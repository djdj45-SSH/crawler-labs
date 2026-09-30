# book —— 课文

这是全书正文的目录。每章一个文件，章节号即文件名（`ch01.md` = 第 1 章）。
本目录同时是 mkdocs 站点的源（`docs_dir`），`index.md` 是站点导读页，
`interactive/` 是零安装浏览器试玩页（设计背景见 `../docs/teaching-paths.md`）。

| 文件 | 章 | 状态 |
|---|---|---|
| [`index.md`](index.md) | 站点导读（三路径动线） | ✅ |
| [`ch01.md`](ch01.md) | 第 1 章 · 你的第一次请求 | ✅ 样章 |
| [`ch02.md`](ch02.md) | 第 2 章 · 裸爬：拿到第一批数据 | ✅ 样章 |
| [`ch03.md`](ch03.md) | 第 3 章 · 解析：网页不是 JSON | ✅ |
| [`ch04.md`](ch04.md) | 第 4 章 · 403：你被认出来了 | ✅ |
| [`ch05.md`](ch05.md) | 第 5 章 · 429 与 Retry-After | ✅ |
| [`ch06.md`](ch06.md) | 第 6 章 · 200 也可能是假的：蜜罐 | ✅ |
| [`ch07.md`](ch07.md) | 第 7 章 · HTML 里没有数据 | ✅ |
| [`ch08.md`](ch08.md) | 第 8 章 · Scrapy：从脚本到工程 | ✅ |
| [`ch09.md`](ch09.md) | 第 9 章 · 落地：数据要能重复入库 | ✅ |
| [`ch10.md`](ch10.md) | 第 10 章 · 真实战场：博客 | ✅ |
| [`ch11.md`](ch11.md) | 第 11 章 · 写防护：坐到对面去 | ✅ |
| [`ch12.md`](ch12.md) | 第 12 章 · 合规边界与综合实战 | ✅（全书完） |
| [`interactive/`](interactive/ch01.html) | 浏览器试玩页（Pyodide，第 1–2 章） | ✅ |

写作规则（六环节 + 函数卡模板）以 `docs/book-plan.md` 为准，动笔前先读它。

配套实验的跑法：每章末尾的过关检查 `python main.py --chapter N`
（用法见仓库根目录 README）。
