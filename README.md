# Trade-AI · A股智能选股

一个基于 [Baostock](https://baostock.com) 免费数据源的 A 股智能选股应用，计划提供 **Docker 一键部署 + 浏览器网页界面**：选择股票池与策略，一键运行选股，在网页上查看推荐股票榜并下载 Excel / Markdown 报告。

> 本项目基于并改编自开源项目 [striferxu/stock-picker-plus](https://github.com/striferxu/stock-picker-plus)（GPLv3）。

## 计划特性

- 🐳 **Docker 一键部署**：`docker compose up --build`
- 🌐 **网页界面**：浏览器打开 `http://localhost:8501` 使用
- 🎯 **多策略选股**：多因子 / 低PE价值 / 三维评分
- 📊 **报告输出**：Markdown + Excel（中文字段）
- 💾 报告自动保存到本地 `reports/` 目录

## ⚠️ 风险提示

本工具仅供学习研究使用，**不构成任何投资建议**。数据存在延迟，策略未经充分回测，投资决策请自行判断、风险自负。
