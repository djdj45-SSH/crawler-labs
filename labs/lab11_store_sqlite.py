"""实验 11 · 数据落地：幂等写入与写入层的蜜罐防线

前 10 个实验都在解决"怎么拿到数据"。这个实验解决"拿到之后怎么存得不后悔"。

两个具体问题
------------
  ① **幂等**：爬虫一定会重跑。重跑一次就多一批重复数据，是新手最常见的坑。
     解法是把站点给的自然键（slug）当主键做 upsert，而不是自增 id + 追加。

  ② **写入层也要防蜜罐**：第 6 章在读取层做了校验，但校验会漏。
     写入层的最后一道闸是"正文 sha1 重复就拒收" ——
     它拦不住所有假数据，但能拦住"同一段正文铺满整个列表"这种最典型的形态。

实验会：
  1. 用白名单身份抓一次真数据 → 入库
  2. **再抓一次同样入库** → 断言 inserted == 0（幂等生效）
  3. 灌一批"正文完全相同"的脏数据 → 断言全部被拒收，且**列出来**而不是静默丢弃

第 3 步的做法值得注意：拒收一定要留痕。真实场景里这条规则会误伤
（两篇文章引用同一段长文是可能的），所以被拒的条目要能一眼看到、能复核。
静默丢弃比不校验更危险 —— 你会以为数据是完整的。
"""

from __future__ import annotations

import pathlib

import requests
from sqlalchemy.orm import Session

from storage.models import init_db, log_fetch, make_engine, stats, upsert

from .base import Lab, LabContext, Outcome

ROOT = pathlib.Path(__file__).resolve().parent.parent


class StoreSqlite(Lab):
    id = "11"
    title = "数据落地：幂等 upsert + 写入层拒收"
    level = "—"
    teaches = "重跑不产生重复；拒收要留痕，不能静默丢弃"
    needs = []
    chapter = "9"

    def run(self, ctx: LabContext) -> Outcome:
        # 每次从**空库**开始。
        #
        # 第一版用的是默认库 data/dojo.db，结果第二次跑实验时 ① 就报
        # inserted=0 —— 因为上一轮的数据还在库里。实验本身有状态，就不可复现，
        # 而这一个实验的全部意义恰恰是"证明重跑不会产生重复"。
        # 所以这里用独立的库文件，并在开始前删掉它。
        db_file = ROOT / "data" / "lab11.db"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        db_file.unlink(missing_ok=True)

        engine = make_engine(f"sqlite:///{db_file}")
        init_db(engine)

        url = ctx.dojo.url(ctx.dojo.endpoints["list_json"])
        r = requests.get(url, headers=ctx.dojo.whitelist_headers, timeout=5)
        if r.status_code != 200:
            return Outcome.fail(
                f"{r.status_code}",
                f"{url}\n本实验用白名单身份取真数据，避免防护干扰",
                self.level,
            )
        rows = r.json()

        with Session(engine) as s:
            first = upsert(s, rows)
            log_fetch(s, url=url, status=r.status_code, rows=len(rows), identity="whitelist")

        # ---- ② 重复抓取：幂等 ----
        with Session(engine) as s:
            second = upsert(s, rows)

        # ---- ③ 灌脏数据：写入层拒收 ----
        # 这四条用的是**已入库真文章**的正文 —— 对应蜜罐最典型的形态：
        # 一整套"结构完全正确"的假条目，共用同一段正文。
        real_body = rows[0]["body"]
        dirty = []
        for i in range(4):
            dirty.append(
                {
                    "slug": f"dirty-{i}",
                    "title": f"伪造条目 {i}",
                    "published_at": "2099-01-01",
                    "tags": ["fake"],
                    "word_count": 9999,
                    "summary": "重复正文",
                    "body": real_body,
                }
            )
        with Session(engine) as s:
            third = upsert(s, dirty)

        st = stats(engine)

        detail = "\n".join(
            [
                f"数据库        {engine.url}",
                f"① 首次入库    inserted={first['inserted']}  updated={first['updated']}",
                f"② 重复抓取    inserted={second['inserted']}  updated={second['updated']}"
                f"   ← inserted 必须是 0",
                f"③ 脏数据      inserted={third['inserted']}  拒收 {len(third['rejected'])} 条",
                *[f"                拒收：{x}" for x in third["rejected"]],
                "",
                f"库内现状      文章 {st['articles']} 条 · 不同正文 {st['distinct_bodies']} 种"
                f" · 抓取日志 {st['fetches']} 次",
                f"日期范围      {st['date_range'][0]} ~ {st['date_range'][1]}",
                "",
                "三个要点：",
                "  · 用 slug 做主键做 upsert —— 站点给的自然键，比自增 id 有意义得多",
                "  · 重复抓取 inserted=0 才叫幂等。爬虫一定会重跑，别让它污染数据",
                "  · 拒收列表要打出来。静默丢弃比不校验更危险：你会以为数据是完整的",
            ]
        )

        problems = []
        if first["inserted"] != len(rows):
            problems.append(f"① 首次应插入 {len(rows)}，实际 {first['inserted']}")
        if second["inserted"] != 0:
            problems.append(f"② 重复抓取不该新增，实际 inserted={second['inserted']}")
        if second["updated"] != len(rows):
            problems.append(f"② 重复抓取应全部走更新，实际 updated={second['updated']}")
        if third["inserted"] != 0:
            problems.append(f"③ 脏数据不该入库，实际 inserted={third['inserted']}")
        if len(third["rejected"]) != len(dirty):
            problems.append(f"③ 应拒收 {len(dirty)} 条，实际 {len(third['rejected'])}")

        if problems:
            return Outcome.fail(
                f"{len(problems)} 项不符",
                detail + "\n\n" + "\n".join(f"  ✗ {p}" for p in problems),
                self.level,
            )

        return Outcome.pass_(
            f"入库 {first['inserted']} 条 · 重跑新增 0 · 拒收脏数据 {len(third['rejected'])} 条",
            self.level,
            inserted=first["inserted"],
            idempotent=second["inserted"] == 0,
            rejected=len(third["rejected"]),
        )
