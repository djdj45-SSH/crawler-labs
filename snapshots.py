"""HTML 快照的读取层。

为什么要有它
------------
解析代码的调试不该依赖网络。`fixtures/snapshots/<tag>/` 下是**抓好的响应**，
`ctx.fetch()` 在离线模式下直接读它 —— 于是第 2、3、6、7 章可以拆开靶场跑：

    python snapshot.py --level L3        # 抓一份
    python main.py --snapshot auto        # 全部实验对着快照跑

三个好处都是真的：
  1. **离线可跑** —— 调一个选择器不该先起一个服务
  2. **快且稳** —— 一天跑一百次解析也不会打自己的服务器
  3. **可复现** —— 页面（模板）改版之后，旧快照还能复现历史上的解析 bug

一份快照包含两样东西
--------------------
  响应体          `<tag>/<name>.<ext>`
  它是在什么条件下拿到的   `manifest.json`

第二样常常被忽略，但它才是关键：**同一条路径在不同的防护等级下返回完全不同的内容。**
不知道快照是在哪一级抓的，就没法判断它上面能跑哪个实验。
所以 manifest 里冻结了"抓取时的契约" —— 契约本身就描述了那台靶场当时的状态。

三种身份
--------
同一路径 x 不同身份 = 不同响应。快照按 `(path, identity)` 建索引：

    bare       没有 UA（requests 会填自己的默认值）—— 会被 L1 拦
    browser    伪装成浏览器 —— 能过 L1，但仍不在白名单
    whitelist  声明身份 —— 跳过全部防护，拿到真数据

身份是快照的**主键之一**，不是可选项。少了它，第 4 章那个
"伪装能过但没被接纳"的对照就复现不出来。

不提交进仓库
------------
见 `fixtures/README.md`。一句话：它们能从公开的靶场重新抓，而一旦提交就可能
悄悄过期 —— 解析实验却对着过期页面报"通过"，比失败更糟。

两个消费者
----------
这些文件不只服务手工实验。第 8 章的 Scrapy 工程读的是**同一批**：

    python main.py --snapshot auto                 # lab01–11
    scrapy crawl articles -s DOJO_SNAPSHOT=auto    # scrapy_dojo/

所以改这里要两边一起想。有两样东西是"契约"：

  · `(路径, 身份)` 这个索引键 —— 两边都按它取页
  · manifest 里冻结的契约 —— 两边都拿它当"当前生效等级"的依据

注意身份名单**不在这里**，在 `dojo.py` 的 `IDENTITIES`。
本模块只按 `(路径, 身份)` 索引，不负责定义身份 —— 抄一份过来就会漂移。
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent
SNAPSHOT_DIR = ROOT / "fixtures" / "snapshots"


class SnapshotMiss(RuntimeError):
    """快照里没有这一页 —— 或者这个标签根本不存在。"""


class Headers(dict):
    """不区分大小写地读响应头。

    requests 返回的是 CaseInsensitiveDict，实验室代码到处都用
    `r.headers.get("X-Dojo-Level")` 这种写法。快照如果给一个普通 dict，
    这些读取会**静默返回 None** —— 表现出来就是"快照模式下所有实验都读不到信号头"，
    而它看起来很像靶场坏了。所以这里把同样的手感补上。

    内部一律存小写键（manifest 里也是），查的时候把 key 也转小写。
    """

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        super().__init__({str(k).lower(): str(v) for k, v in (raw or {}).items()})

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(str(key).lower(), default)

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(str(key).lower())

    def __contains__(self, key: object) -> bool:
        return super().__contains__(str(key).lower())


@dataclass(frozen=True)
class Page:
    """manifest 里的一条：某一页在某身份下被抓过。"""

    name: str
    path: str
    identity: str
    file: str
    url: str = ""
    status: int = 0
    content_type: str = ""
    bytes: int = 0
    sha256: str = ""
    reason: str = ""
    error: str = ""
    #: 抓取时 requests 报的编码信息。第 1 章讲的正是"r.text 为什么会乱码"，
    #: 而这两个值是**观察结果**，快照里不记就没法复现那一课。
    encoding: str | None = None
    apparent_encoding: str | None = None
    headers: Headers = field(default_factory=Headers)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Page":
        return cls(
            name=raw["name"],
            path=raw["path"],
            identity=raw["identity"],
            file=raw.get("file", ""),
            url=raw.get("url", ""),
            status=raw.get("status", 0),
            content_type=raw.get("content_type", ""),
            bytes=raw.get("bytes", 0),
            sha256=raw.get("sha256", ""),
            reason=raw.get("reason", ""),
            error=raw.get("error", ""),
            encoding=raw.get("encoding"),
            apparent_encoding=raw.get("apparent_encoding"),
            headers=Headers(raw.get("headers")),
        )


@dataclass
class SnapshotResponse:
    """模仿 requests.Response 的最小接口 —— 只实现实验室真的用到的那些。

    刻意不做得更全（没有 Session、没有 cookies、没有 redirects 历史）：
    一个"看起来什么都能做"的假 Response 会让人忘记自己在读冻结的数据。
    """

    url: str
    status_code: int
    content: bytes
    headers: Headers
    snapshot_tag: str
    encoding: str | None = None
    apparent_encoding: str | None = None
    from_snapshot: bool = True

    @property
    def text(self) -> str:
        """按 requests 的规则解码：`encoding or apparent_encoding`。

        顺序和 `requests.Response.text` 一致 —— 差一个字符，快照读出来的正文
        就可能和当时抓的不一样，而那种差异极难发现（只在某些响应上出现）。
        """
        for enc in (self.encoding, self.apparent_encoding, "utf-8"):
            if not enc:
                continue
            try:
                return self.content.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return self.content.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def __repr__(self) -> str:  # pragma: no cover — 只为调试好看
        return (
            f"<SnapshotResponse [{self.snapshot_tag}] {self.status_code} "
            f"{len(self.content)}B {self.url}>"
        )


class Snapshot:
    """一个标签 = 一次抓取 = 一个防护等级下的完整视野。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = pathlib.Path(root)
        self.tag = self.root.name
        manifest = self.root / "manifest.json"
        if not manifest.exists():
            raise SnapshotMiss(f"{self.root} 里没有 manifest.json")
        self.manifest: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
        self.pages: list[Page] = [Page.from_json(p) for p in self.manifest.get("pages", [])]
        # 只有真的落了文件的才算"有" —— 抓取失败的条目也会写进 manifest（留痕），
        # 但它不该被当成一份可用的快照数据。
        self._by_key: dict[tuple[str, str], Page] = {
            (p.path, p.identity): p for p in self.pages if p.file and not p.error
        }

    # ---------------------------------------------------------------- 元信息

    @property
    def captured_at(self) -> str:
        return self.manifest.get("captured_at", "")

    @property
    def captured_date(self) -> dt.date:
        """抓取那一天。第 6 章判定"未来日期"时以它为基准（见 lab06 的说明）。"""
        raw = self.captured_at[:10]
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            return dt.date.today()

    @property
    def base_url(self) -> str:
        return self.manifest.get("base_url", "")

    @property
    def level_spec(self) -> str:
        return self.manifest.get("level_spec", "")

    @property
    def active_levels(self) -> list[str]:
        return list((self.manifest.get("contract") or {}).get("runtime", {}).get("active_levels") or [])

    @property
    def contract_json(self) -> dict[str, Any]:
        """抓取时的契约（含 runtime.active_levels）。

        离线模式把它当契约用 —— 于是 `require()` 检查的"当前生效等级"
        就是快照抓取时的等级，语义完全对得上。
        """
        doc = dict(self.manifest.get("contract") or {})
        doc.setdefault("runtime", {})
        doc["runtime"]["source"] = f"snapshot:{self.tag}"
        return doc

    def is_l0(self) -> bool:
        return not self.active_levels

    @property
    def level_label(self) -> str:
        """给人看的一句话等级描述。`level_spec` 是命令行写法（可能是 "none"），
        这里是它的语义 —— 报"跳过"时要让用户一眼明白这份快照能跑什么。"""
        return "、".join(self.active_levels) or "L0（无防护）"

    # ---------------------------------------------------------------- 取页

    def has(self, path: str, identity: str = "bare") -> bool:
        return (path, identity) in self._by_key

    def get(self, path: str, identity: str = "bare") -> SnapshotResponse:
        page = self._by_key.get((path, identity))
        if page is None:
            raise SnapshotMiss(
                f"快照 {self.tag} 里没有 {path}（身份 {identity}）\n"
                f"  这一份里有的：{self.available()}"
            )
        return SnapshotResponse(
            url=f"{self.base_url}{path}",
            status_code=page.status,
            content=(self.root / page.file).read_bytes(),
            headers=page.headers,
            snapshot_tag=self.tag,
            encoding=page.encoding,
            apparent_encoding=page.apparent_encoding,
        )

    def available(self, path: str | None = None) -> str:
        if path:
            got = [ident for (p, ident) in self._by_key if p == path]
            return "、".join(sorted(got)) or "（无）"
        return "、".join(f"{p.name}@{p.identity}" for p in self._by_key.values())

    # ---------------------------------------------------------------- 展示

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Snapshot {self.tag} {self.captured_at[:19]} levels={self.active_levels}>"

    def describe(self) -> str:
        lv = "、".join(self.active_levels) or "L0（无防护）"
        return f"{self.tag}（{self.captured_at[:16]} · {lv} · {len(self._by_key)} 页）"


# ---------------------------------------------------------------------------
# 目录级操作
# ---------------------------------------------------------------------------


def available() -> list[Snapshot]:
    """列出所有能用的快照，按标签排序。坏掉的目录直接跳过（不炸整个启动流程）。"""
    if not SNAPSHOT_DIR.exists():
        return []
    out: list[Snapshot] = []
    for child in sorted(SNAPSHOT_DIR.iterdir()):
        if not child.is_dir() or not (child / "manifest.json").exists():
            continue
        try:
            out.append(Snapshot(child))
        except (SnapshotMiss, json.JSONDecodeError):
            continue
    return out


def find(tag: str) -> Snapshot | None:
    root = SNAPSHOT_DIR / tag
    if not (root / "manifest.json").exists():
        return None
    return Snapshot(root)


def load(tag: str) -> Snapshot:
    snap = find(tag)
    if snap is None:
        have = "、".join(s.tag for s in available()) or "（一个都没有）"
        raise SnapshotMiss(
            f"没有名为 {tag!r} 的快照。现有：{have}\n"
            f"  抓一份：python snapshot.py --level {tag}"
        )
    return snap
