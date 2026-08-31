"""
统一配置管理模块
支持动态配置加载和热更新
"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List
import threading
import time
from app.utils.logger import get_logger
from app.utils.exceptions import AppError, ErrorType


@dataclass
class CacheConfig:
    """缓存配置"""
    enabled: bool = True
    max_memory_items: int = 1000
    disk_ttl_hours: int = 24
    compression: bool = True


@dataclass
class ConcurrencyConfig:
    """并发配置"""
    collector_max_workers: int = 5
    analyzer_max_workers: int = 3
    extract_max_workers: int = 4
    semaphore_limit: int = 10


@dataclass
class MonitoringConfig:
    """监控配置"""
    enabled: bool = True
    log_level: str = "INFO"
    metrics_retention_days: int = 30
    performance_report_interval: int = 3600  # 1小时


@dataclass
class LLMConfig:
    """LLM配置"""
    model: str = "doubao-pro-128k-240515"
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.3
    max_retries: int = 2
    base_delay: float = 1.0
    batch_size: int = 5


@dataclass
class AppConfig:
    """应用主配置"""
    cache: CacheConfig = field(default_factory=CacheConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    search: Dict[str, Any] = field(default_factory=dict)

    # 基础配置
    timezone: str = "Asia/Shanghai"
    data_dir: str = "data"
    log_dir: str = "logs"

    # 环境标识
    environment: str = "development"

    @classmethod
    def load_from_file(cls, filepath: str) -> 'AppConfig':
        """从文件加载配置"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            # 递归构建配置对象
            config = cls()

            # 更新各个配置段
            if 'cache' in config_data:
                config.cache = CacheConfig(**config_data['cache'])
            if 'concurrency' in config_data:
                config.concurrency = ConcurrencyConfig(**config_data['concurrency'])
            if 'monitoring' in config_data:
                config.monitoring = MonitoringConfig(**config_data['monitoring'])
            if 'llm' in config_data:
                config.llm = LLMConfig(**config_data['llm'])

            # 搜索配置保持原结构
            if 'search' in config_data:
                config.search = config_data['search']

            # 其他配置
            for key, value in config_data.items():
                if key not in ['cache', 'concurrency', 'monitoring', 'llm', 'search']:
                    setattr(config, key, value)

            # 从环境变量读取敏感配置
            cls._load_from_env(config)

            return config

        except Exception as e:
            raise AppError(
                ErrorType.CONFIGURATION_ERROR,
                f"Failed to load config from {filepath}: {str(e)}",
                filepath=filepath
            )

    @classmethod
    def _load_from_env(cls, config: 'AppConfig'):
        """从环境变量加载配置"""
        # LLM配置
        if not config.llm.api_key:
            config.llm.api_key = os.getenv('ARK_API_KEY') or os.getenv('OPENAI_API_KEY', '')

        if not config.llm.base_url:
            config.llm.base_url = os.getenv('ARK_BASE_URL') or os.getenv('OPENAI_BASE_URL', '')

        # 基础配置
        config.timezone = os.getenv('REPORT_TIMEZONE', config.timezone)
        config.environment = os.getenv('ENVIRONMENT', config.environment)
        config.log_dir = os.getenv('LOG_DIR', config.log_dir)

        # 确保必要的API密钥存在
        if not config.llm.api_key:
            raise AppError(
                ErrorType.CONFIGURATION_ERROR,
                "LLM API key not configured. Set ARK_API_KEY or OPENAI_API_KEY"
            )


class ConfigWatcher:
    """配置文件监视器"""

    def __init__(self, config_path: str, on_reload=None):
        self.config_path = Path(config_path)
        self.config = AppConfig.load_from_file(config_path)
        self.last_modified = self.config_path.stat().st_mtime
        self.on_reload = on_reload
        self.logger = get_logger("config_watcher")
        self._running = False
        self._watch_thread = None

    def start(self):
        """启动配置监视"""
        if self._running:
            return

        self._running = True
        self._watch_thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()
        self.logger.info("Configuration watcher started")

    def stop(self):
        """停止配置监视"""
        self._running = False
        if self._watch_thread:
            self._watch_thread.join()
        self.logger.info("Configuration watcher stopped")

    def _watch_loop(self):
        """监视循环"""
        while self._running:
            try:
                current_modified = self.config_path.stat().st_mtime
                if current_modified != self.last_modified:
                    self.last_modified = current_modified
                    self._reload_config()

                time.sleep(1)  # 每秒检查一次

            except Exception as e:
                self.logger.error(f"Error watching config: {str(e)}")
                time.sleep(5)  # 出错时延长等待时间

    def _reload_config(self):
        """重新加载配置"""
        try:
            old_config = self.config
            self.config = AppConfig.load_from_file(str(self.config_path))

            self.logger.info("Configuration reloaded")
            self.logger.debug("Changes detected:",
                            diff=self._get_config_changes(old_config, self.config))

            if self.on_reload:
                self.on_reload(old_config, self.config)

        except Exception as e:
            self.logger.error(f"Failed to reload config: {str(e)}")
            self.config = old_config  # 回滚到旧配置

    def _get_config_changes(self, old_config: AppConfig, new_config: AppConfig) -> Dict[str, Any]:
        """获取配置变化"""
        changes = {}

        # 比较配置段
        for section_name, old_section in old_config.__dict__.items():
            new_section = getattr(new_config, section_name)

            if old_section != new_section:
                changes[section_name] = {
                    'old': old_section,
                    'new': new_section
                }

        return changes

    def get(self) -> AppConfig:
        """获取当前配置"""
        return self.config


# 全局配置实例
_global_config: Optional[AppConfig] = None
_config_watcher: Optional[ConfigWatcher] = None
_config_lock = threading.Lock()


def init_config(config_path: str, watch: bool = True) -> AppConfig:
    """初始化配置"""
    global _global_config, _config_watcher

    with _config_lock:
        if _global_config is None:
            _global_config = AppConfig.load_from_file(config_path)

            if watch:
                _config_watcher = ConfigWatcher(config_path, _on_config_reload)
                _config_watcher.start()

            # 创建必要的目录
            Path(_global_config.data_dir).mkdir(exist_ok=True)
            Path(_global_config.log_dir).mkdir(exist_ok=True)

    return _global_config


def get_config() -> AppConfig:
    """获取全局配置。

    若主入口尚未调用 init_config()（例如单元测试、单独使用工具模块时），
    惰性返回一份内置默认配置，避免 cache / concurrency / monitoring 等
    无密钥依赖的工具模块因为「未初始化」直接崩溃。
    需要真实 API key 的链路（LLMClient）从环境变量读取，不走这里。
    """
    global _global_config
    if _global_config is None:
        with _config_lock:
            if _global_config is None:
                _global_config = AppConfig()
    return _global_config


def _on_config_reload(old_config: AppConfig, new_config: AppConfig):
    """配置重载回调"""
    global _global_config
    _global_config = new_config

    # 记录配置变化
    logger = get_logger("config")
    logger.info("Configuration reloaded in running process")


# 便捷函数
def get_cache_config() -> CacheConfig:
    """获取缓存配置"""
    return get_config().cache


def get_concurrency_config() -> ConcurrencyConfig:
    """获取并发配置"""
    return get_config().concurrency


def get_llm_config() -> LLMConfig:
    """获取LLM配置"""
    return get_config().llm
