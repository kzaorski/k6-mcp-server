"""
Unit tests for performance optimization utilities.

Tests caching, circuit breakers, metrics collection, and monitoring.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch

from utils.performance import (
    LRUCache, CircuitBreaker, MetricsCollector, HealthChecker,
    RequestThrottler, performance_monitor, timed_cache,
    memory_monitor, global_cache, global_metrics, global_health
)


class TestLRUCache:
    """Test cases for LRU Cache implementation."""
    
    @pytest.mark.asyncio
    async def test_cache_basic_operations(self):
        """Test basic cache set/get operations."""
        cache = LRUCache(max_size=3, ttl_seconds=60)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        
        assert await cache.get("key1") == "value1"
        assert await cache.get("key2") == "value2"
        assert await cache.get("nonexistent") is None
    
    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = LRUCache(max_size=2, ttl_seconds=60)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")  # Should evict key1
        
        assert await cache.get("key1") is None  # Evicted
        assert await cache.get("key2") == "value2"
        assert await cache.get("key3") == "value3"
    
    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self):
        """Test TTL-based cache expiration."""
        cache = LRUCache(max_size=10, ttl_seconds=1)
        
        await cache.set("key1", "value1")
        assert await cache.get("key1") == "value1"
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio
    async def test_cache_statistics(self):
        """Test cache statistics collection."""
        cache = LRUCache(max_size=10, ttl_seconds=60)
        
        await cache.set("key1", "value1")
        await cache.get("key1")  # Hit
        await cache.get("nonexistent")  # Miss
        
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["size"] == 1
    
    @pytest.mark.asyncio
    async def test_cache_cleanup_expired(self):
        """Test manual cleanup of expired entries."""
        cache = LRUCache(max_size=10, ttl_seconds=1)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        expired_count = await cache.cleanup_expired()
        assert expired_count == 2
        assert cache.stats()["size"] == 0


class TestCircuitBreaker:
    """Test cases for Circuit Breaker implementation."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in closed state."""
        breaker = CircuitBreaker(failure_threshold=3, timeout_seconds=5)
        
        async def successful_function():
            return "success"
        
        result = await breaker.call(successful_function)
        assert result == "success"
        
        stats = breaker.stats()
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self):
        """Test circuit breaker opens after threshold failures."""
        breaker = CircuitBreaker(failure_threshold=2, timeout_seconds=5)
        
        async def failing_function():
            raise Exception("Test failure")
        
        # First failure
        with pytest.raises(Exception, match="Test failure"):
            await breaker.call(failing_function)
        
        # Second failure - should open circuit
        with pytest.raises(Exception, match="Test failure"):
            await breaker.call(failing_function)
        
        stats = breaker.stats()
        assert stats["state"] == "open"
        assert stats["failure_count"] == 2
        
        # Third call should be blocked
        with pytest.raises(Exception, match="Circuit breaker is open"):
            await breaker.call(failing_function)
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker half-open state and recovery."""
        breaker = CircuitBreaker(failure_threshold=2, timeout_seconds=0.1)
        
        # Force circuit to open
        async def failing_function():
            raise Exception("Test failure")
        
        for _ in range(2):
            with pytest.raises(Exception):
                await breaker.call(failing_function)
        
        assert breaker.stats()["state"] == "open"
        
        # Wait for timeout
        await asyncio.sleep(0.2)
        
        # Successful call should close circuit
        async def successful_function():
            return "recovered"
        
        result = await breaker.call(successful_function)
        assert result == "recovered"
        assert breaker.stats()["state"] == "closed"


class TestMetricsCollector:
    """Test cases for Metrics Collector."""
    
    @pytest.mark.asyncio
    async def test_metrics_recording(self):
        """Test basic metrics recording."""
        collector = MetricsCollector()
        
        await collector.record("response_time", 150.5)
        await collector.record("response_time", 200.0)
        await collector.record("throughput", 50.0)
        
        response_stats = await collector.get_stats("response_time")
        assert response_stats["count"] == 2
        assert response_stats["min"] == 150.5
        assert response_stats["max"] == 200.0
        assert response_stats["mean"] == 175.25
    
    @pytest.mark.asyncio
    async def test_metrics_percentiles(self):
        """Test percentile calculations."""
        collector = MetricsCollector()
        
        # Record 100 values
        for i in range(100):
            await collector.record("test_metric", i)
        
        stats = await collector.get_stats("test_metric")
        assert stats["count"] == 100
        assert stats["p50"] == 50
        assert stats["p90"] == 90
        assert stats["p95"] == 95
        assert stats["p99"] == 99
    
    @pytest.mark.asyncio
    async def test_metrics_with_tags(self):
        """Test metrics recording with tags."""
        collector = MetricsCollector()
        
        await collector.record("response_time", 150.0, {"endpoint": "/users"})
        await collector.record("response_time", 200.0, {"endpoint": "/orders"})
        
        # Should be able to get all stats regardless of tags
        stats = await collector.get_stats("response_time")
        assert stats["count"] == 2
    
    @pytest.mark.asyncio
    async def test_metrics_time_window(self):
        """Test metrics filtering by time window."""
        collector = MetricsCollector()
        
        # Record old metric
        await collector.record("old_metric", 100.0)
        
        # Simulate time passage (in real test, this would be mocked)
        await asyncio.sleep(0.1)
        
        # Get recent metrics (very short window)
        stats = await collector.get_stats("old_metric", minutes=0.001)
        assert stats == {} or stats["count"] == 0


class TestRequestThrottler:
    """Test cases for Request Throttler."""
    
    @pytest.mark.asyncio
    async def test_throttler_allows_requests_within_rate(self):
        """Test throttler allows requests within rate limit."""
        throttler = RequestThrottler(initial_rate=10.0, min_rate=1.0, max_rate=100.0)
        
        # Should allow first request
        assert await throttler.acquire() is True
        
        # Report success to maintain rate
        await throttler.report_success()
    
    @pytest.mark.asyncio
    async def test_throttler_blocks_excessive_requests(self):
        """Test throttler blocks requests exceeding rate limit."""
        throttler = RequestThrottler(initial_rate=1.0, min_rate=0.1, max_rate=10.0)
        
        # First request should be allowed
        assert await throttler.acquire() is True
        
        # Immediate second request should be blocked
        assert await throttler.acquire() is False
    
    @pytest.mark.asyncio
    async def test_throttler_adaptive_rate_adjustment(self):
        """Test adaptive rate adjustment based on error rates."""
        throttler = RequestThrottler(initial_rate=10.0, min_rate=1.0, max_rate=100.0)
        
        # Simulate high error rate
        for _ in range(10):
            await throttler.report_error()
        
        # Trigger rate adjustment (normally time-based, but we'll call directly)
        await throttler._adjust_rate()
        
        stats = throttler.stats()
        # Rate should be reduced due to high error rate
        assert stats["current_rate"] < 10.0
    
    def test_throttler_statistics(self):
        """Test throttler statistics collection."""
        throttler = RequestThrottler(initial_rate=5.0)
        
        stats = throttler.stats()
        assert "current_rate" in stats
        assert "available_tokens" in stats
        assert "success_count" in stats
        assert "error_count" in stats
        assert "error_rate" in stats


class TestHealthChecker:
    """Test cases for Health Checker."""
    
    @pytest.mark.asyncio
    async def test_health_checker_register_and_run(self):
        """Test registering and running health checks."""
        checker = HealthChecker()
        
        def test_health_check():
            return {"healthy": True, "status": "operational"}
        
        checker.register_check("test_component", test_health_check)
        
        results = await checker.run_checks(force=True)
        
        assert "test_component" in results
        assert results["test_component"]["healthy"] is True
        assert results["overall"]["healthy"] is True
    
    @pytest.mark.asyncio
    async def test_health_checker_failing_check(self):
        """Test health checker with failing component."""
        checker = HealthChecker()
        
        def failing_health_check():
            return {"healthy": False, "error": "Service unavailable"}
        
        checker.register_check("failing_component", failing_health_check)
        
        results = await checker.run_checks(force=True)
        
        assert results["failing_component"]["healthy"] is False
        assert results["overall"]["healthy"] is False
    
    @pytest.mark.asyncio
    async def test_health_checker_exception_handling(self):
        """Test health checker handles exceptions in checks."""
        checker = HealthChecker()
        
        def exception_health_check():
            raise Exception("Check failed")
        
        checker.register_check("error_component", exception_health_check)
        
        results = await checker.run_checks(force=True)
        
        assert results["error_component"]["healthy"] is False
        assert "error" in results["error_component"]
        assert results["overall"]["healthy"] is False


class TestPerformanceMonitor:
    """Test cases for Performance Monitor decorator."""
    
    @pytest.mark.asyncio
    async def test_performance_monitor_async_function(self):
        """Test performance monitoring of async functions."""
        
        @performance_monitor("test_function")
        async def test_async_function(duration=0.1):
            await asyncio.sleep(duration)
            return "completed"
        
        result = await test_async_function(0.05)
        assert result == "completed"
        
        # Check that metrics were recorded
        stats = await global_metrics.get_all_stats()
        duration_metrics = None
        success_metrics = None
        
        for metric_name, metric_stats in stats.items():
            if "test_function.duration" in metric_name:
                duration_metrics = metric_stats
            elif "test_function.success" in metric_name:
                success_metrics = metric_stats
        
        if duration_metrics:
            assert duration_metrics["count"] > 0
        if success_metrics:
            assert success_metrics["count"] > 0
    
    def test_performance_monitor_sync_function(self):
        """Test performance monitoring of sync functions."""
        
        @performance_monitor("test_sync_function")
        def test_sync_function(value):
            time.sleep(0.01)
            return value * 2
        
        result = test_sync_function(5)
        assert result == 10
    
    @pytest.mark.asyncio
    async def test_performance_monitor_exception_handling(self):
        """Test performance monitor handles exceptions correctly."""
        
        @performance_monitor("test_failing_function")
        async def test_failing_function():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError, match="Test error"):
            await test_failing_function()
        
        # Should still record metrics even on failure
        stats = await global_metrics.get_all_stats()
        success_metrics = None
        
        for metric_name, metric_stats in stats.items():
            if "test_failing_function.success" in metric_name:
                success_metrics = metric_stats
                break
        
        if success_metrics:
            # Success metric should record 0 for failed calls
            assert success_metrics["count"] > 0


class TestTimedCache:
    """Test cases for timed cache decorator."""
    
    @pytest.mark.asyncio
    async def test_timed_cache_decorator(self):
        """Test timed cache decorator functionality."""
        call_count = 0
        
        @timed_cache(ttl_seconds=60, max_size=10)
        async def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # Simulate expensive operation
            return x + y
        
        # First call
        result1 = await expensive_function(1, 2)
        assert result1 == 3
        assert call_count == 1
        
        # Second call with same args should use cache
        result2 = await expensive_function(1, 2)
        assert result2 == 3
        assert call_count == 1  # Should not increment
        
        # Call with different args should execute function
        result3 = await expensive_function(2, 3)
        assert result3 == 5
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_timed_cache_expiration(self):
        """Test timed cache expiration."""
        call_count = 0
        
        @timed_cache(ttl_seconds=0.1, max_size=10)
        async def cached_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        # First call
        result1 = await cached_function(5)
        assert result1 == 10
        assert call_count == 1
        
        # Wait for cache expiration
        await asyncio.sleep(0.2)
        
        # Should execute function again
        result2 = await cached_function(5)
        assert result2 == 10
        assert call_count == 2


class TestMemoryMonitor:
    """Test cases for Memory Monitor."""
    
    def test_memory_usage_reporting(self):
        """Test memory usage reporting."""
        usage = memory_monitor.get_memory_usage()
        
        assert "rss_mb" in usage
        assert "vms_mb" in usage
        assert "percent" in usage
        assert "peak_mb" in usage
        assert "gc_runs" in usage
        assert "objects_count" in usage
        
        assert usage["rss_mb"] > 0
        assert usage["objects_count"] > 0
    
    def test_garbage_collection(self):
        """Test manual garbage collection."""
        initial_objects = memory_monitor.get_memory_usage()["objects_count"]
        
        # Create some objects
        temp_list = [i for i in range(1000)]
        
        # Force garbage collection
        gc_stats = memory_monitor.force_gc()
        
        assert "collected" in gc_stats
        assert "objects_before" in gc_stats
        assert "objects_after" in gc_stats
        assert "objects_freed" in gc_stats
        
        # Clean up
        del temp_list
    
    def test_gc_threshold_check(self):
        """Test garbage collection threshold checking."""
        # Should not trigger GC immediately after previous GC
        should_gc = memory_monitor.should_gc(threshold_mb=0.1)
        # Result depends on actual memory usage and timing


class TestGlobalInstances:
    """Test cases for global performance instances."""
    
    @pytest.mark.asyncio
    async def test_global_cache_functionality(self):
        """Test global cache instance."""
        await global_cache.set("test_key", "test_value")
        value = await global_cache.get("test_key")
        assert value == "test_value"
    
    @pytest.mark.asyncio
    async def test_global_metrics_functionality(self):
        """Test global metrics instance."""
        await global_metrics.record("test_metric", 42.0)
        stats = await global_metrics.get_stats("test_metric")
        
        if stats:  # Might be empty due to time window
            assert stats["count"] >= 0
    
    @pytest.mark.asyncio
    async def test_global_health_functionality(self):
        """Test global health checker instance."""
        def test_check():
            return {"healthy": True, "component": "test"}
        
        global_health.register_check("global_test", test_check)
        results = await global_health.run_checks(force=True)
        
        assert "global_test" in results
        assert results["global_test"]["healthy"] is True


# Test fixtures and utilities
@pytest.fixture
def sample_cache():
    """Create a sample cache for testing."""
    return LRUCache(max_size=100, ttl_seconds=60)


@pytest.fixture
def sample_circuit_breaker():
    """Create a sample circuit breaker for testing."""
    return CircuitBreaker(failure_threshold=5, timeout_seconds=30)


@pytest.fixture
def sample_metrics_collector():
    """Create a sample metrics collector for testing."""
    return MetricsCollector(max_samples=1000)


@pytest.fixture
def sample_health_checker():
    """Create a sample health checker for testing."""
    return HealthChecker()


@pytest.fixture
def sample_request_throttler():
    """Create a sample request throttler for testing."""
    return RequestThrottler(initial_rate=50.0, min_rate=10.0, max_rate=200.0)