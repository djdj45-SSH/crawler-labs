"""实验 01 · HTTP 基础：先学会读响应

后面所有判断 —— "被拦了没有""拿到的是不是真数据"—— 都建立在这三样上：
状态码、响应头、编码。所以第一个实验不抓任何"数据"，只把响应读一遍。

顺带一个习惯：**从第一个脚本就声明身份。**
本实验用白名单 UA，因为契约端点本来就不拦人（它是自证性的前提）。
这不是取巧 —— 真实世界里，一个有礼貌的爬虫第一次运行时就该带着联系方式。
第 4 章我们才会故意把身份摘掉，看看会发生什么。
"""

from __future__ import annotations

import requests

from .base import Lab, LabContext, Outcome


class HttpBasics(Lab):
    id = "01"
    title = "HTTP 基础：读状态码 / 响应头 / 编码"
    level = "—"
    teaches = "响应里到底有什么，以及为什么不能只看 r.text"
    needs = []
    chapter = "1"

    def run(self, ctx: LabContext) -> Outcome:
        url = ctx.dojo.url(ctx.dojo.endpoints["contract"])
        r = requests.get(url, headers=ctx.dojo.whitelist_headers, timeout=5)

        ctype = r.headers.get("content-type", "")
        lines = [
            f"URL          {url}",
            f"状态码        {r.status_code}",
            f"Content-Type {ctype}",
            f"r.encoding   {r.encoding}       ← 来自响应头，可能不准",
            f"apparent     {r.apparent_encoding}       ← 由内容猜的",
            f"字节数        {len(r.content)}",
            "",
            "为什么不能只看 r.text：",
            "  r.text 用 r.encoding 解码。响应头没写 charset 时，",
            "  requests 会退回 ISO-8859-1，中文就变成乱码。",
            "  稳妥做法：r.content + 显式 .decode('utf-8')，或先看 r.apparent_encoding。",
        ]

        if r.status_code != 200:
            return Outcome.fail(
                f"契约端点返回 {r.status_code}",
                "\n".join(lines),
                self.level,
            )
        if "json" not in ctype:
            return Outcome.fail(
                f"Content-Type 不是 JSON：{ctype}",
                "\n".join(lines),
                self.level,
            )

        # 契约里声明了 signal / whitelist 这些字段，能解析出来才算真的拿到
        doc = r.json()
        has_core = all(k in doc for k in ("levels", "whitelist", "endpoints"))

        return (
            Outcome.pass_(
                f"200 · {ctype.split(';')[0]} · {len(r.content)} 字节",
                self.level,
                status=r.status_code,
                encoding=r.encoding,
                apparent=r.apparent_encoding,
            )
            if has_core
            else Outcome.fail("契约 JSON 缺关键字段", "\n".join(lines), self.level)
        )
