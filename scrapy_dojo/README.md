# scrapy_dojo —— 第 8 章：Scrapy 工程化

前 11 个实验都是"一个脚本解决一个问题"。这一章换成框架，回答两个新问题：

1. **工程化之后，前面那些结论还成立吗？** —— 成立。契约驱动、幂等写入、
   数据校验，一样是这三件事，只是换了执行方式。
2. **框架帮你做了什么、又瞒着你什么？** —— 这是这一章真正的重点。
   Scrapy 的重试逻辑**不认识 `Retry-After`**，AutoThrottle 会**覆盖**你手工设的
   延迟。不查源码就不知道，而它们都发生在你写不到的地方。

---

## 怎么跑

靶场先起在另一个终端：

```bash
cd ../.. && cd crawler-dojo
python -m server.main --level all
```

然后：

```bash
cd scrapy_dojo
scrapy crawl articles          # 抓真数据
scrapy crawl honeypot          # 故意接假数据（需要 L3，见下）
```

`articles` 跑两遍可以看到幂等：

```
第一遍  入库 新增 6 · 更新 0
第二遍  入库 新增 0 · 更新 6
```

---

## 也可以不起靶场：离线模式

跟手工实验（`lab01–11`）用的是**同一份快照**：

```bash
cd ..                      # 回到 crawler-labs 根目录
python snapshot.py --all   # 六个等级各抓一份（约 1 分钟）

cd scrapy_dojo
scrapy crawl articles -s DOJO_SNAPSHOT=auto
scrapy crawl honeypot -s DOJO_SNAPSHOT=auto
```

`auto` 表示"用 spider 自己声明的 `snapshot_tag`"：`articles` → `l0`，
`honeypot` → `l3`。也可以写死一个标签（`-s DOJO_SNAPSHOT=l3`），
不传就是走网络，和以前完全一样。

实测（确认没有服务在跑）：

```
契约来源=snapshot:l0，生效等级=L0，端点=/api/articles
  通过校验     6 条
  入库         新增 6 · 更新 0        ← 第二遍 新增 0 · 更新 6

honeypot: 拿到 8 条记录 · 校验拦下 8 条 · 入库 新增 0
```

### 为什么这件事本身就是一个结论

**"离线快照"不是某个脚本的取巧，它是"把响应当成数据"这个做法 —— 和用什么框架无关。**

换到 Scrapy 里，实现它只需要**一个中间件**：在 `process_request` 里直接返回一个
冻结的响应，跳过真正的下载。spider、items、管道、校验逻辑**一行都不用改**，
9 个管道的输出和联机时逐字相同。

而且它证明了这个设计是**正交**的：`DojoSignalsMiddleware`（排在 585）在离线模式下
照样读到快照里冻结的 `X-Dojo-*` 响应头，于是那句
「数据来自 L3 的 honeypot 响应，不是真实内容」的 WARNING 原样出现。
观测逻辑不用为离线模式写第二套 —— 和 `main.py --snapshot` 那边是同一条道理。

### 三个坑（都写在 `dojo_spider/snapshot.py` 里了）

**① 中间件队列位置是 540，不是随便挑的。**
身份靠 UA 反推，而 `UserAgentMiddleware` 排在 **500** —— 排在它前面只能读到空 UA，
于是**所有请求都被当成裸身份**。现象是"白名单也拿不到真数据"，而你不会想到
去查中间件顺序。默认队列（打印 `DOWNLOADER_MIDDLEWARES_BASE` 得到）：
`offsite 50 · robotstxt 100 · httpauth 300 · timeout 350 · defaultheaders 400 ·
useragent 500 · retry 550 · metarefresh 580 · compression 590 · redirect 600`。

**② `RetryMiddleware` 照样会看到快照响应。**
`process_response` 是全局倒序跑的，与"谁产生的响应"无关。所以 L2 那一级的 429 快照
会被重试三次（拿到同一份字节）。修法是 `request.meta["dont_retry"] = True` ——
冻结的答案重试一百次也一样，这一条是**结论**，不是优化。

**③ 快照里不能保留 `Content-Encoding`。**
存下来的字节是 `requests` 已经解压过的，把 `Content-Encoding: gzip` 一起冻进去，
`HttpCompressionMiddleware` 会去 gunzip 一段纯文本，报一个看起来和"快照坏了"
毫不相干的解码错误。抓取侧现在不记这些头了（顺手把 `Content-Length` 按实际
字节数重算），中间件里再挡一道，兼容改动之前抓的旧快照。

---

## 两个 spider 的差别

| | `articles` | `honeypot` |
|---|---|---|
| 身份 | 白名单（`DojoBot/1.0`） | **裸 User-Agent**（故意） |
| 数据 | 真的 | 假的（结构完全正确） |
| 结果 | 6 条入库 | **0 条入库，全被校验拦下** |
| 需要等级 | 任意 | L3 |

`honeypot` 的存在理由是：**只跑 `articles` 你会觉得校验管道多此一举。**
跑一遍它，就知道校验拦的是什么 —— 状态码 200、字段齐全、格式全对，
然后 ValidationPipeline 把它们一条条挡在库外，并逐条说出原因。

```bash
# 靶场单独开 L3，否则裸 UA 会在 L1 就被挡下，拿不到蜜罐
cd ../../crawler-dojo && python -m server.main --level L3
cd ../crawler-labs/scrapy_dojo && scrapy crawl honeypot
```

---

## settings 里每个决定对应什么

配置不是模板，每一行都是针对这个项目的一个选择。几处值得单独说：

**`USER_AGENT` 写死成 `DojoBot/1.0 (+https://…)`**
这是全书的核心约定，不是配置项。伪装能过第一道规则，但把关系变成对抗。

**`ROBOTSTXT_OBEY = False`**
靶场是本地虚构站点，没有 robots.txt。**真实站点必须保持默认的 `True`** ——
这一行显式写出来，是为了让你注意到"这里故意改过"。

**`AUTOTHROTTLE_ENABLED = False`**
AutoThrottle 每次响应后都会重写 `slot.delay`，而我们的 Retry-After 处理
（`middlewares.py`）也要写它 —— 两者互相覆盖，结果是"按 Retry-After 退让"
时而生效时而不生效。选了后者，因为 AutoThrottle 按**响应时间**调延迟，
**它不认识 429**，被限流时只会觉得"响应挺快"然后继续催。

想两者兼得：继承 AutoThrottleMiddleware，让它在 429 时不要覆盖。留给读者。

**`RETRY_HTTP_CODES` 显式列出 429**
实测 Scrapy 2.19 的默认值**已经含 429**，所以这行不是必需的 ——
写出来只是为了让"我们关心哪些码"可见（默认值会随版本变）。

**`ITEM_PIPELINES` 的顺序**
`100 校验 → 200 去重 → 300 落库 → 900 报告`。
**校验必须在落库之前**：脏数据一旦进库，你就得写清理脚本，
而清理脚本也需要校验，等于把同一个问题做两遍。

---

## 目录结构

```
scrapy_dojo/
├── scrapy.cfg
├── README.md
└── dojo_spider/
    ├── __init__.py        把父目录补进 sys.path（复用 dojo.py / storage/）
    ├── settings.py        每行都是针对本项目的选择
    ├── items.py           ArticleItem（含 source 字段，记来源）
    ├── middlewares.py     契约信号 → stats；兑现 Retry-After
    ├── snapshot.py        离线模式：一个中间件让整个工程能对着快照跑
    ├── pipelines.py       校验 / 去重 / 落库 / 报告
    └── spiders/
        ├── articles.py    真数据
        └── honeypot.py    假数据
```

**为什么复用父目录的 `dojo.py`、`snapshots.py` 和 `storage/models.py`，而不是各写一份：**
"契约驱动"和"幂等写入"是这个项目的两条主结论。另写一套会让读者以为
那是两回事 —— 它们本来是一回事，只是换了个执行框架。
离线快照同理：手工实验和 Scrapy 读的是**同一份** `fixtures/snapshots/`，
连"身份怎么判"都共用 `dojo.py` 里那条规则。

---

## 五个"跑了才知道"的框架行为

这一章最有价值的部分。下面每一条都是对着 Scrapy 2.19 实跑或查源码得到的，
网上教程里写的多半是旧版本 —— 照着抄会踩坑，而且踩的时候**不报错**。

| 结论 | 怎么发现的 | 后果 |
|---|---|---|
| **`start_requests()` 已经不被调用** | 实跑：Spider opened 后立刻 Closing，0 个请求、无报错。查 `scrapy/spidermiddlewares/start.py` 源码，`start_requests` 零命中 | 入口要用 `async def start()`（2.13 起） |
| **`RetryMiddleware` 不认识 `Retry-After`** | grep `scrapy/downloadermiddlewares/retry.py`，零命中 | 三次重试会在同一个限流窗口里撞完 → 要自己兑现 |
| **管道 `close_spider` 是倒序调用** | 实跑：报告打印"入库 新增 0"，但 stats 里 `inserted=6` | 报告不能写成管道，要挂 `spider_closed` 信号 |
| **默认 `RETRY_HTTP_CODES` 已含 429** | `default_settings.RETRY_HTTP_CODES` 打印实际值 | 不需要手动加（但显式写出来便于升级时看 diff） |
| **`RANDOMIZE_DOWNLOAD_DELAY` 已弃用** | 框架自己的 `ScrapyDeprecationWarning` | 改用 `DOWNLOAD_DELAY_JITTER` |

### 附赠一个自己挖的坑

`honeypot` spider 想用"未声明身份的裸 UA"，但 `settings.USER_AGENT` 是全局的
白名单身份（`DojoBot/1.0`）—— 不覆盖的话它拿到的是**真数据**，
信号头是空的，演示完全失效。日志里只有一句
`实际 signal='' status=200`，看起来"一切正常，只是没有你要看的东西"。

修法是显式在请求头里覆盖。但值得记住的是**这类错误的形态**：
不是报错，而是"静悄悄地没发生"。

### 顺带一提：`spider` 参数正在被淘汰

Scrapy 2.19 对每个接收 `spider` 参数的管道/中间件方法都会给弃用警告，并明说
以后不再传。所以本项目统一用 `from_crawler` 存 crawler、走 `crawler.spider` ——
现在两种都能跑，但以后的版本只认这一种。

---

## 三条核心结论在 Scrapy 里依然成立

换了框架，前面 11 个实验的结论一条都没变，只是换了执行方式：

| 结论 | 在 Scrapy 里落在哪 |
|---|---|
| **契约驱动** | spider 的 `start()` 拉 `/__dojo/contract`（离线时从快照的 manifest 拿），端点和身份都从契约取 |
| **幂等写入** | `SqlitePipeline` 复用实验 11 的 `upsert`，实测第二次跑 `新增 0 · 更新 6` |
| **数据校验** | `ValidationPipeline`（时间范围 / 字段自洽 / 必填），蜜罐 8 条全被拦下 |
| **可复现** | 一个中间件接上同一份快照，9 个管道输出逐字不变（见上面的「离线模式」） |

---

## 实测输出

```
# articles 第一次
  通过校验     6 条
  入库         新增 6 · 更新 0

# articles 第二次（幂等）
  通过校验     6 条
  入库         新增 0 · 更新 6

# honeypot（靶场开 L3）
WARNING 拿到 8 条记录。状态码 200，字段齐全 —— 但它们是假的。
WARNING Dropped: dojo-honeypot-01: 未来日期 2026-10-03
WARNING Dropped: dojo-honeypot-02: 未来日期 2026-10-04
...（8 条全部被拦下，一条都没进库）
```

