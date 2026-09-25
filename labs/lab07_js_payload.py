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

离线模式下这个实验比在线更好看
------------------------------
因为它本质上是一个**对照**：同一路径在 L0 是完整列表页、在 L4 是空壳。
在线跑需要切换靶场等级（还要重启进程）；离线跑就是打开两个文件，
把同一段解析代码分别作用在上面 —— 对照是同时看到的，不是记住的。
"""

from __future__ import annotations

import json
import re

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

        lv = ctx.contract.level("L4")
        marker = lv.config.get("shell_marker", "dojo-shell")
        index_url = ctx.dojo.url(ctx.dojo.endpoints["index"])

        # ---- ① 先确认"HTML 里真的没有数据" ----
        page = ctx.fetch(index_url, identity="bare")
        guard = self.ensure_level(ctx, page, "L4")
        if guard:
            return guard

        if page.status_code != 200:
            return Outcome.fail(f"列表页 {page.status_code}", "", self.level)

        shell_signal = ctx.dojo.signaled_by(page)
        soup = BeautifulSoup(page.content, "lxml")

        # 选择器用 `ul li` 而不是 `#dojo-list li`：
        # 真列表页的 <ul> 没有 id —— 用带 id 的选择器去数"有没有数据"，
        # 在空壳和真页上都会得到 0，等于永远验不出空壳失效。
        html_items = soup.select("ul li")

        if not soup.find(attrs={"data-shell": marker}):
            return Outcome.fail(
                "拿到的不是空壳页 —— L4 没生效",
                f"期望 <body data-shell=\"{marker}\">。"
                "检查 l4_jschallenge.py 是否把列表页也拦到了。",
                self.level,
            )

        if html_items:
            return Outcome.fail(
                f"HTML 里解析出了 {len(html_items)} 条 —— 空壳里不该有条目",
                "检查 shell.html 是否被误渲染。",
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
        pl = ctx.fetch(payload_url, identity="bare")
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
        api = ctx.fetch(ctx.dojo.url(ctx.dojo.endpoints["list_json"]), identity="bare")

        # ---- ④ 若手边有 L0 快照，把"同一页的另一面"一并摆出来 ----
        contrast = self.l0_contrast(ctx, index_url)

        detail = "\n".join(
            [
                f"来源           {ctx.source_label}",
                f"列表页         {index_url} → {page.status_code}，"
                f"BS4 解析出 {len(html_items)} 条  ← 数据不在 HTML 里",
                f"空壳标记        data-shell={marker} ✓",
                f"信号头         X-Dojo-Signal: {shell_signal}",
                f"找到的脚本      {scripts[0]}",
                f"载荷            {payload_url} → {pl.status_code}，"
                f"取出 {len(items)} 条",
                f"JSON 接口       /api/articles → {api.status_code}  ← 这一级刻意关掉了",
                *([contrast] if contrast else []),
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
            detail=detail,
            html_items=len(html_items),
            payload_items=len(items),
        )

    @staticmethod
    def l0_contrast(ctx: LabContext, index_url: str) -> str:
        """有 L0 快照的话，把同一页在无防护下的样子解析一遍。

        这是离线模式**额外**给出的东西 —— 在线跑要靠"重启靶场换等级"才能看到。
        没有就静默跳过，不构成失败。
        """
        if not ctx.offline:
            return ""
        import snapshots

        other = snapshots.find("l0")
        if other is None or not other.has("/", "bare"):
            return ""
        r0 = other.get("/", "bare")
        n0 = len(BeautifulSoup(r0.content, "lxml").select("ul li"))
        return (
            f"对照（快照 l0）  同一路径解析出 {n0} 条 ← "
            f"差别只在'数据在不在 HTML 里'，选择器和解析代码一个字没改"
        )
