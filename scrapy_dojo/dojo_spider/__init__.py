"""让子项目能复用父仓库的模块。

`scrapy_dojo/` 是 `crawler-labs` 的子项目，但 Scrapy 只把项目根（`scrapy_dojo/`）
放进 sys.path。而我们要复用的是父目录里的两样东西：

    dojo.py          契约客户端（和实验 01–11 用的是同一份）
    storage/models.py  幂等 upsert（和实验 11 用的是同一份）

所以这里把父目录补进 sys.path。

为什么要复用而不是复制一份：
    "契约驱动"和"幂等写入"是这个项目的两条主结论。如果 Scrapy 章节里
    另写一套，读者会以为那是两回事 —— 而它们本来是一回事，
    只是换了个执行框架。
"""

from __future__ import annotations

import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
