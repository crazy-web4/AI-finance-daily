"""
智能缓存模块
支持内存缓存和文件缓存，带有LRU策略和压缩功能
"""

import pickle
import hashlib
import json
import gzip
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Dict, List
from functools import lru_cache
from threading import RLock
import threading

from app.config import get_cache_config
from app.utils.logger import get_logger


class SmartCache:
    """智能缓存系统"""

    def __init__(self, cache_dir: str = "data/cache") -> None:
        self.config = get_cache_config()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存
        self._memory_cache: Dict[str, Any] = {}
        self._access_times: Dict[str, float] = {}
        # 每条目绝对过期时间（epoch 秒），仅对设置了 TTL 的条目
        self._expiry: Dict[str, float] = {}
        self._lock = RLock()

        # 文件缓存
        self._file_cache_dir = self.cache_dir / "file_cache"
        self._file_cache_dir.mkdir(exist_ok=True)

        # 统计
        self.hits = 0
        self.misses = 0

        logger = get_logger("cache")
        logger.info("缓存系统初始化",
                  max_memory_items=self.config.max_memory_items,
                  disk_ttl_hours=self.config.disk_ttl_hours)

    def _get_cache_key(self, key: str) -> str:
        """生成缓存键"""
        return hashlib.md5(key.encode()).hexdigest()

    def _get_file_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self._file_cache_dir / f"{cache_key}.pkl.gz"

    def _cleanup_memory_cache(self) -> None:
        """清理内存缓存（LRU策略）"""
        with self._lock:
            if len(self._memory_cache) >= self.config.max_memory_items:
                # 删除最久未使用的
                oldest_key = min(self._access_times.items(), key=lambda x: x[1])[0]
                del self._memory_cache[oldest_key]
                del self._access_times[oldest_key]
                self._expiry.pop(oldest_key, None)

    def _cleanup_file_cache(self) -> None:
        """清理过期文件缓存"""
        if self.config.disk_ttl_hours <= 0:
            return

        cutoff_time = datetime.now() - timedelta(hours=self.config.disk_ttl_hours)
        deleted_count = 0

        for cache_file in self._file_cache_dir.glob("*.pkl.gz"):
            if cache_file.stat().st_mtime < cutoff_time.timestamp():
                try:
                    cache_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger = get_logger("cache")
                    logger.warning(f"删除缓存文件失败: {cache_file}", error=str(e))

        if deleted_count > 0:
            logger = get_logger("cache")
            logger.info(f"清理过期文件缓存: {deleted_count} 个文件")

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        # 1. 检查内存缓存
        with self._lock:
            if key in self._memory_cache:
                # 条目级 TTL：已过期则当作未命中并清理
                exp = self._expiry.get(key)
                if exp is not None and time.time() >= exp:
                    self._memory_cache.pop(key, None)
                    self._access_times.pop(key, None)
                    self._expiry.pop(key, None)
                    self.misses += 1
                    stale_file = self._get_file_path(self._get_cache_key(key))
                    try:
                        stale_file.unlink()
                    except OSError:
                        pass
                    return None
                # 更新访问时间
                self._access_times[key] = time.time()
                self.hits += 1
                return self._memory_cache[key]

        # 2. 检查文件缓存
        cache_key = self._get_cache_key(key)
        cache_file = self._get_file_path(cache_key)

        if cache_file.exists():
            try:
                with self._lock:
                    with gzip.open(cache_file, 'rb') as f:
                        cache_data = pickle.load(f)

                    # 检查是否过期：优先用条目级 TTL（秒），否则回退到全局磁盘 TTL（小时）
                    expired = False
                    cache_time = None
                    if 'timestamp' in cache_data:
                        cache_time = datetime.fromisoformat(cache_data['timestamp'])
                        entry_ttl = cache_data.get('ttl')
                        if entry_ttl:
                            expired = datetime.now() >= cache_time + timedelta(seconds=int(entry_ttl))
                        else:
                            cutoff = datetime.now() - timedelta(hours=self.config.disk_ttl_hours)
                            expired = cache_time < cutoff

                    if expired:
                        cache_file.unlink()
                        self.misses += 1
                        return None

                    # 加载到内存缓存
                    value = cache_data['value']
                    self._memory_cache[key] = value
                    self._access_times[key] = time.time()
                    entry_ttl = cache_data.get('ttl')
                    if entry_ttl and cache_time is not None:
                        self._expiry[key] = (cache_time + timedelta(seconds=int(entry_ttl))).timestamp()

                self.hits += 1
                return value

            except Exception as e:
                logger = get_logger("cache")
                logger.warning(f"读取文件缓存失败: {cache_file}", error=str(e))
                # 删除损坏的缓存文件
                try:
                    cache_file.unlink()
                except:
                    pass

        self.misses += 1
        return None

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[float] = None,
        ttl_hours: Optional[float] = None,
    ) -> None:
        """设置缓存"""
        # 统一换算成秒（ttl_hours 优先）
        if ttl_hours is not None:
            ttl_seconds = float(ttl_hours) * 3600
        ttl_seconds = float(ttl_seconds) if ttl_seconds else None

        with self._lock:
            # 1. 存储到内存缓存
            if len(self._memory_cache) >= self.config.max_memory_items:
                self._cleanup_memory_cache()

            self._memory_cache[key] = value
            self._access_times[key] = time.time()
            if ttl_seconds and ttl_seconds > 0:
                self._expiry[key] = time.time() + ttl_seconds
            else:
                self._expiry.pop(key, None)

            # 2. 存储到文件缓存
            cache_key = self._get_cache_key(key)
            cache_file = self._get_file_path(cache_key)

            cache_data = {
                'value': value,
                'timestamp': datetime.now().isoformat(),
                'key': key
            }

            if ttl_seconds and ttl_seconds > 0:
                cache_data['ttl'] = int(ttl_seconds)

            try:
                with gzip.open(cache_file, 'wb') as f:
                    pickle.dump(cache_data, f)
            except Exception as e:
                logger = get_logger("cache")
                logger.warning(f"写入文件缓存失败: {cache_file}", error=str(e))

    def delete(self, key: str) -> None:
        """删除缓存"""
        with self._lock:
            # 删除内存缓存
            if key in self._memory_cache:
                del self._memory_cache[key]
            if key in self._access_times:
                del self._access_times[key]
            self._expiry.pop(key, None)

            # 删除文件缓存
            cache_key = self._get_cache_key(key)
            cache_file = self._get_file_path(cache_key)
            try:
                cache_file.unlink()
            except FileNotFoundError:
                pass
            except Exception as e:
                logger = get_logger("cache")
                logger.warning(f"删除缓存文件失败: {cache_file}", error=str(e))

    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            # 清空内存缓存
            self._memory_cache.clear()
            self._access_times.clear()
            self._expiry.clear()

            # 清空文件缓存
            for cache_file in self._file_cache_dir.glob("*.pkl.gz"):
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger = get_logger("cache")
                    logger.warning(f"删除缓存文件失败: {cache_file}", error=str(e))

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            hit_rate = self.hits / (self.hits + self.misses) if (self.hits + self.misses) > 0 else 0

            return {
                'memory_count': len(self._memory_cache),
                'disk_count': len(list(self._file_cache_dir.glob("*.pkl.gz"))),
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': hit_rate,
                'max_memory_items': self.config.max_memory_items,
                'disk_ttl_hours': self.config.disk_ttl_hours
            }

    def optimize(self) -> None:
        """优化缓存"""
        self._cleanup_memory_cache()
        self._cleanup_file_cache()


# 全局缓存实例
_cache_instance = None
_cache_lock = threading.RLock()


def get_cache() -> SmartCache:
    """获取全局缓存实例"""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = SmartCache()
    return _cache_instance


# 缓存装饰器
def cache_result(
    ttl_hours: Optional[float] = None,
    ttl_seconds: Optional[float] = None,
):
    """缓存装饰器"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 生成缓存键
            key_parts = [func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}:{v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # 尝试从缓存获取
            cache = get_cache()
            result = cache.get(cache_key)

            if result is not None:
                return result

            # 执行函数并缓存结果
            result = func(*args, **kwargs)

            cache.set(cache_key, result, ttl_seconds=ttl_seconds, ttl_hours=ttl_hours)

            return result

        return wrapper
    return decorator


# LRU缓存装饰器（用于频繁调用的函数）
def smart_lru_cache(maxsize: int = 128) -> Callable[..., Any]:
    """智能LRU缓存装饰器"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @lru_cache(maxsize=maxsize)
        def cached_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # 清理缓存的辅助方法
        def clear_cache() -> None:
            cached_wrapper.cache_clear()

        wrapper = cached_wrapper
        wrapper.clear_cache = clear_cache
        return wrapper
    return decorator


# 文本内容缓存
def cache_extract_text(url: str, text: str) -> None:
    """缓存提取的文本"""
    cache_key = f"extract:{url}"
    cache = get_cache()
    cache.set(cache_key, text, ttl_hours=24)  # 缓存24小时


def get_cached_extract_text(url: str) -> Optional[str]:
    """获取缓存的提取文本"""
    cache_key = f"extract:{url}"
    cache = get_cache()
    return cache.get(cache_key)


# 事件分析结果缓存
def cache_event_analysis(event_id: str, analysis_result: dict) -> None:
    """缓存事件分析结果"""
    cache_key = f"analysis:{event_id}"
    cache = get_cache()
    cache.set(cache_key, analysis_result, ttl_hours=72)  # 缓存72小时


def get_cached_event_analysis(event_id: str) -> Optional[dict]:
    """获取缓存的事件分析结果"""
    cache_key = f"analysis:{event_id}"
    cache = get_cache()
    return cache.get(cache_key)
