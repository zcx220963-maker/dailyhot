<div align="center" id="top">

<img src="frontend/nextjs/public/img/dailyhot-logo.svg" alt="DailyHot Logo" width="80">

# 🔥 DailyHot

**多平台热榜报告生成与追问分析系统**

自动抓取主流平台热榜 → LLM 意图识别 → 生成结构化报告 → 支持精准追问（口播稿 / 深度分析 / 联网补充）

基于 FastAPI + Next.js。

</div>

---

## 目录

- [功能特性](#功能特性)
- [支持平台](#支持平台)
- [快速开始](#快速开始)
- [使用示例](#使用示例)
- [项目架构](#项目架构)
- [核心设计](#核心设计)
- [功能演进](#功能演进)
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
- 域名黑名单（成人、赌博等多个域名）
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

> **注意**：`NEXT_PUBLIC_*` 环境变量在 Next.js 构建时内联。手动部署时通过 `.env.local` 或 shell 环境变量传入。

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

---

## 功能演进

DailyHot 是在 gpt-researcher 通用研究助手框架上、为”中文热榜分析”场景深度定型的项目。以下按时间线记录六大阶段的设计抉择、踩坑与修复。

### 阶段 0：起点（gpt-researcher）

原始框架提供：
- 通用研究 agent（`GPTResearcher`）：搜索 → 抓取 → 嵌入 → 报告 → 追问
- Next.js 前端 + FastAPI 后端 + WebSocket 流式推送
- LangGraph ReAct 循环、工具调用、向量 RAG

保留并复用的部分：WebSocket 流式推送骨架、`/api/reports` 持久化接口、前端 `useWebSocket` hook 与 `ReportStore` JSON 文件存储。从这里出发定制为垂直场景。

---

### 阶段 1：热榜抓取 + 跨平台匹配

**目标**：让 LLM 分析“今日抖音前 20”，而不是一般性研究问题。

新增：
- **意图识别** — 前端传入自然语言 prompt，后端 `hot_list_agent`（ReAct agent + MCP）识别 `is_hot_list`、提取 `primary_codes`（主干平台列表）和 `category`。
- **MCP server**（`hot_list_server.py`，stdio transport）— 把 DailyHotApi 各平台封装为 `get_all_hot_list(code, limit)` 工具，由 agent 调用，避免 LangChain 工具签名/并发问题。
- **主干/辅助分层** — 主干平台按需求条数拉取（`primary_limit` = N），辅助平台固定 50 条做大池子供跨平台 `find_related` 匹配。原因：各平台排名不对齐，主干第 5 在辅助平台可能第 20+，小池子兜不住。
- **find_related 算法改进** — embedding 余弦相似度（阈值从 0.5 调到 0.65，过滤“中专生高考” vs “DV磁带”这类弱相关） + 实体重合硬过滤（两条标题必须共享至少一个实体，jieba 优先、2-4 字滑动窗口兜底） → 取 top-2。

---

### 阶段 2：报告生成

定制 `report_type/hot_list_report/HotListReport`：
- 继承 `BaseReport` 接入 WebSocket 流式推送骨架，新增 `analyses` 字段存 `(platform, rank, title, hot, summary, related_links, url)` 七元组。
- 并发 30 线程 `fetch_article_text` 抓正文 → LLM 摘要（`report_language=zh`）。
- 跨域改写：辅助池匹配上的跨平台新闻，LLM 用原文摘要 + 实体重合硬过滤结果判定相关性，命中才写入 `related_links`。

报告完成后，通过 `stream_output("report", "report_complete", report, ws, True, metadata={"hot_items": hot_items})` 把 `analyses` 结构化为 `metadata.hot_items` 数组推给前端。这是后续追问精准定位的数据源头。

---

### 阶段 3：追问精准定位

**遇到的问题**：追问“第三条口播稿”时，后端只看到纯 markdown 文本，无从知道“第三条”指什么。

**设计抉择**：不走“从报告文本解析第N个热点”（脆弱），改用“前端带结构化 state 给后端”：

1. 后端 `report_complete` 推送 `metadata.hot_items`，前端 `useWebSocket` 回调捕获到 `hotItems` state。
2. `handleChat(message)` 把 `{report, hot_items, messages}` 一并 POST 到 `/api/chat`。
3. 后端 `ChatAgentWithMemory(report, hot_items)` 接收，`_resolve_target_index(latest_user_msg)` 解析“第N个”：
   - 阿拉伯数字：`热点8`、`第3条`、`第12位`
   - 中文数字：`热点八`、`第八条`、`第三`
   - 平台名：`抖音那条`、`B站那个`
   - 标题关键词：标题里任意连续 4 字出现在用户消息 → 走这条
4. 能定位 → `_build_item_context(idx)` 取出 `title / url / summary / related_links` 作为上下文；定位不到 → RAG 全文检索兜底。
5. 双路径内容 + 索引表 + 联网搜索结果 → 进 LLM system prompt。

**踩坑**：
- 中文数字解析最初只认 `第八`（“第”+中文数字），不支持 `热点八`（“热点”+中文数字） → 用户说“分析热点八”进入 None → RAG 兜底为空 → 联网搜索也搜不到 → LLM 返回“资料不足”。通过新增 `热点/第 + 中文数字 + [个条位号]?` 分支修复。
- RAG 检索后端原本活跃，后改为仅做兜底空实现 `return ""`（报告全文已足够长，不需要切片）。后续维护要记得双路径里 RAG 路径已空。

---

### 阶段 4：联网搜索 + 安全过滤

追问场景热点变化快（事件反转、官方回应、网友评论），报告生成时的分析已经过时，所以追问必须联网。

**quick_search**（DuckDuckGo，免费无需 API key，`safesearch='on'`）：
- 搜索目标标题（有定位时）或用户原始问题（定位不到时）
- 过滤三层：域名黑名单（成人、赌博等多个） + 标题关键词过滤 + 正文逐句 `_sanitize_body` 清洗
- 解析失败不抛错，返回空结果让 LLM 兜底用 hot_items 数据正常回答

**踩坑**：搜索结果偶有成人内容混入。单独增加 `_sanitize_body`：按句号/感叹号/问号粒度去掉命中关键词的句子，保留其余部分，避免一刀切截断。

---

### 阶段 5：多格式导出 + 字体战争

最初用 WeasyPrint + `md2pdf` 生成 PDF，依赖 `libgobject`，Debian slim 镜像里装不上。

**PDF 渲染三阶段演化**：

| 尝试 | 方案 | 失败原因 |
|------|------|----------|
| 1 | WeasyPrint (CSS→PDF) | 缺 libgobject，apt 装不上 |
| 2 | md2pdf (轻量) | 同样依赖 Pango/Fontconfig 子系统 |
| 3 | **fpdf2 + wqy-zenhei.ttc** |  纯 Python + TTF，不依赖系统图形栈 |

fpdf2 接入后又踩两坑：
- **`multi_cell(0, X)` 报 "Not enough horizontal space to render a single character"**：fpdf2 的 `multi_cell` 结束后默认把光标 X 移到页面右边界，下一段文字起笔时已在边缘外 → 渲染崩溃。解决：4 处 `multi_cell` 全部加 `new_x=XPos.LMARGIN, new_y=YPos.NEXT` 让每段回到左边距。
- **前端 proxy 把二进制流当 JSON 解析**：Next.js proxy route 最初对 PDF/DOCX 也 `await response.json()` → "Unexpected token 'P'"。解决：按 `Content-Type` 分流（JSON 仍解析，其余 `arrayBuffer` → `Buffer` 透传），前端再加 `triggerDownload(blob, filename)` 用 `<a>.click()` 触发下载。

DOCX 是 `python-docx + htmldocx`，Markdown → HTML → DOCX，CJK 和 emoji 直接由 docx 字体 fallback 处理。

**最终决策**：PDF / DOCX 链路都已打通，但 CJK 字体依赖对跨平台部署仍脆弱。**UI 现在只保留 Markdown 导出**（后端 `/api/chat/export` 仍支持完整三种格式，可通过 API 直接调用）。

---

### 阶段 6：持久化 + 环境踩坑

**报告持久化**：
- 后端 `ReportStore`：单文件 `backend/data/reports.json`（`{report_id: {question, answer, orderedData, chatMessages}}`），bind mount 到宿主机，容器重启/重建保留。
- 前端：首次加载从 `/api/reports` 拉全量，写入 `localStorage.researchHistory` 作离线 fallback；每个追问通过 `POST /api/reports/{id}/chat` 同步到后端。

**踩坑三连**：

| 问题 | 根因 | 修复 |
|------|------|------|
| PDF/DOCX 下载 HTTP 500 | `.env.local` `NEXT_PUBLIC_GPTR_API_URL=http://localhost:8001` 覆盖了容器内部服务名地址，前端进程里 `localhost` 指自己 | 删 `.env.local` 覆盖，让容器内环境变量自然生效 |
| 历史“丢”了 | `useResearchHistory` 只在 localStorage 有记录时才 fetch 后端；清缓存/换端口/隐身 → localStorage 空 → 不请求服务端 | 始终先 GET `/api/reports` 全量；服务端挂了才 fallback localStorage |
| 容器重启后数据消失(假象) | bind mount 路径含单引号(`xu'zhi'cheng`)时 Git Bash 的 `${PWD}` 偶有解析异常 | 后端实际落盘成功，数据仍在，前端展示层见上 |

---

### 阶段 7：UI 收敛

最近的 UI 整理：
- 删除 PDF / DOCX 导出按钮（脆弱度高、中文字体包重），聊天回答保留 Markdown 下载。
- 复制 / 下载 / 转发飞按钮从回答右上角移到回答文本左下角，便于单手触达。
- 下载按钮不再弹出三级菜单，直接一键下载 `.md`。

---

### 当前状态（代码整洁度）

近 6 次 commit 都是 bug fix，没有新功能加入。所有 fix 都 push 到 `main`，仓库历史线性、无其他分支。敏感文件（`.env`、`cookies.txt`、`reports.json`）已 `.gitignore`。

---

## 开源协议

本项目基于 Apache License 2.0 协议开源，详见 [LICENSE](LICENSE) 文件。

---

<p align="right">
  <a href="#top">⬆️ 返回顶部</a>
</p>
