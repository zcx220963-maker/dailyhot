FROM python:3.11-slim-bookworm

WORKDIR /app

# ── 系统依赖（爬虫 + PDF 中文字体 ────────────────────────────
# 网络不稳定时自动重试，最多 3 次
# 两次 apt-get：先装基础工具，再单独装字体（字体包在 slim 镜像里常缺 recommends）
RUN for i in 1 2 3; do \
        apt-get update && \
        apt-get install -y --no-install-recommends \
            build-essential gcc g++ make \
            pandoc wkhtmltopdf && \
        rm -rf /var/lib/apt/lists/* && \
        break || { echo "apt attempt $i failed, retrying in 5s..."; sleep 5; }; \
    done

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
 || echo "[warn] fonts install skipped (non-fatal)" \
 && rm -rf /var/lib/apt/lists/* || true

# ── Python 依赖 ───────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/requirements.txt ./backend-requirements.txt
RUN pip install --no-cache-dir -r backend-requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .

# ── 环境变量 ─────────────────────────────────────────────────
ENV FAST_LLM=openai:LongCat-2.0
ENV SMART_LLM=openai:LongCat-2.0
ENV RETRIEVER=duckduckgo
ENV TONE=Objective
ENV WORKERS=1

EXPOSE 8001

CMD ["python", "backend/run_server.py"]
