"""
Async I/O Optimization Module for K6 MCP Server.

This module provides optimized async I/O operations including streaming file operations,
connection pooling, and efficient resource management for better performance and memory usage.
"""

import asyncio
import aiofiles
import aiohttp
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum

from error_handler import (
    ErrorHandler, ErrorContext, ErrorCategory, EnhancedError,
    ResourceExhaustionError, with_error_handling, graceful_degradation
)

logger = logging.getLogger(__name__)


class StreamingMode(Enum):
    """Streaming operation modes."""
    BINARY = "binary"
    TEXT = "text"
    JSON_LINES = "json_lines"
    CSV = "csv"


@dataclass
class StreamingConfig:
    """Configuration for streaming operations."""
    chunk_size: int = 8192
    max_file_size: int = 100_000_000  # 100MB
    encoding: str = "utf-8"
    buffer_size: int = 64 * 1024  # 64KB
    timeout: float = 30.0
    max_concurrent_operations: int = 10


@dataclass
class ConnectionPoolConfig:
    """Configuration for HTTP connection pooling."""
    max_connections: int = 100
    max_connections_per_host: int = 30
    timeout_total: float = 300.0
    timeout_connect: float = 30.0
    timeout_read: float = 60.0
    max_retries: int = 3
    enable_compression: bool = True
    enable_keepalive: bool = True


class AsyncIOOptimizer:
    """
    High-performance async I/O operations with streaming and connection pooling.
    """
    
    def __init__(
        self,
        streaming_config: Optional[StreamingConfig] = None,
        connection_config: Optional[ConnectionPoolConfig] = None
    ):
        self.streaming_config = streaming_config or StreamingConfig()
        self.connection_config = connection_config or ConnectionPoolConfig()
        self.error_handler = ErrorHandler()
        
        # Connection pool management
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = None  # Will be initialized when event loop is available
        
        # Thread pool for CPU-intensive operations
        try:
            # Try to get current loop if available
            loop = asyncio.get_running_loop()
            max_workers = min(32, (loop.get_debug() and 1) or 4)
        except RuntimeError:
            # No running loop, use default
            max_workers = 4
        
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        
        # Semaphore for limiting concurrent operations - will be initialized when needed
        self._operation_semaphore = None
        
        # Metrics tracking
        self._metrics = {
            'bytes_read': 0,
            'bytes_written': 0,
            'files_processed': 0,
            'http_requests': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    def _ensure_async_components(self):
        """Initialize async components when event loop is available."""
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        if self._operation_semaphore is None:
            self._operation_semaphore = asyncio.Semaphore(
                self.streaming_config.max_concurrent_operations
            )
    
    async def _ensure_session(self):
        """Ensure HTTP session is initialized."""
        self._ensure_async_components()
        if self._session is None:
            async with self._session_lock:
                if self._session is None:
                    connector = aiohttp.TCPConnector(
                        limit=self.connection_config.max_connections,
                        limit_per_host=self.connection_config.max_connections_per_host,
                        enable_cleanup_closed=True,
                        keepalive_timeout=30,
                        use_dns_cache=True
                    )
                    
                    timeout = aiohttp.ClientTimeout(
                        total=self.connection_config.timeout_total,
                        connect=self.connection_config.timeout_connect,
                        sock_read=self.connection_config.timeout_read
                    )
                    
                    self._session = aiohttp.ClientSession(
                        connector=connector,
                        timeout=timeout,
                        headers={'User-Agent': 'K6-MCP-Server/1.0'},
                        compress=self.connection_config.enable_compression
                    )
    
    async def close(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
            self._session = None
        
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
    
    @with_error_handling(component="async_io", operation="stream_read_file")
    async def stream_read_file(
        self,
        file_path: Union[str, Path],
        mode: StreamingMode = StreamingMode.TEXT,
        chunk_size: Optional[int] = None
    ) -> AsyncGenerator[Union[str, bytes, Dict], None]:
        """
        Stream read a file with configurable chunk size and mode.
        
        Args:
            file_path: Path to the file to read
            mode: Streaming mode (text, binary, json_lines, csv)
            chunk_size: Size of chunks to read (uses config default if None)
        
        Yields:
            File content in chunks based on the specified mode
        """
        file_path = Path(file_path)
        chunk_size = chunk_size or self.streaming_config.chunk_size
        
        context = ErrorContext(
            operation="stream_read_file",
            component="async_io",
            metadata={"file_path": str(file_path), "mode": mode.value}
        )
        
        async with self._operation_semaphore:
            if not file_path.exists():
                raise EnhancedError(
                    f"File not found: {file_path}",
                    category=ErrorCategory.FILESYSTEM,
                    context=context
                )
            
            file_size = file_path.stat().st_size
            if file_size > self.streaming_config.max_file_size:
                raise ResourceExhaustionError(
                    f"File too large: {file_size} bytes (max: {self.streaming_config.max_file_size})",
                    context=context,
                    recovery_suggestions=[
                        "Use a smaller file",
                        "Increase max_file_size limit",
                        "Process file in smaller segments"
                    ]
                )
            
            try:
                if mode == StreamingMode.BINARY:
                    async with aiofiles.open(file_path, 'rb') as f:
                        while chunk := await f.read(chunk_size):
                            self._metrics['bytes_read'] += len(chunk)
                            yield chunk
                
                elif mode == StreamingMode.TEXT:
                    async with aiofiles.open(
                        file_path, 'r', 
                        encoding=self.streaming_config.encoding
                    ) as f:
                        while chunk := await f.read(chunk_size):
                            self._metrics['bytes_read'] += len(chunk.encode())
                            yield chunk
                
                elif mode == StreamingMode.JSON_LINES:
                    async with aiofiles.open(
                        file_path, 'r',
                        encoding=self.streaming_config.encoding
                    ) as f:
                        async for line in f:
                            try:
                                data = json.loads(line.strip())
                                self._metrics['bytes_read'] += len(line.encode())
                                yield data
                            except json.JSONDecodeError as e:
                                logger.warning(f"Invalid JSON line: {line.strip()[:100]}...")
                                continue
                
                elif mode == StreamingMode.CSV:
                    async with aiofiles.open(
                        file_path, 'r',
                        encoding=self.streaming_config.encoding
                    ) as f:
                        header = None
                        async for line in f:
                            self._metrics['bytes_read'] += len(line.encode())
                            if header is None:
                                header = [col.strip() for col in line.strip().split(',')]
                                yield {'_header': header}
                            else:
                                values = [val.strip() for val in line.strip().split(',')]
                                if len(values) == len(header):
                                    yield dict(zip(header, values))
                
                self._metrics['files_processed'] += 1
                
            except Exception as e:
                raise EnhancedError(
                    f"Error reading file {file_path}: {str(e)}",
                    category=ErrorCategory.FILESYSTEM,
                    context=context,
                    original_error=e
                )
    
    @with_error_handling(component="async_io", operation="stream_write_file")
    async def stream_write_file(
        self,
        file_path: Union[str, Path],
        content_generator: AsyncGenerator[Union[str, bytes], None],
        mode: StreamingMode = StreamingMode.TEXT,
        append: bool = False
    ) -> int:
        """
        Stream write content to a file.
        
        Args:
            file_path: Path to write to
            content_generator: Async generator providing content chunks
            mode: Writing mode (text or binary)
            append: Whether to append to existing file
        
        Returns:
            Total bytes written
        """
        file_path = Path(file_path)
        write_mode = 'ab' if append and mode == StreamingMode.BINARY else 'rb'
        write_mode = 'a' if append and mode == StreamingMode.TEXT else 'w'
        
        if mode == StreamingMode.BINARY and not append:
            write_mode = 'wb'
        elif mode == StreamingMode.TEXT and not append:
            write_mode = 'w'
        
        context = ErrorContext(
            operation="stream_write_file",
            component="async_io",
            metadata={"file_path": str(file_path), "mode": mode.value, "append": append}
        )
        
        total_bytes = 0
        
        async with self._operation_semaphore:
            try:
                # Ensure parent directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                async with aiofiles.open(
                    file_path, write_mode,
                    encoding=self.streaming_config.encoding if mode == StreamingMode.TEXT else None
                ) as f:
                    async for chunk in content_generator:
                        await f.write(chunk)
                        if isinstance(chunk, str):
                            total_bytes += len(chunk.encode())
                        else:
                            total_bytes += len(chunk)
                
                self._metrics['bytes_written'] += total_bytes
                self._metrics['files_processed'] += 1
                
                return total_bytes
                
            except Exception as e:
                raise EnhancedError(
                    f"Error writing file {file_path}: {str(e)}",
                    category=ErrorCategory.FILESYSTEM,
                    context=context,
                    original_error=e
                )
    
    @with_error_handling(component="async_io", operation="concurrent_file_operations")
    async def concurrent_file_operations(
        self,
        operations: List[Dict[str, Any]],
        max_concurrent: Optional[int] = None
    ) -> List[Any]:
        """
        Execute multiple file operations concurrently.
        
        Args:
            operations: List of operation dictionaries with 'type', 'args', 'kwargs'
            max_concurrent: Max concurrent operations (uses config default if None)
        
        Returns:
            List of operation results
        """
        max_concurrent = max_concurrent or self.streaming_config.max_concurrent_operations
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_operation(op):
            async with semaphore:
                op_type = op['type']
                args = op.get('args', [])
                kwargs = op.get('kwargs', {})
                
                if op_type == 'read':
                    results = []
                    async for chunk in self.stream_read_file(*args, **kwargs):
                        results.append(chunk)
                    return results
                elif op_type == 'write':
                    return await self.stream_write_file(*args, **kwargs)
                else:
                    raise ValueError(f"Unknown operation type: {op_type}")
        
        tasks = [execute_operation(op) for op in operations]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    @with_error_handling(component="async_io", operation="http_request")
    async def http_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Make HTTP request with connection pooling and error handling.
        
        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional request parameters
        
        Returns:
            HTTP response
        """
        await self._ensure_session()
        
        context = ErrorContext(
            operation="http_request",
            component="async_io",
            metadata={"method": method, "url": url}
        )
        
        self._metrics['http_requests'] += 1
        
        try:
            async with self._session.request(method, url, **kwargs) as response:
                return response
        except aiohttp.ClientTimeout as e:
            raise EnhancedError(
                f"HTTP request timeout: {url}",
                category=ErrorCategory.NETWORK,
                context=context,
                recovery_suggestions=[
                    "Increase timeout values",
                    "Check network connectivity",
                    "Verify server availability"
                ],
                original_error=e
            )
        except aiohttp.ClientConnectionError as e:
            raise EnhancedError(
                f"HTTP connection error: {url}",
                category=ErrorCategory.NETWORK,
                context=context,
                recovery_suggestions=[
                    "Check internet connectivity",
                    "Verify URL is correct",
                    "Check for firewall issues"
                ],
                original_error=e
            )
    
    @graceful_degradation(fallback_value=b'')
    async def stream_http_download(
        self,
        url: str,
        file_path: Optional[Union[str, Path]] = None,
        chunk_size: Optional[int] = None
    ) -> Union[bytes, int]:
        """
        Stream download file from HTTP URL.
        
        Args:
            url: URL to download from
            file_path: Local file path to save to (if None, returns content)
            chunk_size: Size of chunks to download
        
        Returns:
            Content bytes if no file_path, otherwise bytes written
        """
        chunk_size = chunk_size or self.streaming_config.chunk_size
        
        async with self.http_request('GET', url) as response:
            response.raise_for_status()
            
            if file_path:
                # Stream to file
                async def content_generator():
                    async for chunk in response.content.iter_chunked(chunk_size):
                        yield chunk
                
                return await self.stream_write_file(
                    file_path, content_generator(), StreamingMode.BINARY
                )
            else:
                # Return content
                content = b''
                async for chunk in response.content.iter_chunked(chunk_size):
                    content += chunk
                return content
    
    async def batch_json_processing(
        self,
        file_paths: List[Union[str, Path]],
        processor_func: callable,
        output_path: Optional[Union[str, Path]] = None
    ) -> List[Any]:
        """
        Process multiple JSON files concurrently with streaming.
        
        Args:
            file_paths: List of JSON file paths to process
            processor_func: Function to process each JSON object
            output_path: Optional path to write results
        
        Returns:
            List of processed results
        """
        results = []
        
        async def process_file(file_path):
            file_results = []
            async for json_obj in self.stream_read_file(file_path, StreamingMode.JSON_LINES):
                try:
                    processed = await processor_func(json_obj) if asyncio.iscoroutinefunction(processor_func) else processor_func(json_obj)
                    file_results.append(processed)
                except Exception as e:
                    logger.warning(f"Error processing JSON object from {file_path}: {e}")
                    continue
            return file_results
        
        # Process files concurrently
        file_tasks = [process_file(fp) for fp in file_paths]
        file_results = await asyncio.gather(*file_tasks, return_exceptions=True)
        
        for result in file_results:
            if isinstance(result, Exception):
                logger.error(f"File processing failed: {result}")
                continue
            results.extend(result)
        
        # Optionally write results to output file
        if output_path:
            async def result_generator():
                for result in results:
                    yield json.dumps(result) + '\n'
            
            await self.stream_write_file(
                output_path, result_generator(), StreamingMode.TEXT
            )
        
        return results
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics."""
        return {
            **self._metrics,
            'session_active': self._session is not None,
            'concurrent_operations_limit': self.streaming_config.max_concurrent_operations,
            'max_file_size_mb': self.streaming_config.max_file_size / (1024 * 1024),
            'connection_pool_size': self.connection_config.max_connections
        }
    
    def reset_metrics(self):
        """Reset performance metrics."""
        for key in self._metrics:
            self._metrics[key] = 0


# Global optimizer instance for easy access
global_async_optimizer = AsyncIOOptimizer()


@asynccontextmanager
async def optimized_io_context(
    streaming_config: Optional[StreamingConfig] = None,
    connection_config: Optional[ConnectionPoolConfig] = None
):
    """Context manager for optimized I/O operations."""
    optimizer = AsyncIOOptimizer(streaming_config, connection_config)
    async with optimizer:
        yield optimizer


# Convenience functions for common operations
async def fast_read_file(file_path: Union[str, Path], mode: StreamingMode = StreamingMode.TEXT) -> List[Any]:
    """Fast file reading with default optimizer."""
    async with global_async_optimizer:
        content = []
        async for chunk in global_async_optimizer.stream_read_file(file_path, mode):
            content.append(chunk)
        return content


async def fast_write_file(
    file_path: Union[str, Path], 
    content: Union[str, bytes, List[str], List[bytes]], 
    mode: StreamingMode = StreamingMode.TEXT
) -> int:
    """Fast file writing with default optimizer."""
    async def content_generator():
        if isinstance(content, (list, tuple)):
            for item in content:
                yield item
        else:
            yield content
    
    async with global_async_optimizer:
        return await global_async_optimizer.stream_write_file(
            file_path, content_generator(), mode
        )


async def concurrent_file_read(file_paths: List[Union[str, Path]]) -> Dict[str, List[Any]]:
    """Read multiple files concurrently."""
    operations = [
        {'type': 'read', 'args': [path]} 
        for path in file_paths
    ]
    
    async with global_async_optimizer:
        results = await global_async_optimizer.concurrent_file_operations(operations)
        return dict(zip([str(p) for p in file_paths], results))