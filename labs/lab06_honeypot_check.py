"""实验 06 · L3：爬到了，但数据是假的

这是全项目唯一一个"成功了却毫无用处"的场景 —— 也是最重要的一个。

前三级的失败都看得见：403、429，爬虫会报错、会重试、会换办法。
这一级的失败看不见：状态码 200、结构完全正确、字段一个不少。
裸爬脚本会把假数据安静地写进数据库，第二天看报表才发现数字不对。

四种校验（对应契约 levels[L3].flaws 里声明的四条）
--------------------------------------------------
  F1 时间范围     published_at 晚于今天 → 未来日期
  F2 重复率       所有条目正文的 sha1 只有一个值
  F3 链接可达性   url 指向的详情页确实 404
  F4 字段自洽     word_count 与实际正文长度严重不符

这四条都不是"反爬技巧"，是**数据工程的常识**。蜜罐之所以有效，
恰恰因为它攻击的不是你的技术，是你的懒惰 —— 你信任了服务端给的字段。

真实站点上的假数据不会这么明显。这里做浅，是为了让四种校验方法可教。
方法学会之后，换到真实场景只是把阈值调紧。

离线跑时 F1 的基准日的讲究
--------------------------
蜜罐的假日期是**相对"抓取当天"**生成的（`date.today() + 9 天`）。
所以一份快照放久之后，那些"未来日期"会自然变成过去 —— F1 就不再成立。
这不是 bug，是快照会过期的真实样子，也顺带说明"未来日期"这种破绽有多脆。

为了不让读者误以为"校验方法失效了"，离线模式下 F1 用**快照的抓取日**做基准：
判定的是"在观察到它的那一刻，这个日期是不是在未来"。这在语义上也更准确 ——
快照是对某一时刻的冻结观察，就该拿那一刻的钟去衡量它。
"""

from __future__ import annotations

import hashlib

from .base import Lab, LabContext, Outcome


class HoneypotCheck(Lab):
    id = "06"
    title = "L3：四种校验识破蜜罐"
    level = "L3"
    teaches = "爬到 ≠ 有效。将来路不明的字段先当谎言处理"
    needs = ["L3"]
    chapter = "6"

    def run(self, ctx: LabContext) -> Outcome:
        early = self.require(ctx, "L3")
        if early:
            return early

        lv = ctx.contract.level("L3")
        url = ctx.dojo.url(ctx.dojo.endpoints["list_json"])

        r = ctx.fetch(url, identity="bare")
        guard = self.ensure_level(ctx, r, "L3")
        if guard:
            return guard

        if r.status_code != 200:
            return Outcome.fail(
                f"期望蜜罐返回 200（陷阱不该报错），实际 {r.status_code}",
                "蜜罐用 200 才是对的 —— 报错会让爬虫警觉。",
                self.level,
            )

        signal = ctx.dojo.signaled_by(r)
        if signal != (lv.signal or {}).get("value"):
            return Outcome.fail(
                f"信号头不符：期望 {(lv.signal or {}).get('value')}，实际 {signal}",
                "契约里声明了 X-Dojo-Signal: honeypot。",
                self.level,
            )

        items = r.json()
        if not items:
            return Outcome.fail("蜜罐返回 0 条，没法校验", "", self.level)

        today = ctx.reference_date.isoformat()
        findings: list[str] = []

        # ---- F1 时间范围 ----
        future = [a for a in items if a["published_at"] > today]
        if future:
            findings.append(
                f"F1 时间范围    {len(future)}/{len(items)} 条的日期晚于今天"
                f"（例 {future[0]['published_at']}）"
            )

        # ---- F2 重复率 ----
        digests = {hashlib.sha1(a["body"].encode("utf-8")).hexdigest() for a in items}
        if len(digests) < len(items) * 0.5:
            findings.append(
                f"F2 重复率      {len(items)} 条正文只有 {len(digests)} 个不同的 sha1"
            )

        # ---- F3 链接可达性 ----
        sample = items[0]
        detail_url = ctx.dojo.url(sample["url"])
        probe = ctx.fetch(detail_url, identity="bare")
        if probe.status_code >= 400:
            findings.append(
                f"F3 链接可达性  取样 {sample['url']} → {probe.status_code}（死链）"
            )

        # ---- F4 字段自洽 ----
        a = items[0]
        real_len = len(a["body"])
        claimed = a.get("word_count", 0)
        if real_len and claimed > real_len * 3:
            findings.append(
                f"F4 字段自洽   word_count 声称 {claimed}，正文实际 {real_len} 字符"
                f"（{claimed / real_len:.0f} 倍）"
            )

        # ---- 对照：白名单拿到的是真数据 ----
        real = ctx.fetch(url, identity="whitelist")
        real_items = real.json() if real.status_code == 200 else []
        real_digests = {hashlib.sha1(x["body"].encode("utf-8")).hexdigest() for x in real_items}

        detail = "\n".join(
            [
                f"URL           {url}",
                f"来源           {ctx.source_label}",
                f"基准日         {today}"
                + ("   ← 快照抓取日；蜜罐的假日期是相对它生成的"
                   if ctx.offline else "   ← 今天"),
                f"状态码         {r.status_code}   ← 不是错误，是陷阱",
                f"信号头         X-Dojo-Signal: {signal}",
                f"条数           {len(items)}",
                "",
                "四条校验的结果：",
                *(f"  ✓ {f}" for f in findings),
                *([] if findings else ["  （一条都没检出 —— 蜜罐可能失效了）"]),
                "",
                f"对照：白名单身份拿到 {len(real_items)} 条真数据，"
                f"正文 sha1 有 {len(real_digests)} 个不同值。",
                "",
                "记住这四条：时间范围 / 重复率 / 链接可达性 / 字段自洽。",
                "它们不是反爬技巧，是数据工程的常识 —— 蜜罐攻击的正是"
                "'我信任服务端给的字段'这个习惯。",
            ]
        )

        if len(findings) < 4:
            return Outcome.fail(
                f"只检出 {len(findings)}/4 条破绽",
                detail
                + "\n\n契约 levels[L3].flaws 里声明了四条，"
                "检查 l3_honeypot.py 是否都造出来了。",
                self.level,
            )

        return Outcome.pass_(
            f"200 · {len(items)} 条假数据 · 四条破绽全部检出",
            self.level,
            detail=detail,
            fake_count=len(items),
            flaws=[f.split()[0] for f in findings],
        )
