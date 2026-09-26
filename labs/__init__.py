"""实验清单。

顺序就是章节顺序 —— 前面的结论是后面的前提，别打乱跑。

每个实验声明它需要靶场开启哪一级（`needs`）。靶场没开时实验会**跳过**并说明
怎么开，而不是假装通过 —— 一个会在错误前提下报"成功"的实验，比没有实验更糟。

模块名用 labNN_ 前缀而不是直接 NN_：前者是合法的 Python 模块名，能直接 import。
后者要靠 importlib 动态加载，为了一点命名美学引入一层魔法不值得。
"""

from __future__ import annotations

from .base import FALLBACK_LEVEL, Lab, LabContext, LabSkip, Outcome

from .lab01_http_basics import HttpBasics
from .lab02_requests_l0 import RequestsL0
from .lab03_parse_bs4 import ParseBs4
from .lab04_ua_whitelist import UaWhitelist
from .lab05_backoff_retry import BackoffRetry
from .lab06_honeypot_check import HoneypotCheck
from .lab07_js_payload import JsPayload
from .lab08_playwright_render import PlaywrightRender
from .lab09_blog_capstone import BlogCapstone
from .lab10_signature import Signature
from .lab11_store_sqlite import StoreSqlite

# 按章节顺序（lab10 时效签名在第 11 章 —— 守方线，不是攻线）
LAB_CLASSES: list[type[Lab]] = [
    HttpBasics,           # 1
    RequestsL0,           # 2
    ParseBs4,             # 3
    UaWhitelist,          # 4
    BackoffRetry,         # 5
    HoneypotCheck,        # 6
    JsPayload,            # 7
    PlaywrightRender,     # 7（对照）
    StoreSqlite,          # 9
    BlogCapstone,         # 10
    Signature,            # 11（守方：写防护）
]


def all_labs() -> list[Lab]:
    return [cls() for cls in LAB_CLASSES]


def find_lab(token: str) -> Lab | None:
    """按编号（可省前导零）或类名找实验。"""
    token = token.strip().lstrip("0") or "0"
    for lab in all_labs():
        if lab.id.lstrip("0") == token or lab.id == token:
            return lab
        if lab.__class__.__name__.lower() == token.lower():
            return lab
    return None


__all__ = [
    "FALLBACK_LEVEL",
    "LAB_CLASSES",
    "Lab",
    "LabContext",
    "LabSkip",
    "Outcome",
    "all_labs",
    "find_lab",
]
