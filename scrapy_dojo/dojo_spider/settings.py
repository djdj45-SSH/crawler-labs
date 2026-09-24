"""Scrapy 配置。

这里每一行都对应一个"礼貌爬虫"的具体决定，而不是照抄模板。
"""

BOT_NAME = "dojo_spider"

SPIDER_MODULES = ["dojo_spider.spiders"]
NEWSPIDER_MODULE = "dojo_spider.spiders"

# ---------------------------------------------------------------------------
# 身份：从第一个请求就声明自己是谁
#
# 这不是"配置项"，是这一章的核心。靶场的白名单按 User-Agent 里的 dojobot 放行，
# 真实站点则通过 robots.txt 和联系邮箱形成同样的约定。
# 伪装成浏览器能过第一道规则，但那是把关系变成对抗。
# ---------------------------------------------------------------------------
USER_AGENT = "DojoBot/1.0 (+https://blog.djdj45.top/about.html)"

# ---------------------------------------------------------------------------
# robots.txt
#
# 靶场是本地虚构站点，没有 robots.txt，所以这里关掉。
# **真实站点必须开启**（Scrapy 默认就是 True）—— 这是合规底线，不是可选项。
# 这一行之所以显式写出来，是为了让读者注意到：默认值是对的，是这里故意改的。
# ---------------------------------------------------------------------------
ROBOTSTXT_OBEY = False

# ---------------------------------------------------------------------------
# 限速
#
# 固定 DOWNLOAD_DELAY 是"我觉得该多快"；AutoThrottle 是"看服务端反应再说"。
#
# 这里**刻意关掉 AutoThrottle**，原因很具体：AutoThrottle 每次响应后都会
# 重写 `slot.delay`，而我们的 Retry-After 处理（middlewares.py）也要写它 ——
# 两者会互相覆盖，结果是"按 Retry-After 退让"这件事时而生效时而不生效，
# 排查起来极其难受。
#
# 为什么选后者：AutoThrottle 按**响应时间**调延迟，它**不认识 429**。
# 被限流时它只会觉得"响应挺快"，然后继续催。而 Retry-After 是服务端
# 直接给出的答案，可信度更高。
#
# 想两者兼得：继承 AutoThrottleMiddleware，让它在响应码为 429 时不要覆盖。
# 这是个不错的练习，留给读者。
# ---------------------------------------------------------------------------
DOWNLOAD_DELAY = 0.3
# Scrapy 2.19 起 RANDOMIZE_DOWNLOAD_DELAY 已弃用，改用 DOWNLOAD_DELAY_JITTER
# （值表示抖动幅度，0.5 = ±50%）。这个警告是实跑时框架自己报的，照它改。
DOWNLOAD_DELAY_JITTER = 0.5

AUTOTHROTTLE_ENABLED = False
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False

# ---------------------------------------------------------------------------
# 重试
#
# 实测（Scrapy 2.19）：默认的 RETRY_HTTP_CODES **已经包含 429**：
#     [500, 502, 503, 504, 522, 524, 408, 429]
# 所以下面这一行列出来**不是必需的**，而是把"我们关心哪些状态码"写清楚。
# 显式声明的价值在于：默认值会随版本变（早期版本不含 429），
# 写出来之后，升级时你能在 diff 里看见差异，而不是靠运气。
#
# 真正必需的是另一件事：**Scrapy 完全不认识 Retry-After**。
# 查过 2.19 的 `scrapy/downloadermiddlewares/retry.py`，源码里一次都没提到
# 这个响应头 —— 它会重试，但不会等。三次重试会在同一个限流窗口里全部撞完，
# 然后爬取失败。所以要自己兑现，见 middlewares.py。
# ---------------------------------------------------------------------------
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]

# ---------------------------------------------------------------------------
# 并发与礼貌
#
# 单站点并发压到 8（默认 16）—— 本地靶场扛得住，但习惯要从练习时养成。
# ---------------------------------------------------------------------------
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

# 契约信号头要能读到，别被中间件顺序吃掉
DOWNLOADER_MIDDLEWARES = {
    # 我们的中间件排在默认 RetryMiddleware（550）之后。
    # Scrapy 的 process_response 按数字**从大到小**调用，所以 585 先看到响应 ——
    # 这样我们才能在重试发生之前先把 Retry-After 的延迟设好。
    "dojo_spider.middlewares.DojoSignalsMiddleware": 585,
}

ITEM_PIPELINES = {
    # 顺序即职责顺序，数字小的先跑。设计成"任一环不合格就 drop"，
    # 所以校验必须在落库之前、去重必须在落库之前。
    "dojo_spider.pipelines.ValidationPipeline": 100,
    "dojo_spider.pipelines.DupeBodyPipeline": 200,
    "dojo_spider.pipelines.SqlitePipeline": 300,
    "dojo_spider.pipelines.ReportPipeline": 900,
}

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

LOG_LEVEL = "INFO"
