"""实验 10 · L5：时效签名

服务端要求请求带一个 HMAC 签名，签名内容包含**请求路径**和**时间戳**。
本实验把四个性质逐个验证一遍：

  ① 不带签名            → 403
  ② 签名正确且在窗口内   → 200
  ③ 签名绑定路径         → 拿 A 页的签名去请求 B 页，403
  ④ 时间窗过期           → 403

这一课真正教的是"守"
--------------------
靶场把密钥直接公开在契约里，所以"过这一级"本身没有难度。
有价值的是反过来理解：**如果你要给自己的接口加签名，该签什么？**

  · 只签时间戳 → 抄一个签名就能重放 30 秒内的任意请求
  · 签时间戳 + 路径 → 抄走的签名只能用于那一个路径
  · 再签上请求体摘要 → 连内容都改不了（本靶场没做，留给你扩展）

它拦住的不是"爬得慢的人"，是**"先把 URL 清单列出来、之后再慢慢抓"**的人：
那份清单在 30 秒后全部作废。

为什么离线跑不了
----------------
这一级的对错由**服务端现场验签**决定，而时间窗是 30 秒。
快照里存的是一次响应的结果，不是"服务端会不会接受这个签名"的判定过程 ——
把 ③ 和 ④ 冻下来等于把答案抄在纸上，读者验不到任何东西。
"""

from __future__ import annotations

import hashlib
import hmac
import time

import requests

from .base import Lab, LabContext, Outcome


class Signature(Lab):
    id = "10"
    title = "L5：签名绑定路径 + 时间窗"
    level = "L5"
    teaches = "签名该签什么 —— 这是给「守」的一课"
    needs = ["L5"]
    chapter = "11"

    live_only = True
    live_only_reason = (
        "验签是服务端现场做的，而且时间窗只有 30 秒 —— 快照只能冻下结果，"
        "冻不下判定过程。起靶场：python -m server.main --level L5"
    )

    def run(self, ctx: LabContext) -> Outcome:
        early = self.require(ctx, "L5")
        if early:
            return early

        lv = ctx.contract.level("L5")
        cfg = lv.config
        secret = cfg["dev_secret"]
        ts_header = cfg.get("ts_header", "X-Dojo-Ts")
        token_header = cfg.get("token_header", "X-Dojo-Token")
        window = int(cfg.get("window_seconds", 30))

        path = ctx.dojo.endpoints["list_json"]
        url = ctx.dojo.url(path)

        def sign(p: str, ts: int) -> str:
            msg = cfg["message"].format(path=p, ts=ts)
            return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

        def call(p: str, ts: int | None, token: str | None):
            headers = {}
            if ts is not None:
                headers[ts_header] = str(ts)
            if token is not None:
                headers[token_header] = token
            return requests.get(ctx.dojo.url(p), headers=headers, timeout=5)

        now = int(time.time())

        # ① 无签名
        r1 = call(path, None, None)
        # ② 正确签名
        r2 = call(path, now, sign(path, now))
        # ③ 跨路径复用（拿 ② 的签名去请求首页）
        r3 = call("/", now, sign(path, now))
        # ④ 过期
        old = now - window * 3
        r4 = call(path, old, sign(path, old))

        results = [
            ("① 无签名", r1, 403),
            ("② 正确签名", r2, 200),
            ("③ 跨路径复用", r3, 403),
            ("④ 过期签名", r4, 403),
        ]

        # 目标等级校验：L5 在链尾，前面任何一级生效都会先拦下来
        for label, r, _ in results:
            if r.status_code == 200 and ctx.dojo.level_of(r) not in (None, "L5"):
                return Outcome.skip(
                    f"请求被 {ctx.dojo.level_of(r)} 先拦下，到不了 L5。"
                    "单独开启这一级：python -m server.main --level L5",
                    self.level,
                )
        if r1.status_code != 403 or ctx.dojo.blocked_by(r1) != (lv.signal or {}).get("value"):
            seen = ctx.dojo.level_of(r1)
            if seen and seen != "L5":
                return Outcome.skip(
                    f"请求被 {seen} 先生效拦下。单独开启：python -m server.main --level L5",
                    self.level,
                )

        detail = "\n".join(
            [
                f"URL            {url}",
                f"算法           {cfg['algo']}   签名内容 {cfg['message']}",
                f"时间窗         {window} 秒",
                "",
                *(f"{label:14} {r.status_code}   期望 {want}" for label, r, want in results),
                "",
                "③ 是这一级的关键：签名里含请求路径，所以抄一个签名不能跨页面复用。",
                "  如果只签时间戳，一个签名在 30 秒内能重放任意请求 —— 那就等于没签。",
                "",
                "它挡住的是'先把 URL 清单列出来、之后再慢慢抓'的做法：",
                "  清单在 30 秒后全部作废。挡不住的是'边发现边抓'，那需要限流来做。",
            ]
        )

        bad = [f"{label} 期望 {want}，实际 {r.status_code}" for label, r, want in results if r.status_code != want]
        if bad:
            return Outcome.fail(f"{len(bad)} 项不符", detail, self.level)

        return Outcome.pass_(
            f"无签名 403 · 正确 200 · 跨路径 403 · 过期 403",
            self.level,
            window=window,
        )
