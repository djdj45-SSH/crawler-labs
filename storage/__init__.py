"""数据落地。

模型定义与读写逻辑都在 models.py —— 这里只是一个包入口。
单独一层是因为"存哪"和"怎么存得不后悔"是两个问题，
后者（幂等、可追溯、拒收留痕）比前者重要得多，值得在 README 里单独讲。
"""

from .models import Article, FetchLog, init_db, log_fetch, make_engine, stats, upsert

__all__ = ["Article", "FetchLog", "init_db", "log_fetch", "make_engine", "stats", "upsert"]
