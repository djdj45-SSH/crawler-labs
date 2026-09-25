"""实验 03 · 解析 HTML：用 BeautifulSoup 把列表页拆开

第 2 章抓的是 JSON 接口，但真实站点很多只有 HTML。
本实验抓列表页，解析出每条的标题、日期、标签 ——
并且**断言行数**，因为后面第 7 章（L4 空壳）会让这个数字变成 0。

解析库的选择
------------
  · BeautifulSoup + lxml 解析器：最通用的起点，容错好
  · 如果只要速度，lxml 直接用 XPath 更快，但学习曲线陡一点
  · parsel：Scrapy 同款选择器，写 CSS/XPath 很顺手
这里用前两个，附录 B 里做横向对比。

解析的纪律
----------
**先断言行数，再取字段。** 不检查就 `.get_text()`，页面一改你会拿到一堆空字符串，
而且不会报错 —— 错误会一路传到数据库里。

这一章是最该离线跑的一章
------------------------
调一个选择器不该先起一个服务。抓一次快照，之后所有选择器的调试都对着它跑 ——
一天跑一百次也不会打自己的服务器。而且模板改版之后，旧快照还能复现历史上的解析 bug。
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from .base import Lab, LabContext, Outcome


class ParseBs4(Lab):
    id = "03"
    title = "解析层：BeautifulSoup 拆列表页"
    level = "L0"
    teaches = "先断言行数再取字段 —— 否则页面一改就静默拿到空字符串"
    needs = []
    chapter = "3"

    def run(self, ctx: LabContext) -> Outcome:
        url = ctx.dojo.url(ctx.dojo.endpoints["index"])
        r = ctx.fetch(url, identity="whitelist")

        if r.status_code != 200:
            return Outcome.fail(
                f"{r.status_code}",
                f"{url}\n来源：{ctx.source_label}\n"
                f"被挡住的信号头：{ctx.dojo.blocked_by(r)}",
                self.level,
            )

        soup = BeautifulSoup(r.content, "lxml")
        items = soup.select("ul li")
        titles = [li.select_one("a").get_text(strip=True) for li in items if li.select_one("a")]
        dates = [
            (li.select_one(".meta").get_text(strip=True).split(" · ")[0])
            for li in items
            if li.select_one(".meta")
        ]

        detail = "\n".join(
            [
                f"URL        {url}",
                f"来源        {ctx.source_label}",
                f"解析器      lxml",
                f"li 行数     {len(items)}",
                f"标题        {titles[0] if titles else '（无）'}",
                f"日期        {dates[0] if dates else '（无）'}",
                "",
                "注意这里的两步纪律：",
                "  1. 先数行数 —— 0 行就说明选择器错了，或者数据根本不在 HTML 里（第 7 章）",
                "  2. 再取字段 —— 每个字段都判空，别让 None 流到下游",
                "",
                "反例：直接 soup.select_one('a').get_text() —— 页面一改就是 AttributeError，",
                "      或者更糟：拿到一个空字符串而不报错。",
            ]
        )

        if not items:
            return Outcome.fail(
                "解析到 0 行",
                detail + "\n\n可能原因：选择器过时，或该等级下数据不在 HTML 里（见第 7 章 L4）。",
                self.level,
            )
        if len(titles) != len(items):
            return Outcome.fail(
                f"行数 {len(items)} 但有标题的只有 {len(titles)}",
                detail,
                self.level,
            )

        return Outcome.pass_(
            f"解析出 {len(items)} 条 · 例：{titles[0][:16]}…",
            self.level,
            detail=detail,
            count=len(items),
            first_title=titles[0],
        )
