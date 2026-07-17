<div align="center" id="top">

<img src="frontend/nextjs/public/img/dailyhot-logo.svg" alt="DailyHot Logo" width="80">

# 🔥 DailyHot

**多平台热榜报告生成与追问分析系统**

自动抓取主流平台热榜 → LLM 意图识别 → 生成结构化报告 → 支持精准追问（口播稿 / 深度分析 / 联网补充）

基于 FastAPI + Next.js，Docker 一键部署。

</div>

---

## 目录

- [功能特性](#功能特性)
- [支持平台](#支持平台)
- [快速开始](#快速开始)
- [使用示例](#使用示例)
- [项目架构](#项目架构)
- [核心设计](#核心设计)
- [环境变量](#环境变量)
- [技术栈](#技术栈)
- [开源协议](#开源协议)

---

## 功能特性

- **自然语言输入** — "今日抖音热搜前20"、"B站前30分析"，无需记忆命令
- **智能意图识别** — LLM 解析目标平台、分类和数量，返回结构化 JSON
- **多平台热榜** — 抖音、B站、头条、澎湃、百度、36氪、少数派、V2EX、掘金等
- **主干 + 辅助分层** — 主干平台按用户需求条数，辅助平台取 50 条做大池子供跨平台匹配
- **实体过滤匹配** — find_related 使用 embedding 语义 + 实体重合硬过滤，阈值 0.65
- **追问双路径** — 直接定位（"第N个"/"XX平台那条"走 hot_items）+ RAG 全文检索（关键词提问走 embedding）
- **联网搜索补充** — DuckDuckGo，safesearch='on' + 域名黑名单过滤
- **多种输出格式** — Markdown / PDF / DOCX，支持转发飞书
- **流式推送** — WebSocket 实时显示分析进度
- **Docker 部署** — 一行命令启动完整服务

---

## 支持平台

| 平台 | 代码 | 类型 | 可读正文 |
|------|------|------|----------|
| 抖音 | `douyin` | 短视频热榜 | 否（视频为主） |
| Bilibili | `bilibili` | 视频热榜 | 否 |
| 今日头条 | `toutiao` | 新闻热榜 | 是 |
| 澎湃新闻 | `thepaper` | 新闻热榜 | 是 |
| 百度 | `baidu` | 热搜榜 | 部分 |
| 36氪 | `36kr` | 科技财经 | 是 |
| 少数派 | `sspai` | 数码科技 | 是 |
| V2EX | `v2ex` | 技术社区 | 是 |
| 掘金 | `juejin` | 开发者社区 | 是 |

---

## 快速开始

### 使用 Docker（推荐）

> **前提**：安装 [Docker](https://docs.docker.com/get-docker/) 和 Docker Compose

```bash
# 1. 克隆项目
git clone https://github.com/your-repo/dailyhot.git
cd dailyhot

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM API Key（见下方环境变量说明）

# 3. 启动服务
docker compose up --build

# 4. 访问
# 前端: http://localhost:3000
# 后端 API: http://localhost:8001
```

### 手动安装

> **前提**：Python 3.11+

```bash
# 克隆项目
git clone https://github.com/your-repo/dailyhot.git
cd dailyhot

# 安装依赖
pip install -r requirements.txt
pip install -r backend/requirements.txt
pip install -e .

# 配置 .env（同上）

# 启动后端
python backend/run_server.py

# 另开终端，启动前端
cd frontend/nextjs
npm install
npm run dev
```

---

## 使用示例

### 生成报告

在页面输入框中输入自然语言：

```
今日抖音热搜前20总结
```

```
今日头条热搜前30，时政类
```

```
B站前15，每条详细分析
```

系统自动完成：意图识别 → 数据采集 → 跨平台匹配 → LLM 分析 → 流式输出

### 追问分析

报告生成后，可针对具体条目提问：

```
对第一条详细分析，写一篇3000字口播稿
```

```
第三个热搜的口播稿
```

```
重庆彭水那条新闻最新进展是什么
```

```
写一份适合3分钟讲述的口播稿，口语化
```

支持格式："第N个"、"第N条"、"第N位"、"XX平台那条"、标题关键词

---

## 项目架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Frontend (Next.js)                           │
│  ┌──────────┐  ┌───────────┐  �──────────────────────────────┐  │
│  │ 输入框   │  │ 报告展示  │  │ 追问聊天（支持下载/飞书转发） │  │
│  └────┬─────┘  └────▲──────┘  └──────────────┬───────────────┘  │
└───────┼──────────────┼────────────────────────┼─────────────────┘
        │              │                        │
        │ WebSocket    │                        │ REST API
        │              │                        │
┌───────▼──────────────┼────────────────────────▼─────────────────┐
│                  Backend (FastAPI)                               │
│                                                                 │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │ WebSocket      │  │ /api/chat       │  │ /api/chat/feishu │  │
│  │ /ws            │  │ /api/reports/   │  │ /api/chat/export │  │
│  │ (报告生成)     │  │ {id}/chat       │  │                  │  │
│  └───────┬────────┘  └────────┬────────┘  └──────────────────┘  │
│          │                    │                                   │
│  ┌───────▼────────────────────▼──────────────────────────────┐   │
│  │                                                            │   │
│  │  ┌──────────────┐    ┌───────────────┐                    │   │
│  │  │ intent_agent │    │ ChatAgent     │                    │   │
│  │  │ (意图识别)   │    │ (追问)        │                    │   │
│  │  └──────┬───────┘    └───────┬───────┘                    │   │
│  │         │                    │                            │   │
│  │  ┌──────▼────────────────────▼──────┐                     │   │
│  │  │ hot_list_agent (ReAct)           │                     │   │
│  │  │ → MCP get_all_hot_list           │                     │   │
│  │  └──────┬───────────────────────────┘                     │   │
│  │         │                                                  │   │
│  │  ┌──────▼─────────────┐                                    │   │
│  │  │ HotListReport      │                                    │   │
│  │  │ (主干+辅助分层分析)│                                    │   │
│  │  └──────┬─────────────┘                                    │   │
│  │         │                                                  │   │
│  │  ┌──────▼──────────────────────────────────────────┐       │   │
│  │  │ MCP hot_list_server (stdio transport)           │       │   │
│  │  │ Tools: get_all_hot_list / generate_hot_report   │       │   │
│  │  └────────────────────────────────────────────────┘       │   │
│  └────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### 数据流（报告生成）

```
用户输入 "今日抖音前20"
    │
    ▼
① WebSocket → /ws
    │
    ▼
② intent_agent: 自然语言 → {is_hot_list, primary_codes:["douyin"], category:"all"}
    │
    ▼
③ extract_limit_from_query("前20") → primary_limit=20
    │
    ▼
④ MCP get_all_hot_list(default_limit=50, primary_limit=20)
    ├─ douyin（主干）→ API 拉 20 条
    ├─ toutiao/thepaper/...（辅助）→ 各拉 50 条做匹配池
    │
    ▼
⑤ HotListReport.run()
    ├─ 主干 20 条 → 逐条 fetch_article_text → LLM 摘要（并发 30 线程）
    ├─ 每条主干 → find_related 从辅助 50 条池里匹配跨平台新闻
    │
    ▼
⑥ WebSocket push:
    ├─ logs/hot_item: 流式展示单条分析
    ├─ report/report_complete: 最终报告
    └─ metadata.hot_items: 结构化索引（供追问用）
```

### 数据流（追问）

```
用户说 "第一条口播稿"
    │
    ▼
① POST /api/chat {report, hot_items, messages}
    │
    ▼
② _resolve_target_index("第一条") → idx=0
    │
    ▼
③ 路径A（hot_items 能定位）:
    ├─ hot_items[0] → title + url + summary + related_links
    ├─ quick_search(title) → 联网补充
    └─ 全部 + 索引表 → LLM
    
    路径B（无法定位，如 "重庆彭水那条新闻" 但 hot_items 里没有匹配）:
    ├─ RAG retrieve(query) → 报告全文语义检索
    ├─ quick_search(query) → 联网补充
    └─ 全部 → LLM
    │
    ▼
④ 返回 assistant 消息
```

---

## 核心设计

### 1. 主干 + 辅助分层架构

报告生成时的平台角色分离：

| 角色 | 说明 | 拉取条数 |
|------|------|----------|
| **主干平台** | 用户关心的主要平台（如"抖音前20"→douyin） | 用户指定（前N→N条） |
| **辅助平台** | 其余 8 个平台，用于跨平台匹配 | 固定 50 条（大池子） |

设计理由：各平台排名不对齐。主干排第 5 的新闻，在辅助平台可能排第 20+，所以辅助池必须足够大才能兜住匹配。辅助池跟用户需求的 N 无关，固定 50 条不论用户说前 20 还是前 40。

### 2. 区分拉取 vs 后截断

优化前：所有平台各拉 50 条，主干后截断到用户需求数 → API 浪费

优化后：MCP `get_all_hot_list(default_limit=50, primary_limit=20)` 区分参数，主干直接拉 20 条，不多拉。

### 3. 跨平台匹配策略

**find_related 算法**：

```
候选新闻标题（辅助池50条）
    │
    ▼
① embedding 向量化（余弦相似度）
    │ 阈值 0.65（原 0.5，过滤 "中专生高考" vs "DV磁带" 这种弱相关）
    ▼
② 实体重合硬过滤
    │ 两条标题必须共享至少一个实体（人名/地名/品牌/事件关键词）
    │ 关键词提取：优先 jieba（如可用），否则 2-4 字滑动窗口
    ▼
③ 取 top-2 输出
```

### 4. 追问双路径

| 场景 | 路径 | 数据来源 |
|------|------|----------|
| "第一条口播稿" | hot_items 直接定位 | `hot_items[0].{title,summary,url,related_links}` + 联网搜索 |
| "第三条深度分析" | hot_items 直接定位 | `hot_items[2]` + 联网搜索 |
| "重庆彭水山体垮塌最新进展" | RAG | embedding 检索报告全文 + 联网搜索 |
| "未成年人网络保护条例" | RAG | embedding 检索报告全文 + 联网搜索 |

路径优先级：先尝试 hot_items 定位（阿拉伯数字、中文数字、平台名、标题关键词四种匹配），定位不到再退到 RAG 全文检索。

### 5. 结构化 hot_items 推送

`report_complete` 消息附带 `metadata.hot_items` 数组，前端存为 state。追问时原样传给 `/api/chat`，后端直接数组下标取值，O(1) 精准定位，不需要从报告文本里解析"第N个指什么"。

```json
{
  "type": "report",
  "content": "report_complete",
  "output": "# 📊 2025年X月X日 热榜报告...",
  "metadata": {
    "hot_items": [
      {"platform":"douyin","rank":1,"title":"...","hot":"1153万","url":"...","summary":"...","related_links":[...]},
      ...
    ]
  }
}
```

### 6. 内容安全过滤

搜索结果过滤三层：
- DuckDuckGo `safesearch='on'` 开启安全搜索
- 域名黑名单（成人、赌博等 14 个域名）
- 标题关键词过滤（中英文违规词）

### 7. 中文数字解析

用户自然输入"第十二条"、"第三个"、"第二位"，不用强制写"第12条"。`_chinese_to_int()` 支持零~千的中文数字转换 + 混合识读（"三百二十五"→325）。

### 8. 追问输出格式

系统提示内置格式引导：
- 「口播稿」：约 750 字，口语化，开场白 + 3 段主体 + 结尾互动
- 「深度分析」：约 500 字，带小标题，背景→现状→影响→展望
- 「总结」：100 字以内，3 个 bullet

### 8. MCP 工具隔离

ReAct agent 的工具列表只保留 `get_*` 和 `list_*` 前缀，排除 `generate_hot_report`、`chat_about_hot_report`。防止 LLM 误调导致超时或循环。

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | LLM API Key | - |
| `OPENAI_BASE_URL` | 自定义 API 地址（如 LongCat） | - |
| `OPENAI_EMBEDDING_MODEL` | embedding 模型名 | `text-embedding-3-small` |
| `FAST_LLM` | 快速 LLM（意图识别等） | `openai:gpt-4o-mini` |
| `SMART_LLM` | 智能 LLM（分析/追问） | `openai:gpt-4o` |
| `RETRIEVER` | 搜索引擎 | `duckduckgo` |
| `FEISHU_WEBHOOK_URL` | 飞书推送 Webhook（可选） | - |
| `TONE` | 报告语气 | `Objective` |

> **注意**：`NEXT_PUBLIC_*` 环境变量在 Next.js 构建时内联。`docker-compose.yml` 通过 `ARG` 注入，构建时传入。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `backend/server/websocket_manager.py` | WebSocket `/ws` 入口，分流 HotListReport |
| `backend/hot_research/hot_list_agent.py` | ReAct agent 调 MCP，一次性拉取全平台数据 |
| `backend/report_type/hot_list_report/hot_list_report.py` | 多头干+辅助分层分析，生成 Markdown 报告 |
| `backend/mcp_servers/hot_list_server.py` | MCP server（stdio），供 tools: get_all_hot_list / generate_hot_report |
| `backend/hot_research/daily_hot_api.py` | 平台 API 封装 + find_related 匹配算法 |
| `backend/chat/chat.py` | ChatAgent，追问双路径（hot_items 定位 + RAG） |
| `backend/server/app.py` | FastAPI 路由（/api/chat, /api/chat/feishu, /api/chat/export） |
| `frontend/nextjs/hooks/useWebSocket.ts` | WebSocket 连接 + 热榜条目捕获 |
| `frontend/nextjs/app/page.tsx` | 主页面，handleChat 透传 hot_items |

---

## 技术栈

- **后端**：Python、FastAPI、LangGraph (create_react_agent)、FastMCP
- **前端**：Next.js、React、TypeScript、Tailwind CSS
- **LLM**：OpenAI 兼容 API（默认 LongCat）
- **嵌入**：OpenAI text-embedding-3-small（可选本地 HuggingFace 回退）
- **搜索**：DuckDuckGo（免费，无需 API key）
- **部署**：Docker、Docker Compose

---

## 开源协议

本项目基于 Apache License 2.0 协议开源，详见 [LICENSE](LICENSE) 文件。

---

<p align="right">
  <a href="#top">⬆️ 返回顶部</a>
</p>
