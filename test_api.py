#!/usr/bin/env python3
"""测试热榜 API 全链路中文化。"""
import json
import urllib.request
import urllib.error
import sys
import io

# 强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def post(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"http://localhost:8000{path}",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")

def get(path):
    req = urllib.request.Request(f"http://localhost:8000{path}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode("utf-8")

# 1. 平台列表
print("===== /api/hot/platforms =====")
status, body = get("/api/hot/platforms")
data = json.loads(body)
for p in data["platforms"]:
    print(f"  {p['code']:12s} {p['name']:8s} readable={p['readable']}")

# 2. 热榜状态
print("\n===== /api/hot/status =====")
status, body = get("/api/hot/status")
data = json.loads(body)
print(f"  定时任务运行中: {data['running']}")
for j in data.get("jobs", []):
    print(f"  {j['id']:10s} {j['name']}  → 下次: {j['next_run']}")

# 3. Agent 问答
print("\n===== /api/hot/ask (问题: 给我看看抖音现在有什么热点) =====")
status, body = post("/api/hot/ask", {"question": "给我看看抖音现在有什么热点"})
print(f"  状态: {status}")
data = json.loads(body)
report = data.get("report", "")
pushed = data.get("pushed")
print(f"  是否推送到飞书: {pushed}")
print(f"  报告长度: {len(report)} 字符")
print(f"  报告前 600 字:\n{report[:600]}")
