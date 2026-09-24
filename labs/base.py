"""实验基类。

一个 lab 只回答一个问题：**做对这件事需要什么？**

约定
----
  · `needs` 声明它需要靶场开启哪几级。靶场没开时，lab 会**跳过**并说明原因，
    而不是假装通过 —— 一个会在错误前提下报"成功"的实验，比没有实验更糟。
  · 每个 lab 都要先复现"错误姿势会怎样"，再给出"正确姿势"。
    只讲正确姿势的实验，读者记不住为什么。

`run()` 返回 Outcome；抛异常会被 runner 兜住并记为失败（附 traceback）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    def pass_(cls, summary: str, level: str = "—", **facts: Any) -> "Outcome":
        return cls(ok=True, summary=summary, level=level, facts=facts)

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

    def run(self, ctx: "LabContext") -> Outcome:
        raise NotImplementedError

    # -- 工具：让每个 lab 都能一致地报"需要某等级" --

    def require(self, ctx: "LabContext", *levels: str) -> Outcome | None:
        """检查靶场是否开了所需的等级。返回 None 表示可以继续。"""
        active = set(ctx.contract.active_levels)

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

    def ensure_level(self, ctx: "LabContext", resp, level_id: str) -> Outcome | None:
        """确认这次响应**真的**来自目标等级。

        为什么必须这一步：防护是叠加的，前一级生效时后一级根本收不到请求。
        `--level all` 下裸 UA 会在 L1 就被拦下，永远到不了 L2 —— 这很真实，
        但会让实验得出错误结论。所以宁可跳过，也不要在错误前提下判"成功"。

        返回 None 表示确实是目标等级。

        ⚠️ 注意 403 拦截页也会带 X-Dojo-Level —— 所以用"目标等级"来比对，
        而不是用"有没有这个头"。
        """
        seen = ctx.dojo.level_of(resp)
        if seen == level_id:
            return None
        return Outcome.skip(
            f"请求被 {seen or '更前面的等级'} 先生效拦下，到不了 {level_id}。"
            f"单独开启这一级：python -m server.main --level {level_id}",
            level_id,
        )


class LabContext:
    """传给每个 lab 的运行上下文。"""

    def __init__(self, dojo, *, verbose: bool = False) -> None:
        self.dojo = dojo
        self.verbose = verbose
        self.contract = dojo.contract

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"      {msg}")
