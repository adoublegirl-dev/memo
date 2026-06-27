"""日志工具 —— 统一输出格式。"""

import logging
import sys

from memo.core.config import config


def setup_logger(name: str = "memo") -> logging.Logger:
    """创建并返回配置好的 logger。"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)-5s %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return logger


# 默认 logger
logger = setup_logger()
