"""articles spider —— 抓靶场的真数据。

它要证明的是：**Scrapy 里也不该硬编码任何"防护是什么"的知识。**

端点从契约来（`contract.endpoints["list_json"]`），身份从契约来
（`contract.whitelist_ua`）。如果哪天靶场换了路径或换了白名单 token，
这个 spider 一行都不用改 —— 它会跟着新的契约跑。

⚠️ 注意入口方法是 `async def start()`，不是 `start_requests()`
------------------------------------------------------------
Scrapy 2.13 起入口换成了异步的 `start()`。**2.19 里 `start_requests()` 已经完全
不被调用** —— 实跑时表现为"Spider opened 之后立刻 Closing spider (finished)，
0 个请求"，而且不报任何错。查 `scrapy/spidermiddlewares/start.py` 的源码，
里面一次都没提到 `start_requests`。

网上绝大多数教程还在教 `start_requests`。这一条只有跑起来才会发现 ——
正好是本项目想反复强调的那件事：**框架的行为要查源码和实跑，不能凭印象。**
"""

from __future__ import annotations

import json
import os

import scrapy

from dojo import Dojo, fetch_contract
from scrapy_dojo.dojo_spider.items import ArticleItem

FIELDS = ("slug", "title", "published_at", "tags", "word_count", "summary", "body")


class ArticlesSpider(scrapy.Spider):
    name = "articles"

    def __init__(self, base_url: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url or os.environ.get("DOJO_BASE_URL", "http://127.0.0.1:8000")
        self.contract = fetch_contract(self.base_url)
        self.dojo = Dojo(self.base_url, self.contract)
        self.start_url = self.dojo.url(self.dojo.endpoints["list_json"])

    async def start(self):
        active = self.contract.active_levels or ["L0"]
        self.logger.info(
            "契约来源=%s，生效等级=%s，端点=%s",
            self.contract.runtime.get("source"),
            ", ".join(active),
            self.dojo.endpoints["list_json"],
        )

        # 用白名单身份。理由和实验 02/03 一样：这一章要学的是 Scrapy 工程化，
        # 不该被防护噪音干扰。想看裸身份会怎样，跑 honeypot spider。
        yield scrapy.Request(
            self.start_url,
            headers=self.dojo.whitelist_headers,
            callback=self.parse,
            errback=self.on_error,
        )

    def parse(self, response, **kwargs):
        try:
            records = json.loads(response.text)
        except ValueError:
            # L4 会把 JSON 接口关掉（返回 404 + JSON 错误体），蜜罐会返回假 JSON。
            # 两种情况都要能一眼看出来，而不是抛个 JSONDecodeError 让人猜。
            self.logger.error(
                "响应不是 JSON。状态=%s，X-Dojo-Signal=%s，前 160 字节：%s",
                response.status,
                response.headers.get("X-Dojo-Signal", b"").decode("latin-1"),
                response.text[:160],
            )
            return

        for raw in records:
            yield ArticleItem(**{k: raw.get(k) for k in FIELDS}, source="api")

    def on_error(self, failure):
        self.logger.error("请求失败：%s", failure.value)
