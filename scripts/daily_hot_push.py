"""
每日热榜推送脚本 — 全部平台热搜汇总 + 交叉分析

格式:
=== 抖音热搜 TOP 50 ===
1. 标题 🔥热度
   相关平台新闻...

=== 今日头条热搜 TOP 50 ===
1. 标题
...

=== 澎湃新闻热搜 TOP 20 ===
...
"""
import io, os, re, sys, json, requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Windows terminal encoding fix
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from gpt_researcher.actions.notifiers import send_report_to_feishu

# 主平台放第一个，后面是辅助数据源
PLATFORMS = [
    ("douyin",     "抖音",       50, False),   # False = 视频为主, scraper 可能读不到
    ("toutiao",    "今日头条",   50, True),
    ("thepaper",   "澎湃新闻",   20, True),
    ("baidu",      "百度",       20, True),
    ("36kr",       "36氪",       30, True),
    ("sspai",      "少数派",     20, True),
    ("v2ex",       "V2EX",       20, True),
    ("juejin",     "掘金",       20, True),
    ("bilibili",   "B站",        30, False),   # False = 视频为主
]
BASE_URL = os.getenv("DAILY_HOT_API_BASE_URL", "https://dailyhotapi.vercel.app")

def get_proxy():
    proxies = {}
    for k in ("http", "https"):
        v = os.getenv(f"{k.upper()}_PROXY") or os.getenv(f"{k}_proxy")
        if v: proxies[k] = v
    return proxies

def fetch_hot(platform):
    try:
        resp = requests.get(f"{BASE_URL}/{platform}", timeout=15, proxies=get_proxy())
        data = resp.json()
        if data.get("code") == 200 or "data" in data:
            return data.get("data", [])
    except Exception as e:
        print(f"[WARN] {platform}: {e}")
    return []

def normalize(title):
    return re.sub(r'[^一-鿿]', '', title)

def max_overlap(a, b):
    best = 0
    for s in range(len(a)):
        for e in range(s+2, min(s+8, len(a)+1)):
            if a[s:e] in b:
                best = max(best, e-s)
    return best

def find_related(title, items, max_results=2):
    """宽松匹配: >=3个连续汉字重叠 即算相关"""
    norm = normalize(title)
    if len(norm) < 3: return []
    related = []
    for it in items:
        it_norm = normalize(it.get("title",""))
        if not it_norm: continue
        if max_overlap(norm, it_norm) >= 3:
            related.append(it)
        if len(related) >= max_results:
            break
    return related

def hot_str(hot):
    if not hot: return ""
    return f" 🔥{hot}"

def format_item(i, item, with_desc=False):
    t = item.get("title","")
    h = item.get("hot","")
    u = item.get("url", item.get("mobileUrl",""))
    lines = [f"{i}. {t}{hot_str(h)}"]
    if with_desc:
        desc = item.get("desc","")
        if desc: lines.append(f"   {desc[:100]}")
        if u: lines.append(f"   {u}")
    return "\n".join(lines)

def build_platform_messages(all_data):
    """构建每个平台的独立消息列表"""
    today = datetime.now().strftime("%Y年%m月%d日")
    total_items = sum(len(v) for v in all_data.values())
    now_time = datetime.now().strftime("%H:%M")

    messages = []

    # 总览消息
    summary_lines = [
        f"📊 今日全网热榜汇总 — {today}",
        f"共 {len(all_data)} 个平台, {total_items} 条热搜",
        f"推送时间: {now_time}",
        "",
        "各平台热搜将分条消息发送 👇"
    ]
    messages.append(("📊 今日热榜总览", "\n".join(summary_lines)))

    # 抖音: 主平台 + 交叉分析
    main_code, main_name, main_count = PLATFORMS[0]
    main_items = all_data.get(main_code, [])[:main_count]
    other_data = {pc: items for pc, items in all_data.items() if pc != main_code}

    dy_lines = [f"🔥 {main_name} 热搜 TOP {len(main_items)}", "="*30, ""]
    for i, item in enumerate(main_items, 1):
        title = item.get("title","")
        hot = item.get("hot","")
        url = item.get("url", item.get("mobileUrl",""))
        dy_lines.append(f"**{i}. {title}**{hot_str(hot)}")
        if url: dy_lines.append(f"链接: {url}")
        # 交叉平台分析
        cross_items = []
        for pc, pn, _, _ in PLATFORMS[1:]:
            for r in find_related(title, other_data.get(pc, []), max_results=2):
                rt = r.get("title","")
                rurl = r.get("url", r.get("mobileUrl",""))
                rhot = r.get("hot","")
                line = f"  - {pn}: {rt}"
                if rhot: line += f" (🔥{rhot})"
                if rurl: line += f" {rurl}"
                cross_items.append(line)
        if cross_items:
            dy_lines.extend(cross_items)
        dy_lines.append("")
    dy_lines.append(f"数据来源: 今日热榜API | {now_time}")
    messages.append((f"🔥 {main_name} TOP {len(main_items)}", "\n".join(dy_lines)))

    # 其他平台: 每个平台一条消息
    for code, name, count in PLATFORMS[1:]:
        items = all_data.get(code, [])[:count]
        if not items: continue

        lines = [f"📰 {name} 热搜 TOP {len(items)}", "="*30, ""]
        for i, item in enumerate(items, 1):
            t = item.get("title","")
            h = item.get("hot","")
            u = item.get("url", item.get("mobileUrl",""))
            lines.append(f"{i}. {t}{hot_str(h)}")
            if u: lines.append(f"   {u}")
            desc = item.get("desc","")
            if desc: lines.append(f"   {desc[:80]}")
            lines.append("")
        lines.append(f"数据来源: 今日热榜API | {now_time}")
        messages.append((f"📰 {name} TOP {len(items)}", "\n".join(lines)))

    return messages

def split_by_length(text, max_len=4000):
    """按行分割文本，每段不超过 max_len 字符"""
    lines = text.split("\n")
    chunks, cur = [], []
    cur_len = 0
    for line in lines:
        add_len = len(line) + 1
        if cur_len + add_len > max_len and cur:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = add_len
        else:
            cur.append(line)
            cur_len += add_len
    if cur:
        chunks.append("\n".join(cur))
    return chunks

def main():
    print("=== 每日热搜推送开始 ===")
    all_data = {}
    for code, name, count, _ in PLATFORMS:
        items = fetch_hot(code)
        all_data[code] = items[:count]
        print(f"  {name}: {len(items)} 条")
    
    print("组合报告...")
    messages = build_platform_messages(all_data)

    # 保存备份 (合并所有消息到一份文件)
    out = PROJECT_ROOT / "outputs"
    out.mkdir(exist_ok=True)
    ds = datetime.now().strftime("%Y%m%d_%H%M")
    all_content = "\n\n" + "="*60 + "\n\n".join(content for _, content in messages)
    with open(out / f"daily_hot_{ds}.md", "w", encoding="utf-8") as f:
        f.write(all_content)
    print(f"  已保存: outputs/daily_hot_{ds}.md")

    # 每个平台一条飞书消息, 超长则拆分
    ok_all = True
    msg_count = 0
    for platform_title, platform_content in messages:
        chunks = split_by_length(platform_content, max_len=4000)
        n = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            if n > 1:
                title = f"{platform_title} ({idx}/{n})"
            else:
                title = platform_title
            ok = send_report_to_feishu(report=chunk, task=title)
            msg_count += 1
            print(f"  {title}: {'OK' if ok else 'FAIL'}")
            if not ok: ok_all = False

    print(f"共发送 {msg_count} 条消息")
    print("✅ 全流程完成!" if ok_all else "❌ 部分推送失败")
    return ok_all

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
