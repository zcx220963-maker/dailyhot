"""HotListReport 单元测试 - 直接调用类生成报告。"""
import asyncio
import sys
import logging
from pathlib import Path

# 把 backend/ 和 项目根 加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent / "backend"
_PROJ_ROOT = Path(__file__).resolve().parent
for p in (_BACKEND_DIR, _PROJ_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")

from hot_research.daily_hot_api import (
    PLATFORMS,
    PLATFORM_NAME_MAP,
    detect_platforms_in_query,
    fetch_hot,
    find_related,
)
from backend.report_type.hot_list_report.hot_list_report import HotListReport


class FakeWebSocket:
    """模拟 WebSocket，收集推送消息。"""
    def __init__(self):
        self.messages = []

    async def send_json(self, data):
        self.messages.append(data)
        t = data.get("type", "")
        output = data.get("output", "")
        if t == "logs":
            print(f"  {output}")


async def main():
    # ---- 测试多平台组合 ----
    test_queries = [
        "生成今日B站热搜报告",           # 单平台主干
        "B站+抖音今日热榜",               # 双平台主干
        "今日热榜",                       # 全平台主干
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"  测试查询: {query}")
        print(f"{'='*60}\n")

        # 1. 动态检测主干平台
        primary_codes = detect_platforms_in_query(query)
        if not primary_codes:
            primary_codes = [p[0] for p in PLATFORMS]
        primary_names = [PLATFORM_NAME_MAP[c] for c in primary_codes]
        supp_names = [PLATFORM_NAME_MAP[p[0]] for p in PLATFORMS if p[0] not in primary_codes]
        print(f"  主干: {primary_names}")
        print(f"  辅助: {supp_names if supp_names else '无（全是主干）'}")

        # 2. 抓取全部9平台数据
        all_raw = {}
        for code, name, default_n, _ in PLATFORMS:
            all_raw[code] = fetch_hot(code, default_n)

        supp_codes = [p[0] for p in PLATFORMS if p[0] not in primary_codes]
        total_main = sum(len(all_raw.get(c, [])) for c in primary_codes)
        total_supp = sum(len(all_raw.get(c, [])) for c in supp_codes)
        print(f"  主干共 {total_main} 条，辅助 {total_supp} 条")

        # 3. 执行报告（每个主干平台仅前5条，快速验证）
        limited_raw = {}
        for code, items in all_raw.items():
            limited_raw[code] = items[:5] if code in primary_codes else items

        fake_ws = FakeWebSocket()
        researcher = HotListReport(
            query=query,
            all_raw_data=limited_raw,
            primary_codes=primary_codes,
            websocket=fake_ws,
            tone=None,
            config_path="default",
            max_text_items=5,
        )

        print(f"\n  开始分析...")
        report = await researcher.run()

        # 4. 输出结果
        print(f"\n  报告长度: {len(report)} 字符")
        print(f"\n{'─'*60}")
        print(report)
        print(f"{'─'*60}")

        # 保存
        safe_name = query.replace("+", "_").replace(" ", "_")[:20]
        out_path = Path("outputs") / f"report_{safe_name}.md"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\n  已保存: {out_path}")


asyncio.run(main())
