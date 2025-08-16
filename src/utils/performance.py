"""
Performance optimization utilities for K6 MCP Server.

Provides utilities for memory management, caching, async operations,
and resource optimization.
"""

import asyncio
import functools
import gc
import time
import weakref
from typing import Any, Callable, Dict, Optional, TypeVar, Union
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

T = TypeVar('T')


@dataclass
class CacheEntry:
    """Cache entry with expiration support."""
    value: Any
    created_at: datetime
    access_count: int = 0
    last_accessed: datetime = None
    
    def __post_init__(self):
        if self.last_accessed is None:
            self.last_accessed = self.created_at
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cache entry is expired."""
        return (datetime.utcnow() - self.created_at).seconds > ttl_seconds
    
    def mark_accessed(self):
        """Mark entry as accessed."""
        self.access_count += 1
        self.last_accessed = datetime.utcnow()


class LRUCache:
    """
    Thread-safe LRU cache with TTL support.
    
    Features:
    - Least Recently Used eviction
    - Time-based expiration
    - Memory usage tracking
    - Statistics collection
    """
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        
        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            
            # Check expiration
            if entry.is_expired(self.ttl_seconds):
                del self._cache[key]
                self._misses += 1
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.mark_accessed()
            self._hits += 1
            
            return entry.value
    
    async def set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        async with self._lock:
            now = datetime.utcnow()
            
            if key in self._cache:
                # Update existing entry
                entry = self._cache[key]
                entry.value = value
                entry.created_at = now
                entry.mark_accessed()
                self._cache.move_to_end(key)
            else:
                # Add new entry
                entry = CacheEntry(value=value, created_at=now)
                self._cache[key] = entry
                
                # Evict oldest if over capacity
                if len(self._cache) > self.max_size:
                    self._cache.popitem(last=False)
                    self._evictions += 1
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()
    
    async def cleanup_expired(self) -> int:
        """Remove expired entries and return count."""
        async with self._lock:
            expired_keys = []
            now = datetime.utcnow()
            
            for key, entry in self._cache.items():
                if entry.is_expired(self.ttl_seconds):
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._cache[key]
            
            return len(expired_keys)
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
            "evictions": self._evictions,
            "ttl_seconds": self.ttl_seconds
        }


class AsyncBatch:
    """
    Batch processor for async operations.
    
    Collects multiple operations and executes them in batches
    to improve performance and reduce resource usage.
    """
    
    def __init__(self, batch_size: int = 100, max_wait_time: float = 1.0):
        self.batch_size = batch_size
        self.max_wait_time = max_wait_time
        self._items = []
        self._futures = []
        self._last_batch_time = time.time()
        self._lock = asyncio.Lock()
        self._processing = False
    
    async def add(self, item: Any) -> Any:
        """Add item to batch and return future result."""
        async with self._lock:
            future = asyncio.Future()
            self._items.append(item)
            self._futures.append(future)
            
            # Check if we should process the batch
            should_process = (
                len(self._items) >= self.batch_size or
                time.time() - self._last_batch_time >= self.max_wait_time
            )
            
            if should_process and not self._processing:
                asyncio.create_task(self._process_batch())
            
            return await future
    
    async def _process_batch(self):
        """Process the current batch."""
        async with self._lock:
            if self._processing or not self._items:
                return
            
            self._processing = True
            items = self._items.copy()
            futures = self._futures.copy()
            self._items.clear()
            self._futures.clear()
            self._last_batch_time = time.time()
        
        try:
            # Process items in batch (override this method)
            results = await self._process_items(items)
            
            # Set results for futures
            for future, result in zip(futures, results):
                if not future.cancelled():
                    future.set_result(result)
        
        except Exception as e:
            # Set exception for all futures
            for future in futures:
                if not future.cancelled():
                    future.set_exception(e)
        
        finally:
            async with self._lock:
                self._processing = False
    
    async def _process_items(self, items: list) -> list:
        """Override this method to implement batch processing logic."""
        # Default implementation - process items individually
        return [await self._process_item(item) for item in items]
    
    async def _process_item(self, item: Any) -> Any:
        """Override this method to implement single item processing."""
        return item


class ResourcePool:
    """
    Generic resource pool for managing expensive resources.
    
    Provides pooling for database connections, HTTP clients,
    or other expensive resources.
    """
    
    def __init__(self, factory: Callable[[], T], max_size: int = 10):
        self.factory = factory
        self.max_size = max_size
        self._pool = asyncio.Queue(maxsize=max_size)
        self._created = 0
        self._in_use = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> T:
        """Acquire a resource from the pool."""
        try:
            # Try to get from pool without waiting
            resource = self._pool.get_nowait()
            async with self._lock:
                self._in_use += 1
            return resource
        except asyncio.QueueEmpty:
            # Create new resource if under limit
            async with self._lock:
                if self._created < self.max_size:
                    resource = self.factory()
                    self._created += 1
                    self._in_use += 1
                    return resource
            
            # Wait for resource to become available
            resource = await self._pool.get()
            async with self._lock:
                self._in_use += 1
            return resource
    
    async def release(self, resource: T) -> None:
        """Release a resource back to the pool."""
        async with self._lock:
            self._in_use -= 1
        
        try:
            self._pool.put_nowait(resource)
        except asyncio.QueueFull:
            # Pool is full, discard resource
            async with self._lock:
                self._created -= 1
    
    def stats(self) -> Dict[str, int]:
        """Get pool statistics."""
        return {
            "created": self._created,
            "in_use": self._in_use,
            "available": self._pool.qsize(),
            "max_size": self.max_size
        }


class MemoryMonitor:
    """
    Memory usage monitor and optimizer.
    
    Tracks memory usage and provides utilities for
    memory optimization and garbage collection.
    """
    
    def __init__(self):
        self._peak_memory = 0
        self._gc_runs = 0
        self._last_gc_time = time.time()
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """Get current memory usage."""
        import psutil
        import sys
        
        process = psutil.Process()
        memory_info = process.memory_info()
        
        usage = {
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
            "percent": process.memory_percent(),
            "peak_mb": self._peak_memory / 1024 / 1024,
            "gc_runs": self._gc_runs,
            "objects_count": len(gc.get_objects())
        }
        
        # Update peak memory
        if memory_info.rss > self._peak_memory:
            self._peak_memory = memory_info.rss
        
        return usage
    
    def force_gc(self) -> Dict[str, Any]:
        """Force garbage collection and return statistics."""
        before = len(gc.get_objects())
        
        # Run garbage collection
        collected = gc.collect()
        
        after = len(gc.get_objects())
        self._gc_runs += 1
        self._last_gc_time = time.time()
        
        return {
            "collected": collected,
            "objects_before": before,
            "objects_after": after,
            "objects_freed": before - after
        }
    
    def should_gc(self, threshold_mb: float = 100) -> bool:
        """Check if garbage collection should be triggered."""
        usage = self.get_memory_usage()
        time_since_gc = time.time() - self._last_gc_time
        
        return (
            usage["rss_mb"] > threshold_mb and
            time_since_gc > 60  # At least 1 minute since last GC
        )


def timed_cache(ttl_seconds: int = 3600, max_size: int = 128):
    """
    Decorator for caching function results with TTL.
    
    Args:
        ttl_seconds: Time to live for cached results
        max_size: Maximum number of cached entries
    """
    def decorator(func: Callable) -> Callable:
        cache = LRUCache(max_size=max_size, ttl_seconds=ttl_seconds)
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key
            key = f"{func.__name__}:{hash((args, tuple(sorted(kwargs.items()))))}"
            
            # Try to get from cache
            result = await cache.get(key)
            if result is not None:
                return result
            
            # Execute function and cache result
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            await cache.set(key, result)
            return result
        
        # Add cache management methods
        wrapper._cache = cache
        wrapper.cache_stats = cache.stats
        wrapper.cache_clear = cache.clear
        
        return wrapper
    
    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for fault tolerance.
    
    Prevents cascading failures by stopping calls to failing services.
    """
    
    def __init__(self, failure_threshold: int = 5, timeout_seconds: float = 60):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        
        self._failure_count = 0
        self._last_failure_time = None
        self._state = "closed"  # closed, open, half-open
    
    async def call(self, func: Callable, *args, **kwargs):
        """Call function through circuit breaker."""
        if self._state == "open":
            if self._should_attempt_reset():
                self._state = "half-open"
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Success - reset failure count
            self._failure_count = 0
            if self._state == "half-open":
                self._state = "closed"
            
            return result
        
        except Exception as e:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._failure_count >= self.failure_threshold:
                self._state = "open"
            
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset the circuit breaker."""
        if self._last_failure_time is None:
            return True
        
        return time.time() - self._last_failure_time >= self.timeout_seconds
    
    def stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "state": self._state,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "timeout_seconds": self.timeout_seconds
        }


class RequestThrottler:
    """
    Request throttler with adaptive rate limiting.
    
    Automatically adjusts rate limits based on system performance
    and error rates to maintain optimal throughput.
    """
    
    def __init__(self, initial_rate: float = 100.0, min_rate: float = 10.0, max_rate: float = 1000.0):
        self.current_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        
        self._tokens = initial_rate
        self._last_refill = time.time()
        self._success_count = 0
        self._error_count = 0
        self._adjustment_interval = 60  # Adjust rate every 60 seconds
        self._last_adjustment = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """Try to acquire a request token."""
        async with self._lock:
            now = time.time()
            
            # Refill tokens
            elapsed = now - self._last_refill
            self._tokens = min(self.current_rate, self._tokens + elapsed * self.current_rate)
            self._last_refill = now
            
            # Adjust rate if needed
            if now - self._last_adjustment >= self._adjustment_interval:
                await self._adjust_rate()
                self._last_adjustment = now
            
            # Check if token available
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            
            return False
    
    async def report_success(self):
        """Report successful request."""
        async with self._lock:
            self._success_count += 1
    
    async def report_error(self):
        """Report failed request."""
        async with self._lock:
            self._error_count += 1
    
    async def _adjust_rate(self):
        """Adjust rate based on success/error ratio."""
        total_requests = self._success_count + self._error_count
        if total_requests == 0:
            return
        
        error_rate = self._error_count / total_requests
        
        # Adjust rate based on error rate
        if error_rate > 0.1:  # More than 10% errors
            # Decrease rate
            self.current_rate = max(self.min_rate, self.current_rate * 0.8)
        elif error_rate < 0.05:  # Less than 5% errors
            # Increase rate
            self.current_rate = min(self.max_rate, self.current_rate * 1.2)
        
        # Reset counters
        self._success_count = 0
        self._error_count = 0
    
    def stats(self) -> Dict[str, Any]:
        """Get throttler statistics."""
        total_requests = self._success_count + self._error_count
        error_rate = self._error_count / total_requests if total_requests > 0 else 0
        
        return {
            "current_rate": self.current_rate,
            "available_tokens": self._tokens,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "error_rate": error_rate
        }


class MetricsCollector:
    """
    Advanced metrics collector with histogram support.
    
    Collects performance metrics with percentile calculations
    and trend analysis.
    """
    
    def __init__(self, max_samples: int = 10000):
        self.max_samples = max_samples
        self._metrics: Dict[str, list] = {}
        self._lock = asyncio.Lock()
    
    async def record(self, metric_name: str, value: float, tags: Dict[str, str] = None):
        """Record a metric value."""
        async with self._lock:
            if metric_name not in self._metrics:
                self._metrics[metric_name] = []
            
            timestamp = time.time()
            entry = {
                "value": value,
                "timestamp": timestamp,
                "tags": tags or {}
            }
            
            self._metrics[metric_name].append(entry)
            
            # Trim old entries
            if len(self._metrics[metric_name]) > self.max_samples:
                self._metrics[metric_name] = self._metrics[metric_name][-self.max_samples:]
    
    async def get_stats(self, metric_name: str, minutes: int = 5) -> Dict[str, Any]:
        """Get statistics for a metric."""
        async with self._lock:
            if metric_name not in self._metrics:
                return {}
            
            # Filter recent entries
            cutoff = time.time() - (minutes * 60)
            recent_entries = [
                entry for entry in self._metrics[metric_name]
                if entry["timestamp"] >= cutoff
            ]
            
            if not recent_entries:
                return {}
            
            values = [entry["value"] for entry in recent_entries]
            values.sort()
            
            count = len(values)
            return {
                "count": count,
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / count,
                "p50": values[count // 2],
                "p90": values[int(count * 0.9)] if count > 1 else values[0],
                "p95": values[int(count * 0.95)] if count > 1 else values[0],
                "p99": values[int(count * 0.99)] if count > 1 else values[0]
            }
    
    async def get_all_stats(self, minutes: int = 5) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all metrics."""
        stats = {}
        for metric_name in self._metrics.keys():
            stats[metric_name] = await self.get_stats(metric_name, minutes)
        return stats


def performance_monitor(metric_name: str = None):
    """
    Decorator to monitor function performance.
    
    Automatically records execution time and success/failure rates.
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__name__}"
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                raise
            finally:
                duration = time.time() - start_time
                await global_metrics.record(f"{name}.duration", duration * 1000)  # milliseconds
                await global_metrics.record(f"{name}.success", 1 if success else 0)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                raise
            finally:
                duration = time.time() - start_time
                # For sync functions, create async task
                asyncio.create_task(global_metrics.record(f"{name}.duration", duration * 1000))
                asyncio.create_task(global_metrics.record(f"{name}.success", 1 if success else 0))
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class HealthChecker:
    """
    System health checker with component monitoring.
    
    Monitors various system components and provides
    health status and recommendations.
    """
    
    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._last_check = 0
    
    def register_check(self, name: str, check_func: Callable[[], Dict[str, Any]]):
        """Register a health check function."""
        self._checks[name] = check_func
    
    async def run_checks(self, force: bool = False) -> Dict[str, Any]:
        """Run all health checks."""
        now = time.time()
        
        # Run checks every 30 seconds unless forced
        if not force and now - self._last_check < 30:
            return self._results
        
        self._last_check = now
        overall_healthy = True
        
        for name, check_func in self._checks.items():
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()
                
                result["timestamp"] = now
                result["healthy"] = result.get("healthy", True)
                
                if not result["healthy"]:
                    overall_healthy = False
                
                self._results[name] = result
            
            except Exception as e:
                self._results[name] = {
                    "healthy": False,
                    "error": str(e),
                    "timestamp": now
                }
                overall_healthy = False
        
        # Add overall status
        self._results["overall"] = {
            "healthy": overall_healthy,
            "timestamp": now,
            "component_count": len(self._checks)
        }
        
        return self._results
    
    def get_status(self) -> Dict[str, Any]:
        """Get last health check results."""
        return self._results


# Built-in health checks
def memory_health_check() -> Dict[str, Any]:
    """Check memory usage health."""
    usage = memory_monitor.get_memory_usage()
    healthy = usage["percent"] < 80  # Less than 80% memory usage
    
    return {
        "healthy": healthy,
        "memory_percent": usage["percent"],
        "memory_mb": usage["rss_mb"],
        "warning": "High memory usage" if not healthy else None
    }


def cache_health_check() -> Dict[str, Any]:
    """Check cache performance health."""
    stats = global_cache.stats()
    healthy = stats["hit_rate"] > 0.5  # More than 50% hit rate
    
    return {
        "healthy": healthy,
        "hit_rate": stats["hit_rate"],
        "size": stats["size"],
        "warning": "Low cache hit rate" if not healthy else None
    }


# Global instances
memory_monitor = MemoryMonitor()
global_cache = LRUCache(max_size=10000, ttl_seconds=3600)
global_metrics = MetricsCollector()
global_throttler = RequestThrottler()
global_health = HealthChecker()

# Register default health checks
global_health.register_check("memory", memory_health_check)
global_health.register_check("cache", cache_health_check)