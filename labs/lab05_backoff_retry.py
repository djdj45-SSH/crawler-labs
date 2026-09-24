"""实验 05 · L2：被限流之后怎么办

这一级不判断你是谁，只看你快不快。所以它是**唯一一级伪装没有用的** ——
换个 UA 解决不了"你打得太快"。

实验要证明两件事：
  1. 无视 Retry-After 的爬虫，会在窗口边缘一直撞墙
  2. 读了 Retry-After 并退避的爬虫，一次就过

为什么手写退避而不用 tenacity
----------------------------
tenacity 在 requirements 里，生产代码该用它。但这里手写一遍指数退避，
是为了让你看见"退避"到底是什么：等多久、为什么是指数、为什么要加抖动。

  固定间隔重试 → 所有被限流的客户端在同一时刻齐步重试，把服务端再打一次
  指数退避     → 冲突概率随重试次数指数下降
  加抖动       → 打散同时性，避免"退避步调一致"这种隐性同步

真实站点上，抖动（jitter）往往比退避本身更重要。
"""

from __future__ import annotations

import random
import time

import requests

from .base import Lab, LabContext, Outcome


class BackoffRetry(Lab):
    id = "05"
    title = "L2：读 Retry-After 并退避重试"
    level = "L2"
    teaches = "限流是唯一伪装没用的一级；退避 + 抖动才是解法"
    needs = ["L2"]
    chapter = "5"

    MAX_ATTEMPTS = 12

    def run(self, ctx: LabContext) -> Outcome:
        early = self.require(ctx, "L2")
        if early:
            return early

        lv = ctx.contract.level("L2")
        limit = int(lv.config.get("requests", 5))
        window = float(lv.config.get("window_seconds", 10))
        url = ctx.dojo.url(ctx.dojo.endpoints["list_json"])

        # ---- ① 一直打到被限流 ----
        # 注意这里的分支顺序：200 时**不能**去做等级校验。
        # 没被拦的响应本来就没有 X-Dojo-Level，拿它去 ensure_level 会误判成
        # "被更前面的等级拦下了" —— 第一版就是这么错的，表现是永远跳过。
        hit = None
        attempts = 0
        for _ in range(self.MAX_ATTEMPTS):
            attempts += 1
            r = requests.get(url, timeout=5)

            if r.status_code == 200:
                continue

            if r.status_code == lv.expect_status:
                guard = self.ensure_level(ctx, r, "L2")
                if guard:
                    return guard
                hit = r
                break

            # 既不是 200 也不是 429 —— 只可能是被更前面的等级拦住了
            guard = self.ensure_level(ctx, r, "L2")
            return guard or Outcome.fail(
                f"意外状态码 {r.status_code}",
                f"{url}\n响应头：{dict(r.headers)}",
                self.level,
            )

        if hit is None:
            return Outcome.fail(
                f"连打 {attempts} 次都没被限流",
                f"契约说 {window:g} 秒内上限 {limit} 次，但 {attempts} 次都过了。\n"
                "检查 L2.config 与 l2_ratelimit.py 是否一致。",
                self.level,
            )

        retry_after = hit.headers.get("Retry-After")
        blocked_signal = ctx.dojo.blocked_by(hit)

        if not retry_after:
            return Outcome.fail(
                "429 没有带 Retry-After",
                f"{limit} 次后确实被限流了，但响应里没有 Retry-After。\n"
                "没有它，客户端只能瞎猜要等多久 —— 这是服务端该给的信息。",
                self.level,
            )

        # ---- ② 按 Retry-After 退避，再试一次 ----
        wait = float(retry_after)
        # 抖动：在建议值上加 0~15% 的随机量。真实场景里这一步能避免齐步重试。
        jittered = wait * (1 + random.uniform(0, 0.15))
        self._sleep(jittered, ctx)

        ok = requests.get(url, timeout=5)

        detail = "\n".join(
            [
                f"URL            {url}",
                f"契约           {window:g} 秒 / {limit} 次",
                f"第 {attempts} 次       {hit.status_code}  {blocked_signal=}  Retry-After={retry_after}",
                f"退避            {jittered:.1f} 秒（建议 {wait:g} + 抖动）",
                f"退避后重试      {ok.status_code}",
                "",
                "为什么要加抖动：",
                "  如果所有被限流的客户端都严格等 10 秒，它们会在同一时刻齐步重试，",
                "  服务端在第 10 秒又收到一波洪峰。抖动把这批请求在时间轴上摊开。",
                "",
                "为什么不用固定 1 秒重试：",
                "  限流窗口是 10 秒。固定 1 秒重试 = 10 次无效请求，而且每次都刷新计数器。",
                "  读 Retry-After 是服务端直接告诉你答案，别自己猜。",
            ]
        )
        if ok.status_code != 200:
            return Outcome.fail(
                f"退避 {jittered:.1f} 秒后仍是 {ok.status_code}",
                detail + "\n\n可能原因：Retry-After 的算法与窗口边界不一致。",
                self.level,
            )

        return Outcome.pass_(
            f"{limit} 次后 429 · Retry-After={retry_after}s · 退避后 200",
            self.level,
            limit=limit,
            window=window,
            retry_after=retry_after,
            attempts=attempts,
        )

    @staticmethod
    def _sleep(seconds: float, ctx: LabContext) -> None:
        ctx.log(f"sleep {seconds:.1f}s")
        time.sleep(seconds)
