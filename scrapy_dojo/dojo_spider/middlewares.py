"""下载器中间件：观测契约信号 + 兑现 Retry-After。

两根柱子，各管一件事
--------------------
**DojoSignalsMiddleware** 把靶场的契约信号头（`X-Dojo-Block` / `X-Dojo-Signal` /
`X-Dojo-Level` / `X-Dojo-Allow`）变成 Scrapy 的 stats 和日志。

  为什么值得单独写一个中间件：被拦的时候 Scrapy 只会说"请求返回了 403"，
  而你需要知道的是"被**哪一级**、用**什么手段**拦的"。这两条信息在响应头里，
  但默认没人去读。加上之后，报告里会直接出现
  `被拦 ua: 12 次`、`被拦 ratelimit: 3 次`。

**Retry-After 的处理**（见 `_honor_retry_after`）。

  为什么非做不可：实测 Scrapy 2.19 的 `RetryMiddleware` **完全不认识
  `Retry-After` 这个响应头**（源码里零命中）。它会重试，但不会等 ——
  三次重试会在同一个限流窗口里全部撞完，然后爬取失败。

顺序要求
--------
本中间件排在 585，**大于** Scrapy 默认 RetryMiddleware 的 550。
Scrapy 的 process_response 按数字**从大到小**调用，所以 585 先看到响应 ——
这样我们才能在重试发生之前先把延迟设好。
"""

from __future__ import annotations

from urllib.parse import urlparse


class DojoSignalsMiddleware:
    """按 Scrapy 2.19 的要求用 from_crawler 拿 crawler，不再接收 spider 参数。"""

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def __init__(self, crawler) -> None:
        self.crawler = crawler

    @property
    def spider(self):
        return self.crawler.spider

    @property
    def stats(self):
        return self.crawler.stats

    # ------------------------------------------------------------------

    def process_response(self, request, response):
        def head(name: str) -> str | None:
            raw = response.headers.get(name)
            return raw.decode("latin-1") if raw else None

        allow = head("X-Dojo-Allow")
        level = head("X-Dojo-Level")
        blocked = head("X-Dojo-Block")
        signal = head("X-Dojo-Signal")

        if allow:
            self.stats.inc_value("dojo/allow/whitelist")
        if level:
            self.stats.inc_value(f"dojo/level/{level}")
        if blocked:
            self.stats.inc_value(f"dojo/blocked/{blocked}")
            self.spider.logger.warning("被 %s 拦下（%s）：%s", level, blocked, request.url)
        if signal:
            # 200 也可能是陷阱。这一条日志是第 6 章那个教训的自动化版本：
            # 「状态码 200」不等于「拿到的是真数据」。
            self.stats.inc_value(f"dojo/signal/{signal}")
            self.spider.logger.warning(
                "数据来自 %s 的 %s 响应，不是真实内容：%s", level, signal, request.url
            )

        if response.status == 429:
            self._honor_retry_after(request, response)

        return response

    # ------------------------------------------------------------------

    def _honor_retry_after(self, request, response) -> None:
        raw = response.headers.get("Retry-After")
        if not raw:
            self.spider.logger.warning("429 但服务端没给 Retry-After，只能靠固定退避")
            return

        try:
            seconds = float(raw.decode("latin-1"))
        except ValueError:
            # Retry-After 也允许 HTTP-date 形式（如 Mon, 23 Sep 2026 10:00:00 GMT）。
            # 这里不解析 —— 机器用延迟秒数更常见，日期形态是给人看的。
            self.spider.logger.warning("Retry-After 不是秒数（%s），跳过", raw)
            return

        # Scrapy 没有"为单个请求设延迟"的 API。可用做法是调这个下载槽的 delay，
        # 效果是**整个域名一起降速** —— 而这恰好就是被限流时该有的行为：
        # 服务端说的是"你太快了"，那就整体慢下来，而不是只把这一次请求推后。
        #
        # ⚠️ 在中间件里 time.sleep 是错的：那会阻塞 Twisted 反应堆，整条爬取都停。
        #    slot.delay 是 DOWNLOAD_DELAY 和 AutoThrottle 共同的落点，用它才对。
        slot_key = request.meta.get("download_slot") or urlparse(request.url).netloc
        try:
            slot = self.crawler.engine.downloader.slots.get(slot_key)
        except AttributeError:
            slot = None

        if slot is None:
            self.spider.logger.warning("拿不到下载槽 %s，跳过 Retry-After 处理", slot_key)
            return

        slot.delay = max(slot.delay, seconds)
        self.stats.inc_value("dojo/retry_after_honored")
        self.spider.logger.info(
            "按 Retry-After 把 %s 的下载延迟设为 %.1fs（限流窗口内整体退让）",
            slot_key,
            slot.delay,
        )
