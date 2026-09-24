# 附录

主线是攻防回合，附录是速查。两者的分工很清楚：

- **主线**教你"遇到 429 该怎么办"
- **附录**告诉你"requests / httpx / aiohttp 的 API 长什么样"

只写主线，读者查 API 要翻文档；只写附录，就成了又一个库手册。
所以附录不进章节编号，但都在。

---

## 附录 A · 请求库对比

| | `requests` | `httpx` | `aiohttp` |
|---|---|---|---|
| 同步 | ✅ | ✅ | ❌ |
| 异步 | ❌ | ✅（同一份代码） | ✅ |
| HTTP/2 | ❌ | ✅ | ❌ |
| 默认 UA | `python-requests/x.y.z` | `python-httpx/x.y.z` | `Python/3.x aiohttp/x.y` |
| 连接池复用 | `Session` | `Client` | `ClientSession` |
| 超时 | `timeout=`（**必填，没有默认超时**） | `timeout=` | `ClientTimeout` |
| 重试 | 无（配 `urllib3.Retry`） | 无 | 无 |
| 代理 | `proxies=` | `proxies=` / `trust_env` | `trust_env` |
| 学习成本 | 最低 | 低 | 中 |

### 该怎么选（这是附录唯一真正需要给结论的地方）

- **只抓几个页面** → `requests`。简单直接，社区示例最多。
- **要写异步、或者以后可能改异步** → `httpx`。**同一份代码既有 `.get()` 也有 `.aget()`**，
  以后要提速不用重写。这是它比 aiohttp 更值得先学的理由。
- **已经在 asyncio 里、或者要压榨并发** → `aiohttp`。它更老、生态更成熟，
  但也更啰嗦（一切都要在 `async with session` 里）。

**本项目主线用 `requests`**，因为零基础读者第一次写爬虫时，
不该先学 `async with`。第 5 章的退避重试也是手写的，理由一样：
先看清机制，再用库。

### 两个容易踩的点

**`requests` 没有默认超时。** 不写 `timeout=` 的话，一个卡住的连接会让程序永久挂起。
这是新手脚本在生产上最常见的"莫名其妙不结束"。

```python
requests.get(url, timeout=5)                       # 5 秒总超时
requests.get(url, timeout=(3.05, 10))              # (连接, 读取) 分别设
```

**`trust_env` 与代理。** 环境变量里有 `http_proxy` 时，`requests` 会把它用在
**所有**请求上，包括 `127.0.0.1`。于是你拿到的是代理的错误响应，
而它看起来像"目标服务坏了"。本项目就踩过（见 `dojo.py` 顶部），
解法是把 loopback 补进 `no_proxy`，或者用 `Session(trust_env=False)`。

---

## 附录 B · 解析库对比

| | `BeautifulSoup` | `lxml` | `parsel` | `re` |
|---|---|---|---|---|
| 选择器 | CSS + 有限 XPath | XPath + CSS | CSS + XPath（Scrapy 同款） | 无 |
| 速度 | 慢（纯 Python 时更慢） | 最快 | 快（底层就是 lxml） | 最快（但只对文本） |
| 容错 | 最好 | 一般（按 HTML 规范修正） | 一般 | 不适用 |
| 学习成本 | 最低 | 中（XPath 要学） | 低 | — |
| 适合 | 探索、脏 HTML | 大批量、结构稳定 | Scrapy 项目 | 从脚本/JSON 里抠零散字段 |

### 怎么选

- **入门/探路** → `BeautifulSoup(soup, "lxml")`。容错好，选择器写错时更容易发现。
- **要快、结构稳定** → 直接用 `lxml` 的 XPath。
- **进了 Scrapy** → `parsel`（它就是 Scrapy 内置的响应对象）。
- **都不合适** → `re`。但注意：**用正则解析 HTML 是最后手段**，
  它对 DOM 的任何结构调整都敏感，而 XPath/CSS 至少还能靠语义定位。

### 一条比库选择更重要的纪律

不管你用哪个库，**先断言行数，再取字段**：

```python
soup = BeautifulSoup(html, "lxml")
items = soup.select("ul li")

assert items, "解析到 0 行 —— 选择器过时了，或者数据根本不在 HTML 里"

for li in items:
    title_el = li.select_one("a")
    if title_el is None:            # 每个字段都判空
        continue
    ...
```

不做这一步的后果不是报错，而是**静默地拿到一堆空字符串** ——
错误会一路传到数据库里，等到报表不对才发现。

第 3 章（实验 03）和第 7 章（L4 空壳，行数会变成 0）分别在两个方向上验证了这条纪律。

---

## 附录 C · 存储方案对比

| | CSV | JSON/JSONL | SQLite | PostgreSQL |
|---|---|---|---|---|
| 零配置 | ✅ | ✅ | ✅（标准库自带） | ❌ 要起服务 |
| 能增量更新 | ❌ | ❌ | ✅ | ✅ |
| 能查询 | ❌ | ❌ | ✅ | ✅ |
| 并发写 | ❌ | ❌ | 弱 | ✅ |
| 适合 | 一次性导出 | 传给下游程序 | **本地练习、单机工具** | 多人/线上 |

**本项目用 SQLite**：靶场是本地的，读者 clone 下来就该能跑，
不该为了一个练习去装数据库。`storage/models.py` 用的是 SQLAlchemy，
换 PostgreSQL / MySQL 只改连接串，代码一行不动（见 `.env.example`）。

### 比选型更重要的两件事

**① 幂等。** 爬虫一定会重跑。用站点给的自然键（这里是 `slug`）做主键做 upsert，
而不是自增 id + 追加。实测：第二次爬取 `新增 0 · 更新 6`。

**② 拒收要留痕。** 校验拦下的每一条都要能说出来"为什么"。
静默丢弃比不校验更危险 —— 你会以为数据是完整的。
本项目的做法是记进 stats 并打进报告（见 `pipelines.py` 的 `ValidationPipeline`）。
