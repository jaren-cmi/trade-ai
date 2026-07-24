#!/usr/bin/env python3
"""
QQ推送模块（简化存根 - 默认禁用）

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class QQNotifier:
    """QQ通知器（默认关闭，不影响核心选股）"""

    def send(self, report_md: str, excel_path: str, stats: Optional[dict] = None) -> bool:
        logger.info("QQ推送功能在 Docker 版本中未启用（需配置 QQ 机器人）")
        return False
