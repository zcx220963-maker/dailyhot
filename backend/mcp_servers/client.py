"""轻量 MCP 客户端（stdio 传输）。

用法:
    async with MCPStdioClient("python", "backend/mcp_servers/hot_list_server.py") as client:
        tools = await client.list_tools()
        result = await client.call_tool("get_douyin_hot", {"limit": 10})
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MCPStdioClient:
    """通过 stdio 与 MCP 服务器通信的异步客户端。"""

    def __init__(self, *cmd: str, env: Optional[dict] = None):
        self._cmd = cmd
        self._env = env
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._id = 0
        self._tools: list[dict] = []

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self):
        """启动 MCP 子进程并完成握手。"""
        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        # 增大读取缓冲区限制（默认 64KB 对大块热榜数据不够）
        if hasattr(self._proc.stdout, "_limit"):
            self._proc.stdout._limit = 2**23  # 8MB
        if hasattr(self._proc.stderr, "_limit"):
            self._proc.stderr._limit = 2**23  # 8MB

        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "gpt-researcher-hotlist", "version": "0.1"},
        })
        # Send initialized notification
        self._proc.stdin.write(
            (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized",
                          "params": {}}) + "\n").encode()
        )
        await self._proc.stdin.drain()
        # Small delay to let server process notification
        await asyncio.sleep(0.2)
        logger.info(f"MCP 客户端已连接: {' '.join(self._cmd)}")

    async def close(self):
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                pass

    async def _rpc(self, method: str, params: Optional[dict] = None) -> dict:
        """发送 JSON-RPC 请求并等待对应 id 的响应。

        使用 read() + 手动解析来避免 readline() 的 64KB 行大小限制。
        """
        self._id += 1
        req_id = self._id
        req = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            req["params"] = params
        raw = (json.dumps(req) + "\n").encode()
        self._proc.stdin.write(raw)
        await self._proc.stdin.drain()

        # 累积缓冲区，逐行解析 JSON-RPC 响应
        buffer = b""
        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._proc.stdout.read(65536),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"MCP request timed out: {method}")
            if not chunk:
                # EOF – check stderr for clues
                err = self._proc.stderr._buffer.decode(errors="replace") if hasattr(self._proc.stderr, "_buffer") else ""
                raise EOFError(f"MCP server closed stdout (method={method}). stderr: {err[:500]}")
            buffer += chunk
            # Try to find a complete JSON line in the buffer
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line_str = line.decode(errors="replace").strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                except json.JSONDecodeError:
                    # 非 JSON 行（如日志），跳过
                    continue
                if obj.get("id") == req_id:
                    if "error" in obj:
                        raise RuntimeError(f"MCP error: {obj['error']}")
                    return obj.get("result", {})

    async def list_tools(self) -> list[dict]:
        """获取服务器所有可用工具。"""
        result = await self._rpc("tools/list")
        self._tools = result.get("tools", [])
        return self._tools

    async def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        """调用指定工具并返回解析后的结果。"""
        result = await self._rpc("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        # Extract content from MCP response format
        content_list = result.get("content", [])
        if content_list:
            text = content_list[0].get("text", "")
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        return result

    async def collect_hot_data(self, tool_names: list[str], limit: int = 30) -> dict[str, list]:
        """批量调用指定的热榜工具，返回 {平台代码: [items]}。"""
        all_data: dict[str, list] = {}
        for tool_name in tool_names:
            try:
                result = await self.call_tool(tool_name, {"limit": limit})
                if isinstance(result, dict) and "items" in result:
                    code = result.get("code", tool_name.replace("get_", "").replace("_hot", ""))
                    all_data[code] = result["items"]
                    logger.info(f"  MCP {tool_name}: {len(result['items'])} 条")
                elif isinstance(result, dict) and "error" in result:
                    logger.warning(f"  MCP {tool_name} 错误: {result['error']}")
            except Exception as e:
                logger.warning(f"  MCP {tool_name} 调用失败: {e}")
        return all_data


async def _test():
    async with MCPStdioClient(sys.executable, "backend/mcp_servers/hot_list_server.py") as c:
        tools = await c.list_tools()
        print(f"可用 tools ({len(tools)}):")
        for t in tools[:3]:
            print(f"  - {t['name']}: {t['description']}")
        print("\n调用 get_douyin_hot:")
        r = await c.call_tool("get_douyin_hot", {"limit": 3})
        if isinstance(r, dict):
            print(f"  平台: {r.get('platform')}, 条数: {r.get('count')}")
            for it in r.get("items", [])[:3]:
                print(f"    - {it.get('title', '')[:30]}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_test())
