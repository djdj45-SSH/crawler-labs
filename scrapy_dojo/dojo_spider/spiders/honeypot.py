"""honeypot spider —— 故意去接一份假数据。

这个 spider 的价值不在"抓到东西"，而在让第 6 章的结论在 Scrapy 里再成立一次：

    它拿到的每一条记录，字段都是齐的、格式都是对的、状态码是 200。
    然后它会**一条都进不了库** —— 被 ValidationPipeline 全部拦下。

如果你只跑 articles spider，你会觉得"校验管道"是多此一举；
跑一遍这个，就知道它拦的是什么。

用法（靶场必须以 L3 起，否则拿不到蜜罐）：

    cd ../crawler-dojo && python -m server.main --level L3
    scrapy crawl honeypot

离线也行（不需要靶场）：

    scrapy crawl honeypot -s DOJO_SNAPSHOT=auto

注意它故意用**裸 User-Agent**：蜜罐只喂给未声明身份的客户端。
用白名单身份请求会拿到真数据 —— 那样就看不到这一课了。
中间件按 UA 反推身份，所以裸 UA + `l3` 快照 = 拿到那份冻下来的假数据。

入口方法同样用 `async def start()`，理由见 articles.py 的说明。
"""

from __future__ import annotations

import json
import os

import scrapy

from dojo import Dojo
from scrapy_dojo.dojo_spider.items import ArticleItem
from scrapy_dojo.dojo_spider.snapshot import load_contract

FIELDS = ("slug", "title", "published_at", "tags", "word_count", "summary", "body")

# 故意用"未声明身份的库默认 UA"。
#
# ⚠️ 不能靠 settings 里的 USER_AGENT 来"什么都不设" —— 那个全局值是白名单身份
#    （DojoBot/1.0），不覆盖的话这个 spider 会拿到**真数据**，
#    信号头也是空的，整个演示就没了。
#
#    实跑时就是这么翻车的：日志里出现 `实际 signal='' status=200`。
#    这也是一课 —— 全局默认值和单请求覆盖的关系，很容易搞错，
#    而且错了之后现象是"一切正常、只是没有你要看的那个东西"。
BARE_UA = "python-requests/2.31.0"


class HoneypotSpider(scrapy.Spider):
    name = "honeypot"

    #: 离线模式下用哪一份快照。蜜罐只存在于 L3，所以这里必须是 l3。
    snapshot_tag = "l3"

    def __init__(self, base_url: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url or os.environ.get("DOJO_BASE_URL", "http://127.0.0.1:8000")

    async def start(self):
        self.contract = load_contract(self, self.base_url)
        self.dojo = Dojo(self.base_url, self.contract)
        self.start_url = self.dojo.url(self.dojo.endpoints["list_json"])

        if "L3" not in self.contract.active_levels:
            self.logger.error(
                "这一章需要 L3 生效，当前生效等级是 %s。\n"
                "  联机：cd ../crawler-dojo && python -m server.main --level L3\n"
                "  离线：scrapy crawl honeypot -s DOJO_SNAPSHOT=auto（用 l3 那份快照）",
                ", ".join(self.contract.active_levels) or "L0",
            )
            return

        # 裸身份 —— 故意的（显式覆盖全局 USER_AGENT，理由见文件顶部）
        yield scrapy.Request(
            self.start_url,
            headers={"User-Agent": BARE_UA},
            callback=self.parse,
            errback=self.on_error,
        )

    def parse(self, response, **kwargs):
        signal = response.headers.get("X-Dojo-Signal", b"").decode("latin-1")
        if signal != "honeypot":
            self.logger.error(
                "期望拿到蜜罐（X-Dojo-Signal: honeypot），实际 signal=%r status=%s。"
                "可能被更前面的等级拦下了 —— 看上一行的 WARNING。",
                signal,
                response.status,
            )
            return

        records = json.loads(response.text)
        self.logger.warning(
            "拿到 %d 条记录。状态码 %s，字段齐全 —— 但它们是假的。"
            "接下来的校验管道会把它们全部拦下。",
            len(records),
            response.status,
        )

        for raw in records:
            yield ArticleItem(**{k: raw.get(k) for k in FIELDS}, source="honeypot")

    def on_error(self, failure):
        self.logger.error("请求失败：%s", failure.value)

    def closed(self, reason):
        # 用 stats 把"到底拦下了几条、为什么"讲清楚 —— 这是这个 spider 的产出
        dropped = self.crawler.stats.get_value("item_dropped_count", 0)
        self.logger.warning(
            "爬取结束（%s）。item 被丢弃 %d 条 —— "
            "全部来自 ValidationPipeline 的字段校验，原因见上面的 WARNING 行。\n"
            "  结论：状态码 200 + 字段齐全 ≠ 数据可用。",
            reason,
            dropped,
        )
