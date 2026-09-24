"""Item 管道：校验 → 去重 → 落库 → 报告。

顺序是有理由的，不是随意排的：

    100 校验   不合格的挡在门外（并且说明为什么）
    200 去重   同一次爬取里正文重复的挡掉
    300 落库   幂等 upsert
    900 报告   最后汇总

**校验必须在落库之前** —— 一旦脏数据进了库，你就得写脚本去清理，
而清理脚本本身也需要校验，等于把同一个问题做两遍。

这里复用 `storage/models.py` 的 upsert，和实验 11 是同一份实现 ——
教学项目和目标工程用同一套写入逻辑，读者不用学两遍。

关于 spider 参数
----------------
实跑时 Scrapy 2.19 会对每个带 `spider` 参数的方法给出弃用警告，原文是：

    "process_item() requires a spider argument, this is deprecated and the
     argument will not be passed in future Scrapy versions. If you need to
     access the spider instance you can save the crawler instance passed to
     from_crawler() and use its spider attribute."

所以下面统一用 CrawlerAware：在 from_crawler 里存下 crawler，需要 spider 时
走 `self.spider`。现在两种写法都能跑，但以后的 Scrapy 只认这一种。
"""

from __future__ import annotations

import hashlib
import pathlib
from datetime import date

from itemadapter import ItemAdapter
from scrapy import signals
from scrapy.exceptions import DropItem
from sqlalchemy.orm import Session

from storage.models import init_db, log_fetch, make_engine, upsert

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


class CrawlerAware:
    """把 crawler 存下来，替代已经弃用的 spider 参数。"""

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


class ValidationPipeline(CrawlerAware):
    """数据校验：把"结构对但值可疑"的条目挡下来。

    这一环对应第 6 章（蜜罐）的结论 —— 校验不是可选的洁癖，
    它是把"服务端给的字段"和"事实"分开的唯一手段。

    三条规则都是机械可判的，不依赖任何领域知识：
      · 必填字段不能为空
      · 日期不能是未来（站点不可能有"明天发布"的文章）
      · word_count 与正文实际长度的偏差不能超过 3 倍

    被丢掉的每条都记进 stats —— 静默丢弃比不校验更危险。
    """

    REQUIRED = ("slug", "title", "published_at", "body")

    def open_spider(self) -> None:
        self.stats.set_value("dojo/validation/reasons", [])

    def process_item(self, item):
        adapter = ItemAdapter(item)
        slug = adapter.get("slug") or "（无 slug）"

        missing = [f for f in self.REQUIRED if not adapter.get(f)]
        if missing:
            self._reject(slug, f"缺字段 {'/'.join(missing)}")
            raise DropItem(f"{slug}: 缺字段 {'/'.join(missing)}")

        published = str(adapter.get("published_at"))
        if published > date.today().isoformat():
            self._reject(slug, f"未来日期 {published}")
            raise DropItem(f"{slug}: 未来日期 {published}")

        claimed = int(adapter.get("word_count") or 0)
        actual = len(str(adapter.get("body") or ""))
        if actual and claimed > actual * 3:
            self._reject(slug, f"word_count 声称 {claimed}，正文实际 {actual}")
            raise DropItem(f"{slug}: word_count 与正文长度不符（{claimed} vs {actual}）")

        return item

    def _reject(self, slug: str, reason: str) -> None:
        reasons = list(self.stats.get_value("dojo/validation/reasons", []))
        reasons.append(f"{slug} — {reason}")
        self.stats.set_value("dojo/validation/reasons", reasons)
        self.stats.inc_value("dojo/validation/dropped")


class DupeBodyPipeline(CrawlerAware):
    """正文 sha1 去重（只在单次爬取内）。

    跨次去重靠 SQLite 的 slug 主键 upsert —— 两件事不要混为一谈：

      · 同一次里正文重复  → 几乎肯定是采集源有问题（蜜罐的典型形态）
      · 跨次抓到的同一条  → 正常的重复抓取，应该更新而不是丢弃
    """

    def open_spider(self) -> None:
        self.seen: dict[str, str] = {}

    def process_item(self, item):
        adapter = ItemAdapter(item)
        body = str(adapter.get("body") or "")
        digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
        slug = adapter.get("slug")

        if digest in self.seen:
            self.stats.inc_value("dojo/dupe_body/dropped")
            self.spider.logger.warning(
                "正文重复：%s 与 %s 的正文完全相同 —— 这是蜜罐的典型特征",
                slug,
                self.seen[digest],
            )
            raise DropItem(f"{slug}: 正文与 {self.seen[digest]} 重复")

        self.seen[digest] = slug
        return item


class SqlitePipeline(CrawlerAware):
    """落库。默认写 `data/scrapy.db`（已 gitignore）。

    爬完一次再跑一次，你会看到 新增 0 / 更新 6 —— 这就是幂等。
    爬虫一定会重跑，重跑不该产生重复数据。
    """

    def open_spider(self) -> None:
        db_url = self.spider.settings.get(
            "DOJO_DB_URL", f"sqlite:///{ROOT / 'data' / 'scrapy.db'}"
        )
        (ROOT / "data").mkdir(exist_ok=True)
        self.engine = make_engine(db_url)
        init_db(self.engine)
        self.buffer: list[dict] = []

    def process_item(self, item):
        # 攒着，close_spider 时一次性 upsert ——
        # 这样幂等统计的口径才是"一次爬取一批"，而不是逐条来回提交。
        self.buffer.append(dict(ItemAdapter(item)))
        return item

    def close_spider(self) -> None:
        if not self.buffer:
            return
        spider = self.spider
        with Session(self.engine) as session:
            result = upsert(session, self.buffer)
            log_fetch(
                session,
                url=getattr(spider, "start_url", ""),
                status=200,
                rows=len(self.buffer),
                identity="whitelist",
                note=f"scrapy_dojo/{spider.name}",
            )
        self.stats.set_value("dojo/store/inserted", result["inserted"])
        self.stats.set_value("dojo/store/updated", result["updated"])
        self.stats.set_value("dojo/store/rejected", result["rejected"])


class ReportPipeline(CrawlerAware):
    """汇总"这次爬取到底发生了什么"。

    单独一环的价值在于：Scrapy 默认按请求打日志，散在几千行里，
    而你要的是"收了多少、丢了多少、为什么丢" —— 一句话。

    ⚠️ 为什么打印不在 close_spider 里做
    ------------------------------------
    实跑发现：Scrapy 关闭管道是**数字从大到小**的顺序（900 先于 300），
    所以如果报告写在 close_spider 里，它会在落库之前打印 ——
    输出里会出现"入库 新增 0 · 更新 0"，而 stats 里明明写着 inserted=6。

    而且 `process_item` 的顺序是**从小到大**（100 → 900），
    两者方向相反，没法用同一个数字同时满足。

    解法是把两件事分开：
      · 数条目   → 管道职责，写在 process_item（顺序正确）
      · 打印报告 → 生命周期职责，挂到 spider_closed 信号

    spider_closed 在所有管道都 close 完之后才触发，所以读数一定是齐的。
    这也是为什么"报告"这种东西不该做成管道 —— 它本来就不是管道。
    """

    @classmethod
    def from_crawler(cls, crawler):
        obj = cls(crawler)
        crawler.signals.connect(obj.print_report, signal=signals.spider_closed)
        return obj

    def open_spider(self) -> None:
        self.count = 0

    def process_item(self, item):
        self.count += 1
        return item

    def print_report(self, spider, reason: str = "finished", **kwargs) -> None:
        s = self.stats
        reasons = list(s.get_value("dojo/validation/reasons", []))
        inserted = s.get_value("dojo/store/inserted", 0)
        updated = s.get_value("dojo/store/updated", 0)
        rejected = list(s.get_value("dojo/store/rejected", []) or [])

        lines = [
            "",
            "─" * 64,
            f"scrapy_dojo · {spider.name}（{reason}）",
            f"  通过校验     {self.count} 条",
        ]
        if s.get_value("dojo/validation/dropped"):
            lines.append(f"  校验拦下     {s.get_value('dojo/validation/dropped')} 条，原因：")
            for r in reasons[:8]:
                lines.append(f"                 {r}")
        if s.get_value("dojo/dupe_body/dropped"):
            lines.append(f"  正文去重     {s.get_value('dojo/dupe_body/dropped')} 条")
        lines.append(f"  入库         新增 {inserted} · 更新 {updated}")
        if rejected:
            lines.append(f"  入库拒收     {len(rejected)} 条（正文与已入库记录重复）")
        for name in ("ua", "ratelimit", "signature"):
            if s.get_value(f"dojo/blocked/{name}"):
                lines.append(f"  被拦         {name}: {s.get_value(f'dojo/blocked/{name}')} 次")
        if s.get_value("dojo/retry_after_honored"):
            lines.append(f"  退避         按 Retry-After 降速 {s.get_value('dojo/retry_after_honored')} 次")
        lines.append("─" * 64)

        spider.logger.info("\n".join(lines))
