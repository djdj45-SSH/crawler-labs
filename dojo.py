"""契约客户端。

这个文件是"攻"这一侧唯一与靶场耦合的地方 —— 而且它耦合的是**契约**，
不是靶场的实现。

为什么这么做
------------
把"第几级是什么、预期什么状态码"在爬虫里再写一遍，两边一定会漂移：
改了靶场忘了改爬虫，读者跑出错误的结论，然后他会以为是自己代码写错了。

所以这里的规则是：
  · 所有关于"防护是什么"的知识，都从 GET /__dojo/contract 拿；
  · 爬虫代码里只允许出现 "读 X-Dojo-Block 响应头" 这类**契约里声明过的**约定。

离线兜底
--------
契约一旦拉到就落盘到 fixtures/contract.cache.json。之后靶场没起也能读缓存 ——
否则第 3 章（离线解析）没法脱离靶场单独跑。
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 本地靶场的请求绝不走代理
#
# 有些环境（公司网关、抓包工具、CI 沙箱）会设 http_proxy / HTTP_PROXY。
# requests 会把 127.0.0.1 的请求也发给代理 —— 于是你拿到的是代理的错误响应，
# 而它看起来很像"靶场坏了"：502、空响应、缺了契约信号头。
# 这类环境噪音最耗时间（会被误判成代码问题），所以在包被导入时就一次性关掉。
#
# 用 merge 而不是 setdefault：已有 no_proxy 时也要把 loopback 补进去。
# ---------------------------------------------------------------------------
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_existing = {h.strip() for h in os.environ.get("no_proxy", "").split(",") if h.strip()}
os.environ["no_proxy"] = ",".join(sorted(_existing | _LOOPBACK))
os.environ["NO_PROXY"] = os.environ["no_proxy"]

ROOT = pathlib.Path(__file__).resolve().parent
CACHE = ROOT / "fixtures" / "contract.cache.json"


class ContractError(RuntimeError):
    pass


@dataclass
class Level:
    id: str
    name: str
    guard: str | None
    expect_status: int
    signal: dict[str, str] | None
    teaches: list[str] = field(default_factory=list)
    note: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Level":
        return cls(
            id=raw["id"],
            name=raw.get("name", raw["id"]),
            guard=raw.get("guard"),
            expect_status=raw.get("expect_status", 200),
            signal=raw.get("signal"),
            teaches=raw.get("teaches") or [],
            note=raw.get("note", ""),
            config=raw.get("config") or {},
        )


@dataclass
class Contract:
    version: int
    name: str
    whitelist: dict[str, Any]
    endpoints: dict[str, str]
    levels: dict[str, Level]
    runtime: dict[str, Any] = field(default_factory=dict)

    # ---- 运行时信息：当前实际生效的等级 ----

    @property
    def active_levels(self) -> list[str]:
        return self.runtime.get("active_levels") or []

    def is_l0(self) -> bool:
        """L0 是"无防护"基线 —— 生效等级为空就说明现在处于 L0。"""
        return not self.active_levels

    def level(self, level_id: str) -> Level:
        if level_id not in self.levels:
            raise ContractError(f"契约里没有等级 {level_id}")
        return self.levels[level_id]

    @property
    def whitelist_token(self) -> str:
        return self.whitelist["contains"]

    @property
    def whitelist_ua(self) -> str:
        return self.whitelist.get("example", f"DojoBot/1.0 (+{self.endpoints.get('index', '/')})")

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Contract":
        return cls(
            version=raw.get("version", 0),
            name=raw.get("name", "unknown"),
            whitelist=raw.get("whitelist") or {},
            endpoints=raw.get("endpoints") or {},
            levels={lv["id"]: Level.from_json(lv) for lv in raw.get("levels", [])},
            runtime=raw.get("runtime") or {},
        )


def fetch_contract(base_url: str, *, timeout: float = 5.0, use_cache: bool = True) -> Contract:
    """拉契约。失败时退回本地缓存（如果有）。"""
    url = base_url.rstrip("/") + "/__dojo/contract"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        raw.setdefault("runtime", {}).setdefault("source", "live")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return Contract.from_json(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        if not use_cache or not CACHE.exists():
            raise ContractError(
                f"拉不到契约：{url}\n"
                f"  原因：{exc}\n"
                f"  请先在另一个终端启动靶场：cd ../crawler-dojo && python -m server.main"
            ) from exc
        raw = json.loads(CACHE.read_text(encoding="utf-8"))
        raw.setdefault("runtime", {})["source"] = "cache"
        raw["runtime"]["stale_warning"] = f"契约来自本地缓存，靶场当前不可达（{exc}）"
        return Contract.from_json(raw)


class Dojo:
    """靶场客户端：URL 拼接 + 契约信号的读取。

    只提供"读信号"的能力，不提供"判断对错"的能力 ——
    对错由各个 lab 自己按契约断言，这样每个 lab 都能独立讲清它那一课。
    """

    def __init__(self, base_url: str, contract: Contract) -> None:
        self.base = base_url.rstrip("/")
        self.contract = contract

    # ---- URL ----

    def url(self, path: str) -> str:
        return self.base + (path if path.startswith("/") else "/" + path)

    @property
    def endpoints(self) -> dict[str, str]:
        return self.contract.endpoints

    # ---- 身份 ----

    @property
    def bare_headers(self) -> dict[str, str]:
        """未声明身份的客户端。故意留空 UA —— requests 会填上自己的默认值。"""
        return {}

    @property
    def whitelist_headers(self) -> dict[str, str]:
        return {"User-Agent": self.contract.whitelist_ua}

    # ---- 契约信号（这三个头是契约里声明的，不是实现细节）----

    @staticmethod
    def blocked_by(resp) -> str | None:
        return resp.headers.get("X-Dojo-Block")

    @staticmethod
    def signaled_by(resp) -> str | None:
        return resp.headers.get("X-Dojo-Signal")

    @staticmethod
    def allowed(resp) -> bool:
        return resp.headers.get("X-Dojo-Allow") == "whitelist"

    @staticmethod
    def level_of(resp) -> str | None:
        return resp.headers.get("X-Dojo-Level")
