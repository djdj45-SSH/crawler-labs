# book —— 课文

这是全书正文的目录。每章一个文件，章节号即文件名（`ch01.md` = 第 1 章）。
本目录同时是 mkdocs 站点的源（`docs_dir`），`index.md` 是站点导读页，
`interactive/` 是零安装浏览器试玩页（设计背景见 `../docs/teaching-paths.md`）。

| 文件 | 章 | 状态 |
|---|---|---|
| [`index.md`](index.md) | 站点导读（三路径动线） | ✅ |
| [`ch01.md`](ch01.md) | 第 1 章 · 你的第一次请求 | ✅ 样章 |
| [`ch02.md`](ch02.md) | 第 2 章 · 裸爬：拿到第一批数据 | ✅ 样章 |
| [`ch03.md`](ch03.md) | 第 3 章 · 解析：网页不是 JSON | ✅ 新 |
| [`interactive/`](interactive/ch01.html) | 浏览器试玩页（Pyodide，第 1–2 章） | ✅ |
| ch04–ch12 | 其余九章 | 待写（大纲见 [`../docs/book-plan.md`](../docs/book-plan.md)） |

写作规则（六环节 + 函数卡模板）以 `docs/book-plan.md` 为准，动笔前先读它。

配套实验的跑法：每章末尾的过关检查 `python main.py --chapter N`
（用法见仓库根目录 README）。
