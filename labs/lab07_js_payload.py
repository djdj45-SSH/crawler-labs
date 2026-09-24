"""实验 07 · L4：HTML 里没有数据，先找数据源，再考虑上浏览器

这一级的列表页是个空壳：`<ul id="dojo-list"></ul>` 里什么都没有，
正文由一段 `<script src>` 在浏览器里现拼。用 BeautifulSoup 解析得到 0 条。

重要的不是"怎么渲染它"，而是**先别急着渲染**
-----------------------------------------------
看到 HTML 抓不到数据，很多人的第一反应是"上 Playwright"。
那是最后手段，不是第一手段。正确的顺序是：

  1. 看 HTML 里有没有别的线索 —— script src、内联 JSON、注释
  2. 看有没有更省事的接口 —— 有时前端请求的 JSON 接口并没有写在文档里
  3. 以上都没有，才上浏览器

本实验走第 1 步：载荷就明明白白写在 `<script src="/static/dojo-data.js">` 里，
而且那个文件是**可以直接下载的普通文本**。

对照案例（第 7 章下半）：游戏站 blockwild-game 的数据藏在 src/sim/*.js 深处，
连一个规整的载荷文件都没有 —— 那才是必须上浏览器的处境。
"""

from __future__ import annotations

import json
import re

import requests
from bs4 import BeautifulSoup

from .base import Lab, LabContext, Outcome


class JsPayload(Lab):
    id = "07"
    title = "L4：HTML 没数据 → 读脚本载荷"
    level = "L4"
    teaches = "上浏览器是最后手段。先找数据源"
    needs = ["L4"]
    chapter = "7"

    def run(self, ctx: LabContext) -> Outcome:
        early = self.require(ctx, "L4")
        if early:
            return early

        index_url = ctx.dojo.url(ctx.dojo.endpoints["index"])

        # ---- ① 先确认"HTML 里真的没有数据" ----
        page = requests.get(index_url, timeout=5)
        guard = self.ensure_level(ctx, page, "L4")
        if guard:
            return guard

        if page.status_code != 200:
            return Outcome.fail(f"列表页 {page.status_code}", "", self.level)

        shell_signal = ctx.dojo.signaled_by(page)
        soup = BeautifulSoup(page.content, "lxml")
        html_items = soup.select("#dojo-list li")

        if html_items:
            return Outcome.fail(
                f"HTML 里解析出了 {len(html_items)} 条 —— L4 的空壳没生效",
                "检查 l4_jschallenge.py 是否把列表页也拦到了。",
                self.level,
            )

        # ---- ② 从 HTML 里找到数据源 ----
        scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
        if not scripts:
            return Outcome.fail(
                "HTML 里没有任何外部脚本 —— 找不到数据源线索了",
                "真实场景里这时才轮到上浏览器。",
                self.level,
            )

        # ---- ③ 直接下载荷 ----
        payload_url = ctx.dojo.url(scripts[0])
        pl = requests.get(payload_url, timeout=5)
        if pl.status_code != 200:
            return Outcome.fail(f"载荷 {payload_url} → {pl.status_code}", "", self.level)

        # 载荷是 `window.DOJO_ARTICLES = [...]` 形式。用正则取出数组再交给 json。
        # 生产代码里别这么干（正则解析 JS 很脆），应该用 js2py/quickjs 或直接找 JSON 接口。
        # 这里正则够用，而且正好演示"边界在哪"。
        m = re.search(r"=\s*(\[.*\])\s*;", pl.text, re.S)
        if not m:
            return Outcome.fail(
                "载荷里没有找到数组字面量",
                f"前 200 字节：{pl.text[:200]}",
                self.level,
            )

        try:
            items = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            return Outcome.fail("载荷不是合法 JSON 数组", str(exc), self.level)

        # 对照组：JSON 接口在这一级是被关掉的
        api = requests.get(ctx.dojo.url(ctx.dojo.endpoints["list_json"]), timeout=5)

        detail = "\n".join(
            [
                f"列表页         {index_url} → {page.status_code}，"
                f"BS4 解析出 {len(html_items)} 条  ← 数据不在 HTML 里",
                f"信号头         X-Dojo-Signal: {shell_signal}",
                f"找到的脚本      {scripts[0]}",
                f"载荷            {payload_url} → {pl.status_code}，"
                f"取出 {len(items)} 条",
                f"JSON 接口       /api/articles → {api.status_code}  ← 这一级刻意关掉了",
                "",
                "顺序很重要：",
                "  先读 HTML 里的线索（script src）→ 再下载荷 → 实在没有才上浏览器。",
                "  渲染一个页面要几百毫秒到几秒，读一个文本文件只要几十毫秒。",
                "  而且浏览器在 CI 里经常挂，文本请求不会。",
            ]
        )

        if len(items) < 3:
            return Outcome.fail(f"载荷里只有 {len(items)} 条", detail, self.level)
        if not items[0].get("title"):
            return Outcome.fail("载荷条目字段不全", detail, self.level)

        return Outcome.pass_(
            f"HTML 0 条 → 载荷 {len(items)} 条（未启用浏览器）",
            self.level,
            html_items=len(html_items),
            payload_items=len(items),
        )
