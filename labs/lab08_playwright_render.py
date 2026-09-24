"""实验 08 · L4 备选方案：真的只能上浏览器时

这个实验是上一条的对照组。它要证明的不是"Playwright 多好用"，
而是**它的代价有多大** —— 然后你才知道什么时候值得付这个代价。

实验会做同一件事（拿到 N 条记录）两遍：
  ① 读文本载荷（实验 07 的做法）
  ② 用 Playwright 启动 Chromium、渲染、再从 DOM 里取

然后把两边的耗时并排打出来。

什么时候必须在 ② 里做
----------------------
  · 数据由 JS 计算得出，而不是从某个接口/文件读来的
  · 需要交互（点击、滚动、登录）才会出现
  · 站点对无浏览器特征的请求直接拒绝，而你又必须拿到（先想清楚这合不合规）

什么时候不该用 ②
----------------
  · 只要有个 JSON 接口或静态载荷 —— 那样快几十倍，而且稳定
  · 只是为了省掉分析工作 —— 分析一次，比每次跑浏览器便宜得多

依赖：playwright 是可选依赖。没装时本实验跳过并打印安装命令。
"""

from __future__ import annotations

import time

import requests

from .base import Lab, LabContext, Outcome

INSTALL_HINT = (
    "pip install playwright && playwright install chromium\n"
    "  （Chromium 大约 150 MB，装在 ~/.cache/ms-playwright）"
)


class PlaywrightRender(Lab):
    id = "08"
    title = "L4 对照：浏览器渲染的代价"
    level = "L4"
    teaches = "渲染是最后手段 —— 用耗时差证明这句话"
    needs = ["L4"]
    chapter = "7"

    def run(self, ctx: LabContext) -> Outcome:
        early = self.require(ctx, "L4")
        if early:
            return early

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return Outcome.skip(f"未安装 playwright —— {INSTALL_HINT}", self.level)

        page_url = ctx.dojo.url(ctx.dojo.endpoints["index"])

        # ---- ① 文本路径 ----
        t0 = time.perf_counter()
        index = requests.get(page_url, timeout=5)
        guard = self.ensure_level(ctx, index, "L4")
        if guard:
            return guard

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(index.content, "lxml")
        scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
        payload_text = (
            requests.get(ctx.dojo.url(scripts[0]), timeout=5).text if scripts else ""
        )
        cheap_ms = (time.perf_counter() - t0) * 1000

        # ---- ② 浏览器路径 ----
        t1 = time.perf_counter()
        rendered = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(page_url, wait_until="load")
                # 等列表容器里真的出现条目，而不是死等固定毫秒
                page.wait_for_selector("#dojo-list li", timeout=5000)
                rendered = page.eval_on_selector_all(
                    "#dojo-list li a", "els => els.map(e => e.textContent.trim())"
                )
                browser.close()
        except Exception as exc:  # noqa: BLE001 — 浏览器失败的面很宽，这里要全兜住
            return Outcome.fail(
                "Playwright 渲染失败",
                f"{type(exc).__name__}: {exc}\n\n{INSTALL_HINT}",
                self.level,
            )
        browser_ms = (time.perf_counter() - t1) * 1000

        ratio = browser_ms / cheap_ms if cheap_ms else float("inf")

        detail = "\n".join(
            [
                f"同一个页面，同一份数据，两条路：",
                f"  ① 读脚本载荷    {cheap_ms:7.1f} ms   文本请求 ×2",
                f"  ② 浏览器渲染    {browser_ms:7.1f} ms   启动 Chromium + 执行 JS",
                f"  代价倍数        {ratio:.0f}×",
                "",
                f"② 渲染出 {len(rendered or [])} 条：{(rendered or ['（无）'])[:3]}",
                "",
                "注意这个倍数还是乐观的：它没算首次浏览器下载（约 150 MB），",
                "也没算在 CI 里渲染偶发挂掉时要重试的那几次。",
                "",
                "所以顺序是：接口 → 静态载荷 → 浏览器。别倒过来。",
            ]
        )

        if not rendered:
            return Outcome.fail("渲染后仍然没有条目", detail, self.level)

        return Outcome.pass_(
            f"文本 {cheap_ms:.0f}ms vs 浏览器 {browser_ms:.0f}ms（{ratio:.0f}×）",
            self.level,
            cheap_ms=round(cheap_ms, 1),
            browser_ms=round(browser_ms, 1),
            ratio=round(ratio, 1),
            items=len(rendered),
        )
