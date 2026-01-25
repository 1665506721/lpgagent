"""日志初始化。"""

import logging

from .config import settings


def init_logging() -> None:
    """初始化标准日志输出格式。"""

    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
