import logging
import os
import uuid
import json
import numpy as np
from fastapi import WebSocket
from typing import List, Dict, Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from gpt_researcher.config.config import Config
from gpt_researcher.utils.llm import create_chat_completion
from gpt_researcher.utils.tools import create_chat_completion_with_tools, create_search_tool
from datetime import datetime

# Setup logging
# Get logger instance
logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # Only log to console
    ]
)

# Note: LLM client is now handled through GPT Researcher's unified LLM system
# This supports all configured providers (OpenAI, Google Gemini, Anthropic, etc.)

def get_tools():
    """Define tools for LLM function calling (primarily for OpenAI-compatible providers)"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "quick_search",
                "description": "Search for current events or online information when you need new knowledge that doesn't exist in the current context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    return tools

class ChatAgentWithMemory:
    def __init__(
        self,
        report: str,
        config_path="default",
        headers=None,
        vector_store=None,
        hot_items=None,
    ):
        self.report = report
        self.headers = headers
        self.config = Config(config_path)
        self.retriever = None
        self.search_metadata = None
        self.hot_items = hot_items or []

        # RAG 相关
        self._chunks: List[str] = []
        self._embeddings: Optional[np.ndarray] = None
        self._embed_fn = None

        # DuckDuckGo search (free, no API key needed)
        self._ddgs = None

        # 初始化 RAG（切片 + 嵌入）
        self._setup_rag()

    def _hot_items_prompt(self) -> str:
        """生成热榜条目索引表 + 追问格式指引（仅当 hot_items 非空时）。"""
        if not self.hot_items:
            return ""
        idx_lines = []
        for i, item in enumerate(self.hot_items, 1):
            hot_str = item.get("hot", "")
            hot_display = f" (🔥{hot_str})" if hot_str else ""
            url = item.get("url", "")
            url_display = f"  {url}" if url else ""
            idx_lines.append(
                f"{i}. [{item.get('platform', '')} #{item.get('rank', i)}] "
                f"{item.get('title', '')}{hot_display}{url_display}"
            )
        idx_table = "\n".join(idx_lines)
        return (
            "## 热榜条目索引（用户可能用「第N个」「XX平台那条」等方式指代）\n\n"
            f"{idx_table}\n\n"
            "当用户针对某条热点追问时：\n"
            "1. 先根据索引表确定用户指的是哪条（注意区分平台 + 排名）\n"
            "2. 用 quick_search 联网搜索该标题的最新信息（如事件进展、官方回应、网友评论）\n"
            "3. 结合报告中的已有分析，给出回答\n\n"
            "输出格式指引：\n"
            "- 「口播稿」：约 750 字，口语化，开场白 + 3 段主体 + 结尾互动，适合 3 分钟讲述\n"
            "- 「深度分析」：约 500 字，带小标题，背景→现状→影响→展望\n"
            "- 「总结」：100 字以内，3 个 bullet\n"
            "- 其他：按用户要求"
        )

    def _build_item_context(self, idx: int) -> str:
        """从 hot_items 直接构建第 idx 条的新闻上下文（标题+摘要+跨平台链接）。"""
        if not self.hot_items or idx < 0 or idx >= len(self.hot_items):
            return ""
        item = self.hot_items[idx]
        lines = [
            f"## 新闻 #{idx+1}",
            f"**平台**: {item.get('platform', '')}  **排名**: #{item.get('rank', '')}  **热度**: {item.get('hot', '')}",
            f"**标题**: {item.get('title', '')}",
        ]
        if item.get("url"):
            f"**链接**: {item['url']}"
            lines.append(f"**链接**: {item['url']}")
        if item.get("summary"):
            lines.append(f"**报道摘要**:\n{item['summary']}")
        related = item.get("related_links", [])
        if related:
            lines.append("**跨平台相关报道**:")
            for r in related:
                u = r.get("url", "")
                t = r.get("title", "")
                p = r.get("platform", "")
                line = f"  - {p}: {t}"
                if u:
                    line += f" → {u}"
                lines.append(line)
        return "\n".join(lines)

    def retrieve(self, query: str, top_k: int = 4) -> str:
        """保留接口兼容性，实际不再使用（改用 hot_items 直接定位）。"""
        return ""

    # 违规域名黑名单（成人、赌博、垃圾站等）
    _BLOCKED_DOMAINS = {
        '51chigua', '51cg', 'hgyubxjlw', 'theporndude', 'pornhub',
        'xvideos', 'xhamster', 'redtube', 'youporn', 'spankbang',
        'chaturbate', 'onlyfans', 'fansly', 'manyvids',
    }

    def _is_blocked(self, url: str, title: str = "") -> bool:
        """检查 URL 或标题是否包含违规内容。"""
        from urllib.parse import parse_qs, urlparse
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        # 域名黑名单
        for domain in self._BLOCKED_DOMAINS:
            if domain in host:
                return True
        # 标题关键词过滤（中文 + 英文）
        blocked_keywords = [
            '口爆', '吞精', '做爱', '性爱', '裸聊', '约炮', '援交',
            'porn', 'xxx', 'sex', 'nude', 'naked', 'escort',
        ]
        title_lower = (title or "").lower()
        for kw in blocked_keywords:
            if kw in title_lower:
                return True
        return False

    def quick_search(self, query):
        """Perform a web search for current information using DuckDuckGo"""
        try:
            logger.info(f"Performing DuckDuckGo search for: {query}")
            from ddgs import DDGS
            # safesearch='on' 开启安全搜索，过滤成人内容
            raw = list(DDGS().text(query, region='cn-zh', max_results=8, safesearch='on'))
            # 过滤违规结果
            filtered = [r for r in raw if not self._is_blocked(r.get("href", ""), r.get("title", ""))]
            # 如果过滤后不足 3 条，说明查询本身可能有问题，返回空
            if len(filtered) < 1 and len(raw) > 0:
                logger.warning(f"quick_search: 所有 {len(raw)} 条结果均被过滤，查询可能涉及违规内容: {query}")
                return {"results": [], "filtered": True}
            results = {
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "content": r.get("body", ""),
                    }
                    for r in filtered[:5]
                ]
            }
            # Store search metadata for frontend
            self.search_metadata = {
                "query": query,
                "sources": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "content": r.get("body", "")[:200] + "..." if len(r.get("body", "")) > 200 else r.get("body", ""),
                    }
                    for r in filtered[:5]
                ],
            }
            return results
        except Exception as e:
            logger.error(f"Error performing DuckDuckGo search: {str(e)}", exc_info=True)
            return {"error": str(e), "results": []}


    async def process_chat_completion(self, messages: List[Dict[str, str]]):
        """Process chat completion using configured LLM provider.
        使用简单 LLM 调用（不依赖工具调用），兼容性更好。
        """
        from gpt_researcher.utils.llm import create_chat_completion
        response = await create_chat_completion(
            messages=messages,
            model=self.config.smart_llm_model,
            llm_provider=self.config.smart_llm_provider,
            llm_kwargs=self.config.llm_kwargs,
        )
        return response, []


    async def chat(self, messages, websocket=None):
        """Chat with configured LLM provider.
        双路径策略：
        - 路径A：hot_items 能直接定位（"第N个"、"XX平台那条"、标题关键词）→ 用结构化数据
        - 路径B：定位不到 → RAG 检索报告全文兜底
        """
        try:
            # 1. 取出最新一条用户消息
            latest_user_msg = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    latest_user_msg = msg.get("content", "")
                    break

            # 2. 路径A：hot_items 直接定位
            item_context = ""
            targeted_title = ""
            targeted_idx = self._resolve_target_index(latest_user_msg)
            if targeted_idx is not None:
                item_context = self._build_item_context(targeted_idx)
                targeted_title = self.hot_items[targeted_idx].get("title", "")

            # 3. 路径B：定位不到 → RAG 检索报告全文
            rag_context = ""
            if not item_context:
                rag_query = targeted_title if targeted_title else latest_user_msg
                rag_context = self.retrieve(rag_query, top_k=4) if rag_query else ""

            # 4. 联网搜索（有目标标题搜目标，否则搜用户原始问题）
            search_context = ""
            search_metadata = None
            if targeted_title or latest_user_msg:
                search_results = self.quick_search(targeted_title if targeted_title else latest_user_msg)
                search_metadata = self.search_metadata
                if search_results and search_results.get("results"):
                    parts = []
                    for r in search_results["results"][:3]:
                        parts.append(f"[{r.get('title', '')}]({r.get('url', '')})\n{r.get('content', '')[:300]}")
                    search_context = "\n\n".join(parts)

            # 5. 日志
            logger.info(f"[CHAT] mode={'item' if item_context else 'rag'}, "
                        f"idx={targeted_idx}, title='{targeted_title}', "
                        f"item_ctx={len(item_context)}, rag={len(rag_context)}, search={len(search_context)}")

            # 6. 系统提示
            system_parts = [
                "你是一个专业资讯分析师。用户正在看一份热榜报告，针对某条热点追问。",
                "**必须严格基于提供的新闻资料和联网搜索来回答**，不要使用自己的先验知识。",
                "如果资料为空或不足以回答，请明确告知用户而非编造内容。",
                "",
                "输出格式要求：",
                "- 使用 Markdown 格式，段落清晰",
                "- 口播稿：约 750 字，口语化，开场白 + 3 段主体 + 结尾互动",
                "- 深度分析：约 500 字，带小标题，背景→现状→影响→展望",
                "- 总结：100 字以内，3 个 bullet",
                f"当前时间：{datetime.now().strftime('%Y年%m月%d日')}",
            ]
            hot_prompt = self._hot_items_prompt()
            if hot_prompt:
                system_parts.append(hot_prompt)

            system_prompt = "\n".join(system_parts)

            # 7. 组装消息：hot_items 优先，RAG 兜底
            formatted_messages = [{"role": "system", "content": system_prompt}]

            if item_context:
                formatted_messages.append({
                    "role": "assistant",
                    "content": f"用户针对以下新闻提问：\n\n{item_context}"
                })
            elif rag_context:
                formatted_messages.append({
                    "role": "assistant",
                    "content": f"从报告中检索到的相关段落：\n\n{rag_context}"
                })

            if search_context:
                formatted_messages.append({
                    "role": "assistant",
                    "content": f"联网搜索补充资料：\n\n{search_context}"
                })

            for msg in messages:
                if 'role' in msg and 'content' in msg:
                    formatted_messages.append({"role": msg["role"], "content": msg["content"]})

            # 8. 调用 LLM
            ai_message, tool_calls_metadata = await self.process_chat_completion(formatted_messages)

            if not ai_message:
                logger.warning("No AI message content found in response, using fallback")
                ai_message = "抱歉，我没能生成回答，请换个方式提问。"

            logger.info(f"Generated response: {ai_message[:100]}..." if len(ai_message) > 100 else f"Generated response: {ai_message}")
            return ai_message, tool_calls_metadata

        except Exception as e:
            logger.error(f"Error in chat: {str(e)}", exc_info=True)
            raise

    _CN_NUM = {
        '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100, '千': 1000,
    }

    @classmethod
    def _chinese_to_int(cls, s: str) -> int:
        """将中文数字字符串（如 '十二', '三百二十五'）转为 int。"""
        if not s:
            return 0
        # 纯数字
        if s.isdigit():
            return int(s)
        # 十 开头（十一 ~ 十九）
        if s.startswith('十'):
            s = '一' + s
        total, section = 0, 0
        for ch in s:
            num = cls._CN_NUM.get(ch, 0)
            if num >= 10:
                if section == 0:
                    section = 1
                section *= num
                total += section
                section = 0
            else:
                section = section * 10 + num if section else num
        return total + section

    def _resolve_target_index(self, user_msg: str) -> Optional[int]:
        """解析用户指的是 hot_items 的第几条 → 返回 0-based index 或 None。"""
        import re
        if not self.hot_items:
            return None

        # 阿拉伯数字：第1个、第12条
        m = re.search(r'第\s*(\d+)\s*[个条位]?', user_msg)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(self.hot_items):
                return idx

        # 中文数字：第一条、第二位
        m = re.search(r'第\s*([零一二两三四五六七八九十百千]+)\s*[个条位]?', user_msg)
        if m:
            idx = self._chinese_to_int(m.group(1)) - 1
            if 0 <= idx < len(self.hot_items):
                return idx

        # 平台名：抖音那条、B站那个
        for i, item in enumerate(self.hot_items):
            platform = item.get("platform", "")
            if platform and platform in user_msg:
                return i

        # 标题关键词：用户消息里有标题的部分文本
        for i, item in enumerate(self.hot_items):
            title = item.get("title", "")
            if title and len(title) >= 4:
                # 取标题的任意连续4字，看是否出现在用户消息里
                for j in range(len(title) - 3):
                    if title[j:j+4] in user_msg:
                        return i

        return None

    def _resolve_target_title(self, user_msg: str) -> str:
        """根据用户消息和热榜索引表，解析用户指的是哪条热点 → 返回该条目标题。

        支持格式：
        - 阿拉伯数字：第1个、第12条、第3位
        - 中文数字：第十二条、第三个、第二位
        """
        import re

        # 匹配 "第N个/条/位"（阿拉伯数字）
        m = re.search(r'第\s*(\d+)\s*[个条位]?', user_msg)
        if m and self.hot_items:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(self.hot_items):
                return self.hot_items[idx].get("title", "")

        # 匹配 "第N个/条/位"（中文数字）
        m = re.search(r'第\s*([零一二两三四五六七八九十百千]+)\s*[个条位]?', user_msg)
        if m and self.hot_items:
            idx = self._chinese_to_int(m.group(1)) - 1
            if 0 <= idx < len(self.hot_items):
                return self.hot_items[idx].get("title", "")

        # 匹配 "XX平台那条/那个"
        for item in self.hot_items:
            platform = item.get("platform", "")
            if platform and platform in user_msg:
                return item.get("title", "")

        # 兜底：返回空，让 RAG 用用户原始消息检索
        return ""

    def get_context(self):
        """return the current context of the chat"""
        return self.report
