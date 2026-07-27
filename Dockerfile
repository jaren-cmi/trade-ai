# =============================================================
# Dockerfile — A股智能选股 Trade-AI
# 基于并改编自 striferxu/stock-picker-plus（GPLv3）
#
# 构建命令（在仓库根目录）：
#   docker compose up --build
# =============================================================

FROM python:3.12-slim

# 替换为清华镜像源，加速 apt-get（兼容 Debian bookworm 及更早版本）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
            /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
            /etc/apt/sources.list; \
    fi

# 系统依赖：gcc（编译扩展）、中文轻量字体（Excel中文显示）
# fonts-noto-cjk 体积过大且常下载失败，仅保留轻量的 fonts-wqy-zenhei
# 字体安装非致命：若镜像源暂时不可用，构建仍可继续（Excel 仍可输出，仅字体退回默认）
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && { apt-get install -y --no-install-recommends fonts-wqy-zenhei \
         || echo "WARNING: fonts-wqy-zenhei install failed, continuing without CJK font"; } \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 先复制依赖文件，充分利用 Docker 层缓存
COPY requirements.txt .

# 使用清华 pip 镜像加速安装
RUN pip install --no-cache-dir \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
        -r requirements.txt

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
