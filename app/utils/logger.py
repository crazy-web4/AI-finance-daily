"""
结构化日志模块
提供结构化的日志输出，支持多种日志级别和格式
"""

import logging
import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import contextmanager


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StructuredLogger:
    """结构化日志记录器"""

    def __init__(self, name: str, log_dir: str = "logs") -> None:
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # 创建日志记录器
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # 清除现有处理器
        self.logger.handlers.clear()

        # 创建文件处理器
        self._setup_file_handler()

        # 创建控制台处理器（可选）
        if os.environ.get("LOG_TO_CONSOLE", "false").lower() == "true":
            self._setup_console_handler()

    def _setup_file_handler(self) -> None:
        """设置文件处理器"""
        log_file = self.log_dir / f"{self.name}.log"

        handler = logging.FileHandler(
            log_file,
            encoding='utf-8',
            mode='a'  # 追加模式
        )

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def _setup_console_handler(self) -> None:
        """设置控制台处理器"""
        handler = logging.StreamHandler()

        formatter = logging.Formatter(
            '%(levelname)s - %(name)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def log(self, level: LogLevel, message: str, **kwargs: Any) -> None:
        """记录结构化日志"""
        # 构造结构化数据
        structured_data = {
            'timestamp': datetime.now().isoformat(),
            'logger': self.name,
            'level': level.value,
            'message': message,
            **kwargs
        }

        # 转换为JSON字符串
        json_str = json.dumps(structured_data, ensure_ascii=False)

        # 记录日志
        if level == LogLevel.DEBUG:
            self.logger.debug(json_str)
        elif level == LogLevel.INFO:
            self.logger.info(json_str)
        elif level == LogLevel.WARNING:
            self.logger.warning(json_str)
        elif level == LogLevel.ERROR:
            self.logger.error(json_str)
        elif level == LogLevel.CRITICAL:
            self.logger.critical(json_str)

    def debug(self, message: str, **kwargs: Any) -> None:
        """DEBUG级别日志"""
        self.log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """INFO级别日志"""
        self.log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """WARNING级别日志"""
        self.log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """ERROR级别日志"""
        self.log(LogLevel.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        """CRITICAL级别日志"""
        self.log(LogLevel.CRITICAL, message, **kwargs)

    @contextmanager
    def operation(self, operation: str, **context):
        """操作上下文管理器"""
        start_time = datetime.now()
        self.info(f"开始操作: {operation}", **context)

        try:
            yield
            duration = (datetime.now() - start_time).total_seconds()
            self.info(f"操作完成: {operation}", duration=duration, **context)
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.error(f"操作失败: {operation}",
                      error=str(e),
                      duration=duration,
                      **context)
            raise

    def log_api_call(self, method: str, url: str, status_code: int,
                    duration: float, request_id: Optional[str] = None):
        """记录API调用"""
        self.info("API调用",
                  method=method,
                  url=url,
                  status_code=status_code,
                  duration=duration,
                  request_id=request_id)

    def log_llm_call(self, model: str, tokens_in: int, tokens_out: int,
                    duration: float, cost: Optional[float] = None):
        """记录LLM调用"""
        self.info("LLM调用",
                  model=model,
                  tokens_in=tokens_in,
                  tokens_out=tokens_out,
                  duration=duration,
                  cost=cost)


_LOGGER_CACHE: Dict[str, StructuredLogger] = {}


def get_logger(name: str, log_dir: Optional[str] = None) -> StructuredLogger:
    """获取或创建日志记录器。

    第三轮 T15: 单例缓存——原实现每次调用都 handlers.clear() 后新建
    FileHandler，旧句柄不 close（fd 泄漏隐患）；log_dir 默认接配置。
    """
    if log_dir is None:
        try:
            from app.config import get_config
            log_dir = get_config().log_dir
        except Exception:
            log_dir = "logs"
    key = f"{name}@{log_dir}"
    if key not in _LOGGER_CACHE:
        _LOGGER_CACHE[key] = StructuredLogger(name, log_dir)
    return _LOGGER_CACHE[key]


# 便捷的日志函数
def log_debug(message: str, logger_name: str = "app", **kwargs: Any) -> None:
    """DEBUG级别便捷函数"""
    logger = get_logger(logger_name)
    logger.debug(message, **kwargs)


def log_info(message: str, logger_name: str = "app", **kwargs: Any) -> None:
    """INFO级别便捷函数"""
    logger = get_logger(logger_name)
    logger.info(message, **kwargs)


def log_error(message: str, logger_name: str = "app", **kwargs: Any) -> None:
    """ERROR级别便捷函数"""
    logger = get_logger(logger_name)
    logger.error(message, **kwargs)
