FROM python:3.11-slim-bookworm

WORKDIR /app

# ── 系统依赖（爬虫 + PDF 中文字体 ────────────────────────────
# 网络不稳定时自动重试，最多 3 次
RUN for i in 1 2 3; do \
        apt-get update && \
        apt-get install -y --fix-missing --no-install-recommends \
            build-essential gcc g++ make \
            pandoc wkhtmltopdf \
            fonts-wqy-zenhei fonts-arphic-ukai && \
        rm -rf /var/lib/apt/lists/* && \
        break || { echo "apt attempt $i failed, retrying in 5s..."; sleep 5; }; \
    done

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
