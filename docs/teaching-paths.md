# 教学路径设计：三条线 × 12 章（teaching-paths）

> 2026-09-28 与用户对齐定稿。配套讨论背景：把教学端用 GitHub Pages 发布，
> 降低读者门槛。本文是站点的教学逻辑总纲——**课文怎么分层、读者从哪条路径进来、
> 每一章用哪个对手**。工程实现（mkdocs / Actions）不在本文，见仓库根 `mkdocs.yml`
> 与 `.github/workflows/docs.yml`。

---

## 1. 三条路径的定义

| 路径 | 载体 | 覆盖范围 | 读者需要 | 定位 |
|---|---|---|---|---|
| **A 主线** | GitHub Pages 电子书（mkdocs-material） | 全部 12 章 | Python + 本地靶场（第 3 章起） | 全书的正文，唯一事实来源 |
| **C 试玩** | Pages 上的 Pyodide 交互页 | **只有第 1–2 章** | 什么都不装，打开网页 | 引流钩子：零安装体验 → 愿意装环境 |
| **B 入场** | 本地部署 crawler-dojo | 第 3 章起所有"真请求"章节 | clone 两仓 + `pip install` | 练习场，判定与通过矩阵的来源 |

读者动线：**C（零安装，先玩起来）→ 第 3 章门槛 → B（本地部署靶场）→ A（走完全书）**。

## 2. C 路径的技术边界（为什么只有前两章，且怎么落）

### 2.1 三条硬约束（实测结论，2026-09-28）

| # | 约束 | 后果 |
|---|---|---|
| 1 | 浏览器沙箱禁止网页调用本地 `python.exe` | "网页调本地 Python"这条路本身不存在 |
| 2 | 浏览器 `fetch` 无法读取**没开 CORS 头**的响应 | toscrape / scrapethissite 等公开练习站**全部够不着**（它们只服务本地 Python） |
| 3 | `User-Agent` 是浏览器的禁止篡改头 | 第 4 章（UA 伪装 / L1）在浏览器版**无法教学**；Scrapy 依赖 socket，第 8 章不可能 |

### 2.2 落地方式（每章一个来源）

| 章 | 浏览器版数据来源 | 说明 |
|---|---|---|
| 第 1 章 | **httpbin.org 真实请求**（CORS 全开） | 用 pyodide-http 给 requests 打补丁；UA 回显会显示浏览器 UA 且改不动——这正好是"第 4 章为什么要本地环境"的天然钩子 |
| 第 2 章 | **靶场 L0 内容层快照**（`dojo-articles.json`，同源 fetch） | 页面内模拟 `requests.get` 垫片（注册进 `sys.modules`），课文代码可以原样跑；6 条数据与课文输出逐字一致 |

原则：**浏览器版永远明确标注"沙箱版 ≠ 真实环境"**，每页固定放一条差异说明横幅，
并引导"第 3 章起请部署本地靶场"。

### 2.3 快照入库的例外说明

`fixtures/snapshots/` 因防过期被 gitignore。但 C 路径页面需要一份**冻结数据**，
因此把 L0 的 `list_json__whitelist.json` 单独复制为 `book/interactive/dojo-articles.json`
入库。理由：L0 内容层（whitelist 身份）不随等级变化（见快照 manifest 的 note），
教学内容只依赖"6 条文章的字段与数值"，过期风险为零；真过期时重建快照、同步这一个文件即可。

## 3. 三路径 × 12 章编排总表

| 章 | 主题 | C 试玩 | B 本地靶场 | 公开站点（副线） | 博客（真实战场） |
|---|---|---|---|---|---|
| 1 | 你的第一次请求 | ✅ httpbin | — | httpbin.org | — |
| 2 | 裸爬：第一批数据 | ✅ L0 快照 | — | — | — |
| 3 | 解析：网页不是 JSON | — | ✅ 入场（部署 dojo） | books.toscrape.com / scrapethissite.com | — |
| 4 | 身份：UA + 限速 | ❌ | ✅ L1+L2 | — | — |
| 5 | 蜜罐识别与校验 | ❌ | ✅ L3 | — | — |
| 6 | 数据在 JS 里 | ❌ | ✅ js_payload | quotes.toscrape.com/js、/scroll | — |
| 7 | 浏览器渲染 | ❌ | ✅ L4 | quotes.toscrape.com/js-delayed | — |
| 8 | Scrapy 工程化 | ❌ | ✅ L5 | quotes.toscrape.com/login（CSRF）、web-scraping.dev | — |
| 9 | 数据落地 | ❌ | ✅ 本地 | httpbin.org/status/429、web-scraping.dev（限速） | — |
| 10 | 真实战场 | ❌ | — | — | ✅ blog.djdj45.top |
| 11 | 写防护（守方线） | ❌ | ✅ dojo 守方 | — | ✅ blog 中间件 |
| 12 | 合规边界 | ❌ | — | 全部（robots.txt 实操） | — |

要点：**公开站点永远是副线**——判定（通过矩阵）只来自本地靶场契约；
所有公开站点练习都应配一份快照兜底，站点挂了课不断。

## 4. 公开靶场清单（2026-07 全部实测存活，2026-09-28 复核来源）

**CORS 列决定它能否进 C 路径浏览器版；标 ✅ 的才对浏览器版可用。**

| 站点 | CORS | 练什么 | 用于 |
|---|---|---|---|
| httpbin.org | ✅ | 请求/头/状态码/回显，限速与重试（/status/:code） | C·第 1 章；A·第 9 章 |
| jsonplaceholder.typicode.com | ✅ | JSON 列表获取 | 备选 |
| api.github.com | ✅ | 真实 API | 备选 |
| books.toscrape.com | ❌ | 静态分页 1000 条，完整性校验 | A·第 3 章 |
| scrapethissite.com | ❌ | 简单表格 / AJAX / 隐藏字段 | A·第 3 章 |
| quotes.toscrape.com | ❌ | /js、/scroll、/js-delayed、/login（CSRF 会话） | A·第 6、7、8 章 |
| web-scraping.dev | ❌ | 生产预演：GraphQL、封禁页、429+Retry-After、无限日历陷阱 | A·第 8、9 章 |

合规注意：公开站点仅限**明确欢迎爬取的练习站**；README 合规红线段需加一句
"本书仅对自有资产与公开练习站发起请求"。

## 5. 发布架构（路径 A / C 的托管）

```
crawler-labs (main)
├─ mkdocs.yml               # docs_dir: book（课文即站点源）
├─ book/
│  ├─ index.md              # 导读（三路径动线）
│  ├─ ch01.md / ch02.md …   # 课文（A 主线）
│  └─ interactive/          # C 试玩页（Pyodide）+ 冻结快照数据
└─ .github/workflows/docs.yml  # push → mkdocs build → GitHub Pages
```

- 站点地址：`https://djdj45-ssh.github.io/crawler-labs/`
- 内部设计文档（docs/）不在 `docs_dir` 内，**不发布**
- 发布动作 = 用户本地 `git push`（连接器只读，推送一直靠用户手动）
- Pyodide 走 jsDelivr CDN，页面加载失败时给出"请使用本地环境"的兜底提示

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| Pyodide CDN 不可达（国内网络波动） | 页面加载失败时显示明确兜底指引（转本地环境）；CDN 版本号写死，不做浮动 latest |
| 快照与靶场未来改版不同步 | `dojo-articles.json` 单文件、来源注释写明 manifest tag；重建快照时同步 |
| 公开站点改版/关站 | 只做副线 + 每章练习配快照兜底；主线判定永不依赖公网 |
| 浏览器版被误当真实环境 | 每页固定差异横幅 + UA 回显钩子提前暴露差异 |

## 7. Action items（按优先级）

1. ✅ mkdocs 骨架 + 导读页 + ch01/ch02 上线（本次）
2. ✅ C 试玩两页（httpbin / 快照垫片）（本次）
3. ☐ ch03–ch12 逐章生产（按 book-plan.md 节奏，每章完成即更新 nav）
4. ☐ 公开站点练习的具体实验设计（随各章课文一起写）
5. ☐ （可选，后期）Cloudflare Worker 迷你在线靶场（带 CORS），替代第 2 章的快照垫片
