import asyncio
import json
import io
import sys

if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import websockets


async def test():
    uri = "ws://127.0.0.1:8001/ws"
    async with websockets.connect(uri) as ws:
        msg = json.dumps({
            "task": "生成今日B站热搜报告",
            "report_type": "research_report",
            "report_source": "web_search",
            "tone": "Objective",
            "query_domains": [],
            "mcp_enabled": False,
            "mcp_strategy": "fast",
            "mcp_configs": []
        })
        await ws.send(f"start {msg}")
        print("[OK] 已发送请求: 生成今日B站热搜报告")

        log_count = 0
        try:
            while True:
                resp = await asyncio.wait_for(ws.recv(), timeout=180)
                data = json.loads(resp)
                t = data.get("type", "")
                output = data.get("output", "")

                if t == "logs":
                    log_count += 1
                    if log_count <= 8 or "分析" in output or "已完成" in output:
                        print(f"[log] {output[:120]}")
                elif t == "report_complete":
                    print(f"\n[DONE] report_complete, length={len(output)}")
                    print("=== 报告前800字 ===")
                    print(output[:800])
                    print("=== 报告末尾400字 ===")
                    print(output[-400:])
                    break
                elif t == "error":
                    print(f"[ERROR] {output}")
                    break
        except asyncio.TimeoutError:
            print(f"[TIMEOUT] 已收到 {log_count} 条日志")


asyncio.run(test())
