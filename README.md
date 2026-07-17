<div align="center" id="top">

<img src="frontend/nextjs/public/img/dailyhot-logo.svg" alt="DailyHot Logo" width="80">

# 🔥 DailyHot

**多平台热榜报告生成器 — 自动抓取并分析热点趋势**

基于 LLM 意图识别，支持抖音、B站、知乎、微博、头条等主流平台热榜，生成结构化的热点分析报告。

[English](README.md) | [中文](README-zh_CN.md)

</div>

## 功能特性

- 🎯 **智能意图识别** — 用户输入自然语言，LLM 自动解析目标平台、类别和数量
- 📊 **多平台热榜** — 支持抖音、Bilibili、知乎、微博、今日头条、36氪、少数派、V2EX、掘金等
- 📝 **自动报告生成** — 抓取热榜条目 → 联网搜索补充 → LLM 分析 → 输出结构化报告
- 💬 **追问助手** — 报告生成后可针对具体条目追问（口播稿、深度分析等）
- 🐳 **Docker 部署** — 一行命令启动完整服务（后端 FastAPI + 前端 Next.js）
- 📄 **PDF 导出** — 支持将报告导出为 PDF 格式

## 支持的平台

| 平台 | 代码 | 说明 |
|------|------|------|
| 抖音 | douyin | 短视频热榜 |
| Bilibili | bilibili | 视频热榜与评论 |
| 知乎 | zhihu | 热榜问答 |
| 微博 | weibo | 热搜榜 |
| 今日头条 | toutiao | 新闻热榜 |
| 36kr | 36kr | 科技财经 |
| 少数派 | sspai | 数码科技 |
| V2EX | v2ex | 技术社区 |
| 掘金 | juejin | 开发者社区 |
| 百度 | baidu | 热搜榜 |

## 快速开始

### 使用 Docker（推荐）

> **前提**：安装 [Docker](https://docs.docker.com/get-docker/) 和 Docker Compose

1. 克隆项目：

```bash
git clone https://github.com/your-repo/dailyhot.git
cd dailyhot
```

2. 配置环境变量：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 LLM API Key：

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=your_api_base_url  # 如果使用自定义 API
```

3. 启动服务：

```bash
docker-compose up --build
```

4. 访问 [http://localhost:3000](http://localhost:3000) 开始使用

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

## 使用示例

在输入框中输入自然语言：

```
今日抖音热榜报告总结
```

```
帮我看看 B 站和知乎现在在讨论什么
```

```
微博热搜前 10 条，每条简要分析
```

系统会自动：
1. 识别意图（平台、类别、数量）
2. 抓取对应平台热榜数据
3. 联网搜索补充信息
4. 生成结构化分析报告

## 项目架构

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ 输入框  │  │ 报告展示 │  │ 追问聊天         │   │
│  └────┬────┘  └────▲─────┘  └───────┬──────────┘   │
└───────┼─────────────┼────────────────┼──────────────┘
        │             │                │
        │  WebSocket  │                │  REST API
        │             │                │
┌───────▼─────────────┼────────────────▼──────────────┐
│                 Backend (FastAPI)                    │
│                                                     │
│  ┌──────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ 意图识别 LLM │→│ HotList    │→│ ChatAgent  │  │
│  │ (结构化JSON) │  │ Report     │  │ (追问)     │  │
│  └──────────────┘  └─────┬──────┘  └────────────┘  │
│                          │                          │
│                   ┌──────▼──────┐                   │
│                   │ 平台 API    │                   │
│                   │ + Web搜索   │                   │
│                   └─────────────┘                   │
└─────────────────────────────────────────────────────┘
```

### 数据流

1. **用户输入** → WebSocket 发送 task
2. **意图识别** → LLM 返回 `{is_hot_list, primary_codes, category, confidence}`
3. **报告生成** → `HotListReport` 根据平台代码抓取热榜 → 联网搜索 → LLM 分析
4. **报告推送** → WebSocket 返回 `report_complete`（含结构化 `hot_items`）
5. **追问** → `/api/chat` 接收报告 + 热榜索引 → LLM 可精准定位条目并联网搜索

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | LLM API Key | - |
| `OPENAI_BASE_URL` | 自定义 API 地址 | - |
| `FAST_LLM` | 快速 LLM 模型 | `openai:gpt-4o-mini` |
| `SMART_LLM` | 智能 LLM 模型 | `openai:gpt-4o` |
| `RETRIEVER` | 搜索引擎 | `duckduckgo` |
| `TONE` | 报告语气 | `Objective` |
| `WORKERS` | 并发 workers | `1` |

## 技术栈

- **后端**：Python, FastAPI, LangChain, DuckDuckGo Search
- **前端**：Next.js, React, TypeScript, Tailwind CSS
- **LLM**：OpenAI 兼容 API（支持自定义模型）
- **部署**：Docker, Docker Compose

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---

<p align="right">
  <a href="#top">⬆️ Back to Top</a>
</p>
