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

    def _setup_rag(self):
        """对报告切片 + 生成嵌入向量，存入内存供检索。"""
        if not self.report or len(self.report.strip()) < 50:
            return

        # 1. 切片：按 Markdown 标题优先，其次固定长度
        try:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=800,
                chunk_overlap=80,
                separators=["\n## ", "\n### ", "\n\n", "\n", "。", "，", " "],
            )
        except TypeError:
            # 旧版 langchain 不支持 separators
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=800,
                chunk_overlap=80,
            )
        self._chunks = text_splitter.split_text(self.report)
        if not self._chunks:
            return

        # 2. 嵌入：使用 huggingface sentence-transformers（本地模型，无需 API key）
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
            model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            self._embed_fn = HuggingFaceEmbeddings(model_name=model_name)
            vectors = self._embed_fn.embed_documents(self._chunks)
            self._embeddings = np.array(vectors, dtype=np.float32)
            logger.info(f"RAG: 报告切成 {len(self._chunks)} 块，嵌入维度 {self._embeddings.shape[1]}")
        except Exception as e:
            logger.warning(f"RAG 嵌入初始化失败（将跳过 RAG，仅用索引表）: {e}")
            self._embed_fn = None
            self._embeddings = None

    def retrieve(self, query: str, top_k: int = 4) -> str:
        """对查询做语义检索，返回最相关的几段原文拼接。"""
        if not self._embed_fn or self._embeddings is None or not self._chunks:
            return ""
        try:
            q_vec = np.array(self._embed_fn.embed_query(query), dtype=np.float32)
            # 余弦相似度
            norms = np.linalg.norm(self._embeddings, axis=1) * np.linalg.norm(q_vec)
            norms = np.where(norms == 0, 1e-9, norms)
            sims = self._embeddings.dot(q_vec) / norms
            top_idx = np.argsort(sims)[-top_k:][::-1]
            selected = [self._chunks[i] for i in top_idx if sims[i] > 0.1]
            if not selected:
                return ""
            return "\n\n---\n\n".join(selected)
        except Exception as e:
            logger.error(f"RAG 检索失败: {e}")
            return ""

    def quick_search(self, query):
        """Perform a web search for current information using DuckDuckGo"""
        try:
            logger.info(f"Performing DuckDuckGo search for: {query}")
            from ddgs import DDGS
            raw = list(DDGS().text(query, region='cn-zh', max_results=5))
            results = {
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "content": r.get("body", ""),
                    }
                    for r in raw
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
                    for r in raw
                ],
            }
            return results
        except Exception as e:
            logger.error(f"Error performing DuckDuckGo search: {str(e)}", exc_info=True)
            return {"error": str(e), "results": []}


    async def process_chat_completion(self, messages: List[Dict[str, str]]):
        """Process chat completion using configured LLM provider with tool calling support"""
        # Create a search tool using the utility function
        search_tool = create_search_tool(self.quick_search)
        
        # Use the tool-enabled chat completion utility
        response, tool_calls_metadata = await create_chat_completion_with_tools(
            messages=messages,
            tools=[search_tool],
            model=self.config.smart_llm_model,
            llm_provider=self.config.smart_llm_provider,
            llm_kwargs=self.config.llm_kwargs,
        )
        
        # Process metadata to match the expected format for the chat system
        processed_metadata = []
        for metadata in tool_calls_metadata:
            if metadata.get("tool") == "search_tool":
                # Extract query from args
                query = metadata.get("args", {}).get("query", "")
                
                # Trigger search again to get metadata (the search was already executed by LangChain)
                if query:
                    self.quick_search(query)  # This populates self.search_metadata
                    
                processed_metadata.append({
                    "tool": "quick_search",
                    "query": query,
                    "search_metadata": self.search_metadata
                })
        
        return response, processed_metadata


    async def chat(self, messages, websocket=None):
        """Chat with configured LLM provider. 使用 RAG 按需检索报告片段，
        不再把完整报告塞进 system prompt。"""
        try:
            # 1. 取出最新一条用户消息，用于 RAG 检索
            latest_user_msg = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    latest_user_msg = msg.get("content", "")
                    break

            # 2. RAG：根据用户问题检索报告相关片段
            retrieved_context = self.retrieve(latest_user_msg, top_k=4) if latest_user_msg else ""

            # 3. 系统提示不再包含完整报告，只保留角色定义 + 索引表 + 输出指引
            system_parts = [
                "You are GPT Researcher, an autonomous research agent. ",
                "This is a chat about a research report. Answer based on the given context and report.",
                "",
                "You may use the quick_search tool when the user asks about information",
                "that might require current data not found in the report.",
                "",
                "You must respond in markdown format, readable with paragraphs, tables, etc.",
                f"Assume the current time is: {datetime.now()}.",
            ]
            # 热榜索引（如果有）
            hot_prompt = self._hot_items_prompt()
            if hot_prompt:
                system_parts.append(hot_prompt)

            system_prompt = "\n".join(system_parts)

            # 4. 组装消息：system +（检索到的上下文作为 assistant 前缀）+ 消息历史
            formatted_messages = [
                {"role": "system", "content": system_prompt}
            ]

            # 把 RAG 检索到的片段作为一条 tool_result 注入到消息历史最前面
            # 这样 LLM 看到的不是全量报告，而是与当前问题相关的片段
            if retrieved_context:
                formatted_messages.append({
                    "role": "assistant",
                    "content": (
                        "我已经从完整报告中检索到了以下与问题相关的段落，"
                        "你可以基于这些内容回答。如果信息不足，可以调用 quick_search 联网搜索。\n\n"
                        f"{retrieved_context}"
                    )
                })

            # 原始消息历史
            for msg in messages:
                if 'role' in msg and 'content' in msg:
                    formatted_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
                else:
                    logger.warning(f"Skipping message with missing role or content: {msg}")

            # 5. 调用 LLM
            ai_message, tool_calls_metadata = await self.process_chat_completion(formatted_messages)

            if not ai_message:
                logger.warning("No AI message content found in response, using fallback")
                ai_message = "抱歉，我没能生成回答，请换个方式提问。"

            logger.info(f"Generated response: {ai_message[:100]}..." if len(ai_message) > 100 else f"Generated response: {ai_message}")
            return ai_message, tool_calls_metadata

        except Exception as e:
            logger.error(f"Error in chat: {str(e)}", exc_info=True)
            raise

    def get_context(self):
        """return the current context of the chat"""
        return self.report
