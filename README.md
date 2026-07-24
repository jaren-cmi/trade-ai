# Trade-AI · A股智能选股

基于 [Baostock](https://baostock.com) 免费数据源的 A 股智能选股应用。
**Docker 一键部署，浏览器直接使用**：选择股票池与策略，点击开始，在网页上看到推荐股票榜并下载 Excel / Markdown 报告。

> 本项目基于并改编自开源项目 [striferxu/stock-picker-plus](https://github.com/striferxu/stock-picker-plus)（GPLv3），致谢原作者 Simon。

## 主要特性

- 🐳 **Docker 一键部署**：`docker compose up --build`，无需本机安装 Python
- 🌐 **中文网页界面**：浏览器打开 `http://localhost:8501` 即可使用
- 🎯 **多策略选股**：多因子 / 低PE价值 / 三维评分（基本面+技术面+情绪面）
- ⚡ **快速模式**：采样约 20-60 秒出结果；全市场扫描约 15-20 分钟
- 📊 **双重报告**：Markdown 摘要 + Excel 详细数据（含中文字段）
- 💾 **报告本地保存**：自动写入宿主机 `reports/` 目录，容器重建不丢失
- 🔓 **免费数据源**：Baostock 免费无需注册/API Key，容器内联网即可用

---

## 🚀 快速开始（Windows + Docker Desktop）

### 前提条件

- 安装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)（确保已启动）
- Git 克隆本仓库（或下载 ZIP 解压）

### 一键启动

```powershell
# 在 PowerShell 中，切换到仓库目录
cd D:\trade-ai

# 首次运行（构建镜像，约 2-5 分钟）
docker compose up --build

# 后续启动（镜像已构建，直接启动）
docker compose up
```

启动成功后，终端会显示类似：

```
You can now view your Streamlit app in your browser.
URL: http://0.0.0.0:8501
```

### 打开网页

浏览器访问：**http://localhost:8501**

即可看到中文选股界面。

### 使用步骤

1. 在左侧边栏选择**股票池**（建议先选「沪深300」或「全A股」）
2. 选择**选股策略**（推荐「多因子策略」）
3. 选择**运行模式**（「快速采样」约 20-60 秒，适合先试用）
4. 点击 **「🔍 开始选股」**
5. 等待进度完成后，页面展示**推荐股票榜**
6. 点击「📊 下载 Excel 报告」或「📝 下载 Markdown 报告」

> Excel 报告也会自动保存到宿主机 `./reports/daily/` 目录，可直接用 Excel 打开。

### 停止服务

```powershell
# 停止（保留数据）
docker compose down

# 停止并清除（慎用，不影响 ./reports 和 ./data 目录）
docker compose down --volumes
```

---

## ⚙️ 可选配置

项目提供 `.env.example` 作为环境变量参考：

```powershell
# 复制示例文件（Windows）
copy .env.example .env

# 可选：填入 Tavily API Key（用于三维评分策略情绪分析面）
# 留空则情绪分析维度使用中性分，不影响核心选股
```

---

## 📁 项目结构

```
trade-ai/
├── core/                   # 核心选股引擎
│   ├── engine.py           # 主引擎（协调全流程）
│   ├── data_fetcher.py     # Baostock 数据获取
│   ├── scorer.py           # 三维评分算法
│   ├── strategies.py       # 多因子/PE/三维评分策略
│   ├── indicators.py       # 技术指标（ta 库）
│   └── cache_manager.py    # 数据缓存管理
│
├── config/                 # 配置文件（YAML）
│   ├── strategies.yaml     # 策略参数
│   ├── pools.yaml          # 股票池配置
│   ├── data_sources.yaml   # 数据源配置
│   └── scoring_weights.yaml
│
├── output/                 # 输出模块
│   ├── reporter.py         # Markdown 报告生成
│   └── excel_writer.py     # Excel 导出
│
├── web/
│   └── app.py              # Streamlit 网页界面
│
├── reports/                # 报告输出（挂载到宿主机）
├── data/                   # 缓存数据（挂载到宿主机）
│
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .dockerignore
```

---

## 🐍 本地开发（不使用 Docker）

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate   # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动 Streamlit
streamlit run web/app.py
```

---

## ⚠️ 免责声明

**本工具仅供学习研究，不构成任何投资建议。**

- 数据来自 Baostock，存在 T+1 延迟
- 策略未经充分回测，历史表现不代表未来
- 投资决策请自行判断、**风险自负**

---

## 📄 开源许可与致谢

本项目基于 **GNU General Public License v3.0（GPLv3）** 授权发布。

致谢：
- **[striferxu/stock-picker-plus](https://github.com/striferxu/stock-picker-plus)**（GPLv3）：本项目的核心选股逻辑来源
- **[Baostock](https://baostock.com)**：免费稳定的 A 股数据源
