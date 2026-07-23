# =============================================================
# Dockerfile — A股智能选股 Trade-AI
# 基于并改编自 striferxu/stock-picker-plus（GPLv3）
#
# 构建命令（在仓库根目录）：
#   docker compose up --build
# =============================================================

FROM python:3.12-slim

# 系统依赖 + 中文字体（用于 Excel 报告中文显示）
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-wqy-zenhei \
        fonts-noto-cjk \
        gcc \
        && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 先复制依赖文件，充分利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录（挂载点）
RUN mkdir -p data/cache reports/daily

# 暴露 Streamlit 端口
EXPOSE 8501

# Streamlit 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# 启动命令
CMD ["streamlit", "run", "web/app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
