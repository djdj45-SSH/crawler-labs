"""实验 04 · L1：被拦住之后有两条路，但只有一条是对的路

这是全项目最重要的一课，也是这个实验要证明的东西：

    伪装成浏览器 → 能过，但你**不在白名单里**
    声明自己的身份 → 既过了，而且是被**接纳**

实验三步：
  1. 默认 UA 被 403，信号头 X-Dojo-Block: ua（读契约里的 expect_status 断言）
  2. 换成浏览器 UA → 200。**但响应里没有 X-Dojo-Allow**
  3. 换成白名单 UA → 200，且带 X-Dojo-Allow: whitelist

第 2 步是重点。如果本实验只做第 1、3 步，读者会以为"改 UA"和"声明身份"是等价的 ——
它们都过 200，但含义完全不同：

  伪装 = 在这一条规则上不再被针对，下一条规则还会瞄准你
  声明 = 从"对抗关系"进入"被接纳状态"，后续规则可以主动放行你

真实站点会继续加维度（频率、指纹、行为），伪装的路是走不到头的。
"""

from __future__ import annotations

import requests

from .base import Lab, LabContext, Outcome

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"


class UaWhitelist(Lab):
    id = "04"
    title = "L1：默认 UA 被拦 → 伪装 vs 声明身份"
    level = "L1"
    teaches = "能过 ≠ 被接纳。声明身份才会进入白名单"
    needs = ["L1"]
    chapter = "4"

    def run(self, ctx: LabContext) -> Outcome:
        early = self.require(ctx, "L1")
        if early:
            return early

        lv = ctx.contract.level("L1")
        expect = lv.expect_status
        signal_header = (lv.signal or {}).get("header", "X-Dojo-Block")
        signal_value = (lv.signal or {}).get("value")
        url = ctx.dojo.url(ctx.dojo.endpoints["list_json"])

        # ① 错误姿势：默认身份
        bad = requests.get(url, timeout=5)
        # ② 伪装：装成浏览器
        faked = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=5)
        # ③ 正确姿势：声明身份
        good = requests.get(url, headers=ctx.dojo.whitelist_headers, timeout=5)

        detail = "\n".join(
            [
                f"① 默认 UA      {bad.status_code}    {signal_header}: {ctx.dojo.blocked_by(bad)}",
                f"② 伪装浏览器    {faked.status_code}    {signal_header}: {ctx.dojo.blocked_by(faked)}   "
                f"X-Dojo-Allow: {faked.headers.get('X-Dojo-Allow') or '（无）'}",
                f"③ 声明身份      {good.status_code}    X-Dojo-Allow: {good.headers.get('X-Dojo-Allow') or '（无）'}",
                "",
                "看 ② 和 ③ 的差别：都是 200，但只有 ③ 拿到了 X-Dojo-Allow。",
                "这就是'能过'和'被接纳'的区别 —— 伪装只能在单条规则上过关。",
            ]
        )

        problems = []
        if bad.status_code != expect:
            problems.append(f"① 期望 {expect}，实际 {bad.status_code}")
        if signal_value and ctx.dojo.blocked_by(bad) != signal_value:
            problems.append(f"① 期望信号头 {signal_header}={signal_value}，实际 {ctx.dojo.blocked_by(bad)}")
        if faked.status_code != 200:
            problems.append(f"② 伪装 UA 期望 200，实际 {faked.status_code}")
        if faked.headers.get("X-Dojo-Allow"):
            problems.append("② 伪装 UA 竟然拿到了白名单标记 —— 契约与实现不一致")
        if good.status_code != 200:
            problems.append(f"③ 白名单期望 200，实际 {good.status_code}")
        if not ctx.dojo.allowed(good):
            problems.append("③ 白名单 UA 没有拿到 X-Dojo-Allow: whitelist")

        if problems:
            return Outcome.fail(
                f"{len(problems)} 项断言不符",
                detail + "\n\n" + "\n".join(f"  ✗ {p}" for p in problems),
                self.level,
            )

        return Outcome.pass_(
            f"403 → 伪装 200（无白名单）→ 声明身份 200 + X-Dojo-Allow",
            self.level,
            blocked_status=bad.status_code,
            faked_status=faked.status_code,
            good_status=good.status_code,
        )
