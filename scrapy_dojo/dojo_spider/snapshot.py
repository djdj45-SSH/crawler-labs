"""离线模式：让 Scrapy 也对着快照跑。

为什么值得做
------------
`crawler-labs` 的手工实验已经能离线跑了（见 `../../fixtures/README.md`），
但第 8 章不行 —— 两个 spider 直接打靶场，靶场没起就跑不动。

把快照接进来之后，**同一份 `fixtures/snapshots/<tag>/` 同时服务两边**：

    python main.py --snapshot auto                 # 手工实验（lab01–11）
    scrapy crawl articles -s DOJO_SNAPSHOT=auto    # 框架

这件事本身就是这一章想要的那个结论的证据：**"离线快照"不是某个脚本的取巧，
它是"把响应当成数据"这个做法，和用什么框架无关。** 换到 Scrapy 里，
实现它只需要一个中间件 —— spider、管道、校验逻辑一行都不用改。

机制只有一句话
--------------
Scrapy 的下载器中间件允许在 `process_request` 里**直接返回一个响应**，
从而跳过真正的下载。快照就是这个响应的来源。

有一件事要特别注意：**UA 是本中间件的输入，也是判断"我是谁"的依据。**
Scrapy 的 `UserAgentMiddleware` 排在 500，所以本中间件排在 **540** ——
排在它前面就读不到 `settings.USER_AGENT`，所有请求都会被当成 `bare`，
而现象是"白名单身份也拿不到真数据"，很难往中间件顺序上想。

顺序的其余影响
--------------
`process_response` 是**全局**按优先级倒序跑的，与"谁产生的响应"无关。
所以排在 585 的 `DojoSignalsMiddleware` 照样能读到快照里冻结的 `X-Dojo-*` 响应头 ——
信号统计和"200 也可能是陷阱"的日志在离线模式下原样生效，
不用为离线模式再写一套观测逻辑。

反过来，`RetryMiddleware`（550）也照样会看到它。对快照来说重试毫无意义
（同一份冻结的字节，重试一百次还是一样），所以本中间件顺手把
`request.meta["dont_retry"]` 设上 —— 尤其是 L2 那一级的 429 快照，
`RetryMiddleware` 默认会重试它，白打三次。

用法
----
    -s DOJO_SNAPSHOT=l0      # 指定标签
    -s DOJO_SNAPSHOT=auto    # 用 spider 自己声明的 snapshot_tag
    （不传，或 =none）        # 走网络，和以前完全一样
"""

from __future__ import annotations

from urllib.parse import urlsplit

from scrapy.http import Headers, TextResponse

import snapshots
from dojo import BROWSER_UA, Contract, fetch_contract

#: 这个配置项是**唯一**的开关，spider 和中间件都读它，不各写一份。
SNAPSHOT_SETTING = "DOJO_SNAPSHOT"

#: 这些头描述的是传输过程，而快照里存的字节是**已经解压过**的。
#: 原样带进去会让 `HttpCompressionMiddleware` 去解压一段没压缩的内容。
#: 抓取侧现在就不记它们了，这里再挡一道是为了兼容改动之前抓的旧快照。
_TRANSPORT_HEADERS = frozenset(
    {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
)


class SnapshotUnavailable(RuntimeError):
    """离线模式下拿不到需要的东西 —— 直接炸，不要安静地返回空结果。"""


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------


def spec_of(spider) -> str:
    """读 `DOJO_SNAPSHOT`。返回值：''（走网络）/ 'auto' / 具体标签。"""
    settings = getattr(spider, "settings", None)
    raw = settings.get(SNAPSHOT_SETTING, "") if settings is not None else ""
    return str(raw or "").strip()


def tag_of(spider) -> str:
    """解析出这次要用的快照标签。没开离线就返回 ''。"""
    spec = spec_of(spider)
    if not spec or spec.lower() == "none":
        return ""
    if spec.lower() == "auto":
        # 'auto' 交给 spider 自己声明 —— 和 crawler-labs 里 Lab.snapshot_level 同一套约定。
        # 不声明就报错，而不是猜一个：猜错了会安静地拿错等级的数据。
        tag = str(getattr(spider, "snapshot_tag", "") or "")
        if not tag:
            raise SnapshotUnavailable(
                f"{type(spider).__name__} 没有声明 snapshot_tag，"
                f"无法解析 -s {SNAPSHOT_SETTING}=auto。\n"
                f'  要么在 spider 上写 snapshot_tag = "l0"，'
                f"要么直接指定：-s {SNAPSHOT_SETTING}=l0"
            )
        return tag
    return spec


def resolve(spider) -> snapshots.Snapshot | None:
    tag = tag_of(spider)
    if not tag:
        return None
    try:
        return snapshots.load(tag)
    except snapshots.SnapshotMiss as exc:
        raise SnapshotUnavailable(str(exc)) from exc


def load_contract(spider, base_url: str) -> Contract:
    """拿契约 —— 离线时来自快照的 manifest，在线时来自靶场。

    为什么要换来源：契约里带 `runtime.active_levels`，而两个 spider 都靠它判断
    "这一级生效了没有"。离线时若用本地缓存那份，等级就是**上一次联机时**的，
    快照和判断会对不上。
    """
    snap = resolve(spider)
    if snap is None:
        return fetch_contract(base_url)
    return Contract.from_json(snap.contract_json)


# ---------------------------------------------------------------------------
# 身份：从请求上实际带的 UA 反推
# ---------------------------------------------------------------------------


def identity_of(ua: str, whitelist_token: str) -> str:
    """和靶场、`dojo.py` 用**同一条规则**，不许各写一份。

    白名单必须最先判：它是"被接纳"这个状态，优先于任何形态判断。
    """
    low = ua.lower()
    if whitelist_token and whitelist_token.lower() in low:
        return "whitelist"
    if BROWSER_UA.lower() in low:
        return "browser"
    return "bare"


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------


class SnapshotMiddleware:
    """离线时用快照作答；在线时什么都不做。"""

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def __init__(self, crawler) -> None:
        self.crawler = crawler
        # 按标签缓存 (快照, 契约)。契约要跟着标签走 —— auto 模式下不同 spider
        # 用不同等级的快照，共用一个契约实例是隐式假设"它们的契约一样"。
        self._cache: dict[str, tuple[snapshots.Snapshot, Contract]] = {}

    @property
    def stats(self):
        return self.crawler.stats

    def _resolve(self, spider) -> tuple[snapshots.Snapshot, Contract] | None:
        tag = tag_of(spider)          # 缺标签 / 没声明都会在这里直接炸
        if not tag:
            return None
        if tag not in self._cache:
            snap = snapshots.load(tag)
            self._cache[tag] = (snap, Contract.from_json(snap.contract_json))
        return self._cache[tag]

    def process_request(self, request, spider):
        got = self._resolve(spider)
        if got is None:
            return None
        snap, contract = got

        # 身份判断要用**实际会发出去的那个 UA**：请求头上有就用它
        # （两个 spider 都显式带了），没有才落到 settings.USER_AGENT。
        raw_ua = request.headers.get("User-Agent")
        ua = (
            raw_ua.decode("latin-1")
            if raw_ua
            else str(spider.settings.get("USER_AGENT") or "")
        )
        identity = identity_of(ua, contract.whitelist_token)

        path = urlsplit(request.url).path or "/"
        if not snap.has(path, identity):
            # 不造假响应、也不安静地跳过：冻下来的字节里没有这一页，
            # 就说清楚缺什么、怎么补。返回一个编出来的 404 会让人以为"站点说没有"。
            raise SnapshotUnavailable(
                f"快照 {snap.tag} 里没有 {path}（身份 {identity}）。\n"
                f"  这一份在该路径下有的身份：{snap.available(path)}\n"
                f"  重新抓：python snapshot.py --level {snap.tag} --force"
                f"（一次抓全：python snapshot.py --all --force）"
            )

        page = snap.get(path, identity)

        # 快照的答案是冻结的，重试只会拿到同一份字节 —— 关掉重试。
        request.meta["dont_retry"] = True

        headers = Headers(
            {
                k.encode("latin-1"): [str(v).encode("latin-1")]
                for k, v in page.headers.items()
                if k not in _TRANSPORT_HEADERS
            }
        )

        self.stats.inc_value("dojo/snapshot/served")
        self.stats.set_value("dojo/snapshot/tag", snap.tag)

        return TextResponse(
            url=request.url,
            status=page.status_code,
            headers=headers,
            body=page.content,
            # 和 requests 的规则一致：encoding 优先，没有就用 apparent。
            # 不传（None）的话 Scrapy 会自己猜一个 —— 大多数时候结果一样，
            # 但"大多数时候"在这里不够：解码差一个字符，正文就悄悄变了。
            encoding=page.encoding or page.apparent_encoding or None,
            request=request,
        )
