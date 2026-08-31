"""
缓存模块测试
"""

import unittest
import time
import tempfile
import shutil
from pathlib import Path

from app.utils.cache import SmartCache, get_cache, cache_result, smart_lru_cache


class TestSmartCache(unittest.TestCase):
    """智能缓存测试"""

    def setUp(self):
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.cache = SmartCache(cache_dir=self.temp_dir)

    def tearDown(self):
        # 清理临时目录
        shutil.rmtree(self.temp_dir)

    def test_set_and_get(self):
        """测试基本存取"""
        self.cache.set("key1", "value1")
        value = self.cache.get("key1")
        self.assertEqual(value, "value1")

    def test_cache_miss(self):
        """测试缓存未命中"""
        value = self.cache.get("nonexistent_key")
        self.assertIsNone(value)

    def test_ttl_expiration(self):
        """测试TTL过期"""
        # 设置带TTL的缓存
        self.cache.set("key_ttl", "value_ttl", ttl_seconds=1)
        value = self.cache.get("key_ttl")
        self.assertEqual(value, "value_ttl")

        # 等待过期
        time.sleep(1.1)
        value = self.cache.get("key_ttl")
        self.assertIsNone(value)

    def test_memory_cache_limit(self):
        """测试内存缓存限制"""
        # 设置超过限制的缓存项
        for i in range(1500):  # 默认最大1000
            self.cache.set(f"key_{i}", f"value_{i}")

        # 应该只有最近的1000项在内存中
        stats = self.cache.get_stats()
        self.assertLessEqual(stats['memory_count'], 1000)

    def test_file_cache(self):
        """测试文件缓存"""
        key = "file_key"
        value = {"test": "data", "number": 123}

        self.cache.set(key, value)

        # 重新创建缓存实例测试文件持久化
        new_cache = SmartCache(cache_dir=self.temp_dir)
        retrieved = new_cache.get(key)

        self.assertEqual(retrieved, value)

    def test_delete(self):
        """测试删除缓存"""
        self.cache.set("key_delete", "value_delete")
        self.assertEqual(self.cache.get("key_delete"), "value_delete")

        self.cache.delete("key_delete")
        self.assertIsNone(self.cache.get("key_delete"))

    def test_clear(self):
        """测试清空缓存"""
        # 设置多个缓存项
        for i in range(10):
            self.cache.set(f"clear_key_{i}", f"clear_value_{i}")

        # 验证缓存项存在
        stats = self.cache.get_stats()
        self.assertGreater(stats['memory_count'], 0)

        # 清空缓存
        self.cache.clear()

        # 验证缓存已清空
        stats = self.cache.get_stats()
        self.assertEqual(stats['memory_count'], 0)

    def test_hit_rate(self):
        """测试命中率统计"""
        # 设置一些缓存
        for i in range(5):
            self.cache.set(f"hit_key_{i}", f"hit_value_{i}")

        # 命中缓存
        for i in range(5):
            self.cache.get(f"hit_key_{i}")

        # 未命中
        for i in range(5):
            self.cache.get(f"miss_key_{i}")

        stats = self.cache.get_stats()
        self.assertEqual(stats['hits'], 5)
        self.assertEqual(stats['misses'], 5)
        self.assertEqual(stats['hit_rate'], 0.5)


class TestCacheDecorators(unittest.TestCase):
    """缓存装饰器测试"""

    def test_cache_result_decorator(self):
        """测试缓存结果装饰器"""
        call_count = 0

        @cache_result(ttl_seconds=1)
        def test_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y

        # 第一次调用
        result1 = test_function(1, 2)
        self.assertEqual(result1, 3)
        self.assertEqual(call_count, 1)

        # 第二次调用应该使用缓存
        result2 = test_function(1, 2)
        self.assertEqual(result2, 3)
        self.assertEqual(call_count, 1)  # 没有增加

        # 等待过期（1 秒 TTL）
        time.sleep(1.1)

        # 过期后再次调用
        result3 = test_function(1, 2)
        self.assertEqual(result3, 3)
        self.assertEqual(call_count, 2)  # 重新调用

    def test_smart_lru_cache(self):
        """测试智能LRU缓存"""
        call_count = 0

        @smart_lru_cache(maxsize=3)
        def test_lru_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # 填充缓存
        test_lru_function(1)  # 调用1
        test_lru_function(2)  # 调用2
        test_lru_function(3)  # 调用3

        self.assertEqual(call_count, 3)

        # 再次调用已缓存值
        test_lru_function(1)
        test_lru_function(2)
        test_lru_function(3)

        # 应该没有新调用
        self.assertEqual(call_count, 3)

        # 添加新值，触发LRU
        test_lru_function(4)  # 调用4
        test_lru_function(1)  # 应该被踢出，调用1
        test_lru_function(2)  # 应该被踢出，调用2

        self.assertEqual(call_count, 6)

    def test_clear_cache_method(self):
        """测试清除缓存方法"""
        @smart_lru_cache(maxsize=10)
        def test_func(x):
            return x * 2

        test_func(1)  # 第一次调用
        self.assertEqual(test_func(1), 2)  # 使用缓存

        # 清除缓存
        test_func.clear_cache()

        # 再次调用
        result = test_func(1)
        self.assertEqual(result, 2)  # 应该重新计算


class TestGlobalCache(unittest.TestCase):
    """全局缓存测试"""

    def test_global_instance(self):
        """测试全局实例"""
        cache1 = get_cache()
        cache2 = get_cache()

        # 应该是同一个实例
        self.assertIs(cache1, cache2)

    def test_global_cache_operations(self):
        """测试全局缓存操作"""
        cache = get_cache()

        # 设置值
        cache.set("global_key", "global_value")

        # 验证值
        value = cache.get("global_key")
        self.assertEqual(value, "global_value")


if __name__ == '__main__':
    unittest.main()
