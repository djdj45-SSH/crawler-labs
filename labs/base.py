"""实验基类。

一个 lab 只回答一个问题：**做对这件事需要什么？**

约定
----
  · `needs` 声明它需要靶场开启哪几级。靶场没开时，lab 会**跳过**并说明原因，
    而不是假装通过 —— 一个会在错误前提下报"成功"的实验，比没有实验更糟。
  · 每个 lab 都要先复现"错误姿势会怎样"，再给出"正确姿势"。
    只讲正确姿势的实验，读者记不住为什么。
  · **取页面一律走 `ctx.fetch()`**，不要直接 `requests.get`。
    这样同一段解析代码能对着实时靶场跑，也能对着快照跑 —— 这是整本书可复现的前提。
    只有真正离不开实时响应的实验（限流、浏览器、签名、真实站点）才直接用 requests，
    并把 `live_only` 打开，说明理由。

`run()` 返回 Outcome；抛 `LabSkip` 会被 runner 转成"跳过"；
其他异常会被 runner 兜住并记为失败（附 traceback）。
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from dojo import headers_for

#: `--snapshot auto` 下用来给"没有明确等级"的实验挑快照（第 1、9 章的实验）。
#: 它们用的是白名单身份，内容层不随等级变，所以拿 L0 这份就够了。
FALLBACK_LEVEL = "L0"


class LabSkip(Exception):
    """没法在**当前前提**下继续 —— 由 runner 转成"跳过"，不是"失败"。

    和 `Outcome.skip()` 的区别：这个用在实验已经跑起来、中途才发现前提不成立的时候
    （最典型的是离线模式下缺某一页快照）。前提检查放在开头的那些仍然返回 Outcome.skip。
    """


@dataclass
class Outcome:
    ok: bool
    summary: str                       # 一句话结论，进矩阵
    level: str = "—"                   # 针对哪一级
    detail: str = ""                   # 多行补充，失败时一定会打印
    skipped: bool = False
    skip_reason: str = ""
    facts: dict[str, Any] = field(default_factory=dict)   # 结构化证据，便于二次利用

    @classmethod
    def skip(cls, reason: str, level: str = "—") -> "Outcome":
        return cls(ok=True, summary="跳过", level=level, skipped=True, skip_reason=reason)

    @classmethod
    def pass_(cls, summary: str, level: str = "—", detail: str = "", **facts: Any) -> "Outcome":
        return cls(ok=True, summary=summary, level=level, detail=detail, facts=facts)

    @classmethod
    def fail(cls, summary: str, detail: str = "", level: str = "—", **facts: Any) -> "Outcome":
        return cls(ok=False, summary=summary, level=level, detail=detail, facts=facts)


class Lab:
    """所有实验的基类。子类覆盖 id / title / level / teaches / needs 和 run()。"""

    id: str = ""
    title: str = ""
    level: str = "—"          # 本实验针对的防护等级
    teaches: str = ""         # 一句话说明学什么
    needs: list[str] = []     # 需要靶场开启的等级；空表示不依赖
    chapter: str = ""         # 对应章节号

    #: True = 必须有**实时**靶场/网络，快照替代不了。打开时请一并写理由。
    live_only: bool = False
    live_only_reason: str = ""

    #: 离线模式下用哪一级的快照。留空则取 `level`，仍为空则取 L0。
    snapshot_level: str = ""

    def run(self, ctx: "LabContext") -> Outcome:
        raise NotImplementedError

    # -- 工具：让每个 lab 都能一致地报"需要某等级" --

    def require(self, ctx: "LabContext", *levels: str) -> Outcome | None:
        """检查靶场（或快照）是否开了所需的等级。返回 None 表示可以继续。"""
        active = set(ctx.contract.active_levels)

        if ctx.offline:
            # 离线模式下"当前生效等级"就是快照抓取时的等级 —— 见 LabContext.use_snapshot。
            # 所以这一段的判断逻辑与在线完全一样，只是措辞要换：
            # 用户需要的是"再抓一份"，而不是"去把靶场重开一遍"。
            need = [lv for lv in levels if lv != "L0"]
            missing = [lv for lv in need if lv not in active]
            if "L0" in levels and active:
                return Outcome.skip(self._offline_msg(ctx, "L0 基线"), self.level)
            if missing:
                return Outcome.skip(self._offline_msg(ctx, "/".join(missing)), self.level)
            return None

        # L0 是特例：它不是一个"等级"而是一种状态（没有任何防护生效）
        if "L0" in levels and not ctx.contract.is_l0():
            return Outcome.skip(
                f"需要 L0 基线（当前生效：{', '.join(sorted(active))}）—— "
                "用 python -m server.main --level none 起靶场",
                self.level,
            )
        need = [lv for lv in levels if lv != "L0"]
        missing = [lv for lv in need if lv not in active]
        if missing:
            return Outcome.skip(
                f"靶场未开启 {'/'.join(missing)}（当前生效："
                f"{', '.join(sorted(active)) or 'L0'}）—— "
                f"用 python -m server.main --level all 起靶场",
                self.level,
            )
        return None

    @staticmethod
    def _offline_msg(ctx: "LabContext", need: str) -> str:
        tag = need.lower()
        return (
            f"快照 {ctx.snapshot.tag} 是在 {ctx.snapshot.level_label} 下抓的，"
            f"本实验需要 {need}。\n"
            f"                抓一份：python snapshot.py --level {tag}\n"
            f"                或一次抓全：python snapshot.py --all（推荐，之后 --snapshot auto 全都能跑）"
        )

    def ensure_level(self, ctx: "LabContext", resp, level_id: str) -> Outcome | None:
        """确认这次响应**真的**来自目标等级。

        为什么必须这一步：防护是叠加的，前一级生效时后一级根本收不到请求。
        `--level all` 下裸 UA 会在 L1 就被拦下，永远到不了 L2 —— 这很真实，
        但会让实验得出错误结论。所以宁可跳过，也不要在错误前提下判"成功"。

        返回 None 表示确实是目标等级。

        ⚠️ 注意 403 拦截页也会带 X-Dojo-Level —— 所以用"目标等级"来比对，
        而不是用"有没有这个头"。

        离线模式下这个方法**一样有用**：冻结的响应里同样带着当时的 X-Dojo-Level，
        所以"这份快照里这一页其实是被 L1 拦下的"也能被发现。
        """
        seen = ctx.dojo.level_of(resp)
        if seen == level_id:
            return None
        if ctx.offline:
            return Outcome.skip(
                f"快照里的这一页实际来自 {seen or '更前面的等级'}，到不了 {level_id}。\n"
                f"                这一份快照是按 {ctx.snapshot.level_label} 抓的 —— "
                f"重新抓：python snapshot.py --level {level_id.lower()}",
                level_id,
            )
        return Outcome.skip(
            f"请求被 {seen or '更前面的等级'} 先生效拦下，到不了 {level_id}。"
            f"单独开启这一级：python -m server.main --level {level_id}",
            level_id,
        )


class LabContext:
    """传给每个 lab 的运行上下文。

    同一个 ctx 会在实验之间被**换契约和换快照**（见 `use_snapshot`）——
    因为离线模式下每个实验需要的是它自己那一级的快照。这件事由 runner 负责，
    lab 只要照常读 `ctx.contract` 就行。
    """

    def __init__(self, dojo, *, verbose: bool = False, offline: bool = False, snapshot=None) -> None:
        self.dojo = dojo
        self.verbose = verbose
        self.offline = offline
        self.snapshot = snapshot
        self._live_contract = dojo.contract
        self.contract = dojo.contract
        #: "#6 判定"未来日期"的基准。在线是今天；离线是快照抓取日 ——
        #: 蜜罐的假日期是相对"抓取当天"生成的，拿今天去比会误判成"日期正常"。
        self.reference_date: dt.date = dt.date.today()
        if snapshot is not None:
            self._apply(snapshot)

    # ---- 离线/在线切换 ----

    def _apply(self, snapshot) -> None:
        from dojo import Contract

        self.contract = Contract.from_json(snapshot.contract_json)
        self.reference_date = snapshot.captured_date

    def use_snapshot(self, snapshot) -> None:
        """换成某一份快照（传 None 表示回到实时契约）。"""
        self.snapshot = snapshot
        if snapshot is None:
            self.contract = self._live_contract
            self.reference_date = dt.date.today()
        else:
            self._apply(snapshot)

    # ---- 取页面：唯一入口 ----

    def fetch(self, url: str, *, identity: str = "bare", timeout: float = 5):
        """取一个页面。在线打靶场，离线读快照 —— 调用方不用关心。

        `identity` 取值见 dojo.IDENTITIES。它是快照的主键之一，所以必须显式给：
        少了它，第 4 章"伪装 vs 声明身份"那个对照就无从复现。
        """
        if self.snapshot is None:
            if self.offline:
                raise LabSkip(
                    "离线模式下没有可用快照 —— 先抓一份："
                    "python snapshot.py --level L3（或 python snapshot.py --all）"
                )
            import requests

            return requests.get(url, headers=headers_for(identity, self.contract), timeout=timeout)

        path = urllib.parse.urlsplit(url).path or "/"
        if not self.snapshot.has(path, identity):
            raise LabSkip(
                f"快照 {self.snapshot.tag} 里没有 {path}（身份 {identity}）。\n"
                f"                这一份里该路径有的身份：{self.snapshot.available(path)}\n"
                f"                重新抓：python snapshot.py --level {self.snapshot.tag} --force"
            )
        self.log(f"fetch[{self.snapshot.tag}] {identity} {path}")
        return self.snapshot.get(path, identity)

    # ---- 显示 ----

    @property
    def source_label(self) -> str:
        """给实验输出用的"这一页是哪来的"。"""
        if self.snapshot is not None:
            return f"快照 {self.snapshot.tag}"
        if self.offline:
            return "离线（无快照）"
        return "实时靶场"

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"      {msg}")
