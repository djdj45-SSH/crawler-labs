"""实验 09 · 真实战场：blog.djdj45.top

前面的实验都在靶场里做 —— 靶场的规则是我们自己写的，所以我们知道答案。
这个实验换到真实站点，而它恰好是本项目的作者自己的站，
所以两件事同时成立：合规，且真实。

真实站点和靶场的差别
--------------------
  · 靶场：规则随契约公开，被拦时带 X-Dojo-Block 信号头
  · 真实：**没有信号头**。你只能从状态码和落点判断发生了什么

这正是这一课的重点：真实世界里没人会告诉你"你被识别了"。

一个会被忽略的细节
------------------
本实验第一次跑到这里时的真实输出是：**连 sitemap.xml 都被改道了。**
因为 sitemap 是用 requests 默认 UA 抓的，而默认 UA 就是 python-requests。

新手会在这里卡很久 —— 他会以为"站点没有 sitemap"，因为拿到的是 200 和一堆
HTML（其实是 trap 页），正则匹配不到 <loc>。状态码是 200，所以不报错。

所以本实验先把这个现象**明确断言出来**（连入口都被改道了），
再用白名单身份去拿真正的清单。这比"直接用白名单跑通"多教一课。

依赖：需要能访问 blog.djdj45.top。不通时本实验跳过。

为什么离线跑不了
----------------
它抓的是**别人的站**（本项目作者的博客），而且整个教学点就是"真实站点不给你信号头，
只能从状态码和落点推断"。快照能做的是"复现靶场的某一级"，做不了"复现互联网"——
把别人的页面存进自己的仓库，既不合适，也失去了"这是活的"这层意义。
"""

from __future__ import annotations

import os
import re

import requests

from .base import Lab, LabContext, Outcome

BLOG = os.environ.get("BLOG_BASE_URL", "https://blog.djdj45.top")
WHITELIST_UA = "DojoBot/1.0 (+https://blog.djdj45.top/about.html)"


def _trapped(resp) -> bool:
    """真实站点没有信号头，只能看落点是否被改道到了 trap 页。"""
    return "/traps/" in resp.url or "/blocked/" in resp.url


class BlogCapstone(Lab):
    id = "09"
    title = "真实战场：连 sitemap 都被改道了"
    level = "—"
    teaches = "真实站点不会告诉你被识别了 —— 只有一个 200 和一份警告页"
    needs = []
    chapter = "10"

    live_only = True
    live_only_reason = (
        "这一章要的是**真实站点**（blog.djdj45.top），不是被冻结的靶场响应。"
        "需要能联外网。"
    )

    def run(self, ctx: LabContext) -> Outcome:
        sitemap = f"{BLOG}/sitemap.xml"

        # ---- ① 裸身份 —— 期望"连入口都被改道" ----
        try:
            bare_sm = requests.get(sitemap, timeout=8)
        except requests.RequestException as exc:
            return Outcome.skip(f"访问不到 {BLOG}（{type(exc).__name__}: {exc}）", self.level)

        if not _trapped(bare_sm) and bare_sm.status_code != 200:
            return Outcome.skip(f"sitemap 返回 {bare_sm.status_code}，无法继续", self.level)

        # ---- ② 声明身份 —— 拿真正的清单 ----
        good_sm = requests.get(sitemap, headers={"User-Agent": WHITELIST_UA}, timeout=8)
        if good_sm.status_code != 200:
            return Outcome.skip(f"白名单身份抓 sitemap 得到 {good_sm.status_code}", self.level)

        post_urls = re.findall(r"<loc>(https?://[^<]*?/posts/[^<]+)</loc>", good_sm.text)
        if not post_urls:
            return Outcome.fail(
                "白名单身份也解析不出 /posts/ 条目",
                f"{sitemap}\n前 300 字节：\n{good_sm.text[:300]}",
                self.level,
            )

        target = post_urls[0]

        # ---- ③④ 同一篇文章，两个身份 ----
        bare_post = requests.get(target, timeout=8)
        good_post = requests.get(target, headers={"User-Agent": WHITELIST_UA}, timeout=8)

        m = re.search(r"<h1[^>]*>(.*?)</h1>", good_post.text, re.S)
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""

        # 裸身份拿到的东西里应当有 trap 页的身份标记
        bare_has_marker = 'data-client-id=' in bare_post.text

        detail = "\n".join(
            [
                f"① 裸 UA 抓 sitemap   {bare_sm.status_code}  落点 {bare_sm.url}",
                f"② DojoBot 抓 sitemap {good_sm.status_code}  {len(post_urls)} 篇文章",
                f"③ 裸 UA 抓文章       {bare_post.status_code}  落点 {bare_post.url}",
                f"④ DojoBot 抓文章     {good_post.status_code}  标题 {title[:36] or '（未解析出）'}",
                "",
                "① 是这一课最值钱的地方：",
                "  状态的码是 200，而且返回的是 HTML —— 所以 requests 不报错，",
                "  正则也匹配不到 <loc>，你会以为'这个站没有 sitemap'。",
                "  真正发生的是：边缘重定向把你改道到了一个 trap 页。",
                "",
                "③ 同理：状态码 200，内容是'认出你了：python-requests'。",
                "  爬虫不会报错，只会把警告页当成文章正文存下去。",
                "",
                "而且这里没有任何 X-Dojo-Block 之类的信号头 ——",
                "  真实站点不会告诉你被识别了。判断依据只有两个：落点变了，内容变了。",
            ]
        )

        problems = []
        if not _trapped(bare_sm):
            problems.append(f"① 期望 sitemap 被改道，实际落点 {bare_sm.url}")
        if not _trapped(bare_post):
            problems.append(f"③ 期望文章被改道，实际落点 {bare_post.url}")
        if bare_post.status_code != 200:
            problems.append(f"③ 期望 trap 页返回 200（伪装成正常资源），实际 {bare_post.status_code}")
        if not bare_has_marker:
            problems.append("③ trap 页里没有认识到的身份标记（data-client-id）")
        if good_post.status_code != 200 or _trapped(good_post):
            problems.append(f"④ 声明身份后仍不正常：{good_post.status_code} @ {good_post.url}")
        if not title:
            problems.append("④ 白名单身份没解析出文章标题")

        if problems:
            return Outcome.fail(
                f"{len(problems)} 项不符",
                detail + "\n\n" + "\n".join(f"  ✗ {p}" for p in problems),
                self.level,
            )

        return Outcome.pass_(
            f"连 sitemap 都被改道（200 警告页）· DojoBot 拿到 {len(post_urls)} 篇",
            self.level,
            sitemap_posts=len(post_urls),
            bare_trapped=True,
            title=title[:40],
        )
