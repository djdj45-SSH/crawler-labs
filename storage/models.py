"""把抓到的东西落库。

第 9 章的两个问题：
  1. 存哪：CSV / JSON / SQLite / PostgreSQL 各自适合什么
  2. 怎么存得不后悔：幂等（重跑不产生重复）、可追溯（记下每次抓取）

这里用 SQLAlchemy 2.0 的声明式写法，**一个模型，四套连接串**：

    SQLite       sqlite:///data/dojo.db          ← 本地练习，零配置
    PostgreSQL   postgresql+psycopg://user:pw@host/db
    MySQL        mysql+pymysql://user:pw@host/db

换库只改连接串，代码一行不动 —— 这是 ORM 唯一真正值得付的代价。

为什么加 FetchLog 表
--------------------
只存文章的话，出了问题你没法回答"这批数据是什么时候、用什么身份抓的"。
抓取日志是排查和复现的起点，成本很低，但漏了就得重抓一遍才知道。
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "dojo.db"


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"

    # slug 做主键 —— 它是站点给的自然键，用它去重比自增 id 更有意义：
    # 同一个 slug 重复抓到就是同一篇文章，upsert 一次即可。
    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    published_at: Mapped[str] = mapped_column(String(20))
    tags: Mapped[str] = mapped_column(String(200), default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    # 正文的 sha1：用来发现"同一段正文出现在不同文章里"（蜜罐的第 2 个破绽）
    body_sha1: Mapped[str] = mapped_column(String(40), default="")

    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC)
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Article {self.slug} {self.title[:16]!r}>"


class FetchLog(Base):
    __tablename__ = "fetch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC)
    )
    url: Mapped[str] = mapped_column(String(500))
    status: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    identity: Mapped[str] = mapped_column(String(60), default="")   # bare / whitelist
    note: Mapped[str] = mapped_column(String(300), default="")


def make_engine(url: str | None = None):
    """建引擎。默认落本地 SQLite（data/ 目录已在 .gitignore 里）。"""
    url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_DB}"
    if url.startswith("sqlite:///"):
        DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def upsert(session: Session, rows: list[dict], *, skip_dupe_body: bool = True) -> dict:
    """幂等写入。

    返回 {"inserted": n, "updated": m, "rejected": [...]}。

    `skip_dupe_body` 是蜜罐防线：正文 sha1 与已有记录重复的，拒收并记录下来。
    真实场景里这条规则会误伤（两篇文章引用同一段长文是可能的），
    所以它默认开启但把拒收的条目**列出来**而不是静默丢弃 —— 让人可以复核。
    """
    import hashlib

    inserted = updated = 0
    rejected: list[str] = []

    seen_bodies = {
        h for (h,) in session.execute(select(Article.body_sha1)).all() if h
    }

    for raw in rows:
        body = raw.get("body", "")
        sha = hashlib.sha1(body.encode("utf-8")).hexdigest()

        obj = session.get(Article, raw["slug"])

        if obj is None:
            # 只有新条目才做正文重复检查。
            # 已存在的条目本来就是我们自己上次抓进来的数据 —— 对它们做去重，
            # 会把"重复抓取"整批误判成脏数据（第一版就是这么错的，
            # 表现为幂等测试里 updated=0：一条都没更新，全被当成重复拒收了）。
            if skip_dupe_body and sha in seen_bodies:
                rejected.append(f"{raw['slug']}（正文与已入库记录重复）")
                continue
            obj = Article(slug=raw["slug"])
            session.add(obj)
            inserted += 1
        else:
            updated += 1

        seen_bodies.add(sha)
        obj.title = raw.get("title", "")
        obj.published_at = raw.get("published_at", "")
        obj.tags = ",".join(raw.get("tags") or [])
        obj.word_count = int(raw.get("word_count") or 0)
        obj.summary = raw.get("summary", "")
        obj.body_sha1 = sha

    session.commit()
    return {"inserted": inserted, "updated": updated, "rejected": rejected}


def log_fetch(session: Session, *, url: str, status: int, rows: int, identity: str, note: str = "") -> None:
    session.add(FetchLog(url=url, status=status, rows=rows, identity=identity, note=note))
    session.commit()


def stats(engine) -> dict:
    with Session(engine) as s:
        articles = s.execute(select(Article)).scalars().all()
        logs = s.execute(select(FetchLog)).scalars().all()
    dates = sorted(a.published_at for a in articles if a.published_at)
    bodies = {a.body_sha1 for a in articles if a.body_sha1}
    return {
        "articles": len(articles),
        "distinct_bodies": len(bodies),
        "date_range": (dates[0], dates[-1]) if dates else (None, None),
        "fetches": len(logs),
    }
