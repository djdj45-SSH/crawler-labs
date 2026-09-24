# 章节编排

主线是**攻防回合**，不是库手册。每一章的结构固定：

```
1. 先让错误姿势失败一次（看见现象）
2. 指出为什么会失败（机制）
3. 给出正确姿势（方法）
4. 用一条断言把结论钉住（可复现）
```

只讲正确姿势的教程，读者记不住为什么。所以每一章都从失败开始。

---

## 全书结构

| 章 | 主题 | 靶场等级 | 实验 | 失败类型 |
|---|---|---|---|---|
| 1 | 环境、HTTP 基础、契约是什么 | — | 01 | — |
| 2 | `requests` 裸爬 | L0 | 02 | — |
| 3 | 解析层：BS4 / lxml | L0 | 03 | — |
| 4 | 礼貌爬虫：UA 与身份 | L1 | 04 | 策略 |
| 5 | 限流与退避 | L2 | 05 | 策略 |
| 6 | **数据可信：蜜罐识别** | L3 | 06 | 策略 |
| 7 | **HTML 里没有数据怎么办** | L4 | 07 / 08 | **技术** |
| 8 | Scrapy 工程化 + 时效签名 | L5 | 10 | 策略 |
| 9 | 数据落地：CSV / JSON / SQLite | — | 11 | — |
| 10 | **真实战场**：被改道之后 | 编辑边缘规则 | 09 | 策略 |
| 11 | 写防护：从边缘规则到中间件 | 对照 | 见 crawler-dojo/cloudflare | 守 |
| 12 | 合规边界、礼貌爬虫、综合实战 | all | — | — |
| 附 A | 请求库对比 requests / httpx / aiohttp | — | — | — |
| 附 B | 解析库对比 BS4 / lxml / parsel / re | — | — | — |

### 两类失败互补，这是编排最要紧的地方

- **第 7 章的技术性失败**：数据在，但 HTML 里拿不到（游戏站 `blockwild-game` 是天然案例 ——
  15 个 `<script>`，数据在 `src/sim/*.js` 深处）
- **第 10 章的策略性失败**：数据在，但你被拒绝了或被骗了（博客的 trap 页）

前者教你换工具，后者教你换态度。缺一个都不完整。

---

## 每章的靶场启动命令

防护是叠加的，所以后几章要单独开启对应等级：

```bash
# 第 1–3 章、第 9 章
python -m server.main --level none

# 第 4 章
python -m server.main --level L1

# 第 5 章
python -m server.main --level L2

# 第 6 章
python -m server.main --level L3

# 第 7 章
python -m server.main --level L4

# 第 8 章
python -m server.main --level L5

# 第 12 章：综合
python -m server.main --level all
```

---

## 还没做的事（下一步）

诚实地列在这里，免得以为是漏了：

- **第 8 章的 Scrapy 工程** —— 只写了签名实验（10），`scrapy_dojo/` 项目还没建。
  那是一个完整的 Scrapy 工程（spider / items / pipelines / middlewares），
  文件数不少，值得单独一次做完。
- **第 11 章的「写防护」** —— 素材在 `crawler-dojo/cloudflare/README.md`
  和博客仓库的 `tools/traps.rules.md`，但还没写成独立的一章。
- **附录 A / B** —— 库对比表还没写。现在只在实验室里零散提到。
- **HTML 快照（`fixtures/`）** —— 目录和说明建好了，但实验 03 目前是直接抓靶场，
  还没切到"抓一次存快照、之后离线解析"的流程。这一步做完，第 3 章就能完全脱靶场跑。
- **PostgreSQL 路径** —— `storage/models.py` 里 ORM 已经写好，换个连接串就能用，
  但实验只测了 SQLite。
