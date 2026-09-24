"""实验 02 · L0 基线：裸爬必须畅通

在任何防护生效之前，先把"能拿到数据"这件事确认下来。
没有基线，后面每加一级你都无法判断"是这一级拦的"还是"本来就抓不到"。

本实验对 `/api/articles` 做三件事：拿到 JSON、数条数、取出标题。
"""

from __future__ import annotations

import requests

from .base import Lab, LabContext, Outcome


class RequestsL0(Lab):
    id = "02"
    title = "L0 基线：用 requests 拿到数据"
    level = "L0"
    teaches = "先建立基线，再加防护 —— 否则分不清是谁拦的"
    needs = []
    chapter = "2"

    def run(self, ctx: LabContext) -> Outcome:
        url = ctx.dojo.url(ctx.dojo.endpoints["list_json"])
        r = requests.get(url, headers=ctx.dojo.whitelist_headers, timeout=5)

        if r.status_code != 200:
            return Outcome.fail(
                f"{r.status_code}",
                f"{url}\n被挡住的信号头：{ctx.dojo.blocked_by(r)}\n"
                "如果你故意想看裸爬被拦的样子，第 4 章会讲；本实验用白名单身份。",
                self.level,
            )

        try:
            items = r.json()
        except ValueError as exc:
            return Outcome.fail("响应不是 JSON", f"{exc}\n前 200 字节：{r.text[:200]}", self.level)

        slugs = [a["slug"] for a in items]
        titles = [a["title"] for a in items]

        detail = "\n".join(
            [
                f"URL    {url}",
                f"条数    {len(items)}",
                f"slug   {', '.join(slugs[:4])}{' …' if len(slugs) > 4 else ''}",
                "",
                "这一级的价值不在'抓到了'，而在'知道正常长什么样'：",
                f"  · 条数应当是 {len(items)}（后面被蜜罐替换时，这个数会变）",
                "  · slug 都应当是 dojo-0x-* 这种可读形式（蜜罐的 slug 也像真的，所以要靠别的维度）",
                "  · 正文长度、日期范围都要先记下来，之后才有比对基准",
            ]
        )

        if len(items) < 3 or not all(slugs):
            return Outcome.fail("数据看起来不完整", detail, self.level)

        return Outcome.pass_(
            f"200 · {len(items)} 条 · 例：{titles[0][:18]}…",
            self.level,
            count=len(items),
            slugs=slugs,
        )
