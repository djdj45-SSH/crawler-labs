"""Item 定义。

Scrapy 的 Item 比 dict 好在两点，都值得用：
  · 字段拼错会**立刻报错**（KeyError），而不是安静地少一个字段
  · 可以在 pipelines 之前就用 Field() 声明"这个字段是必需的"

字段与靶场 `/api/articles` 返回的结构一一对应 —— 这样同一个 item
既能由 API spider 填，也能由 HTML spider 填，下游 pipeline 不用区分来源。
"""

import scrapy


class ArticleItem(scrapy.Item):
    slug = scrapy.Field()
    title = scrapy.Field()
    published_at = scrapy.Field()
    tags = scrapy.Field()
    word_count = scrapy.Field()
    summary = scrapy.Field()
    body = scrapy.Field()

    # 这条记录是怎么来的。三个取值：
    #   api      —— 从 /api/articles 拿的
    #   html     —— 从列表页 + 详情页解析出来的
    #   honeypot —— 从蜜罐拿的（故意用来演示"假数据长什么样"）
    #
    # 记下来源不是为了好看。排查数据问题时第一个要回答的就是
    # "这条记录是哪个入口进来的" —— 而这个信息一旦不记，就永远补不回来。
    source = scrapy.Field()
