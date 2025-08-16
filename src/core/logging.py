"""
Enhanced logging and monitoring for K6 MCP Server.

Provides structured logging, metrics collection, and monitoring capabilities
with support for different environments and output formats.
"""

import json
import logging
import logging.handlers
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from .config import AppConfig, LogLevel, Environment


class LogEventType(str, Enum):
    """Types of log events for structured logging."""
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    PERFORMANCE = "performance"
    SECURITY = "security"
    AUDIT = "audit"
    HEALTH = "health"
    BUSINESS = "business"


@dataclass
class LogContext:
    """Context information for structured logging."""
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    operation: Optional[str] = None
    component: Optional[str] = None
    test_id: Optional[str] = None
    workflow_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class PerformanceMetrics:
    """Performance metrics for monitoring."""
    operation: str
    duration_ms: float
    success: bool
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "operation": self.operation,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


class StructuredLogger:
    """
    Structured logger with JSON output support.
    
    Provides structured logging with consistent format and
    context enrichment for better observability.
    """
    
    def __init__(self, name: str, config: AppConfig):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(name)
        self._context: LogContext = LogContext()
    
    def set_context(self, context: LogContext) -> None:
        """Set logging context."""
        self._context = context
    
    def update_context(self, **kwargs) -> None:
        """Update logging context with new values."""
        for key, value in kwargs.items():
            if hasattr(self._context, key):
                setattr(self._context, key, value)
    
    @contextmanager
    def context(self, **kwargs):
        """Context manager for temporary context updates."""
        original_context = LogContext(**self._context.__dict__)
        try:
            self.update_context(**kwargs)
            yield
        finally:
            self._context = original_context
    
    def _log_structured(self, level: int, event_type: LogEventType, message: str, **kwargs):
        """Log structured message."""
        if self.config.logging.enable_structured_logging:
            log_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": logging.getLevelName(level),
                "event_type": event_type.value,
                "message": message,
                "logger": self.name,
                "context": self._context.to_dict(),
                **kwargs
            }
            
            # Log as JSON
            self.logger.log(level, json.dumps(log_data))
        else:
            # Log as regular text with context
            context_str = ""
            if self._context.request_id:
                context_str += f"[req:{self._context.request_id}] "
            if self._context.operation:
                context_str += f"[op:{self._context.operation}] "
            if self._context.component:
                context_str += f"[comp:{self._context.component}] "
            
            full_message = f"{context_str}{message}"
            if kwargs:
                full_message += f" | {kwargs}"
            
            self.logger.log(level, full_message)
    
    def debug(self, message: str, event_type: LogEventType = LogEventType.BUSINESS, **kwargs):
        """Log debug message."""
        self._log_structured(logging.DEBUG, event_type, message, **kwargs)
    
    def info(self, message: str, event_type: LogEventType = LogEventType.BUSINESS, **kwargs):
        """Log info message."""
        self._log_structured(logging.INFO, event_type, message, **kwargs)
    
    def warning(self, message: str, event_type: LogEventType = LogEventType.BUSINESS, **kwargs):
        """Log warning message."""
        self._log_structured(logging.WARNING, event_type, message, **kwargs)
    
    def error(self, message: str, event_type: LogEventType = LogEventType.ERROR, **kwargs):
        """Log error message."""
        self._log_structured(logging.ERROR, event_type, message, **kwargs)
    
    def critical(self, message: str, event_type: LogEventType = LogEventType.ERROR, **kwargs):
        """Log critical message."""
        self._log_structured(logging.CRITICAL, event_type, message, **kwargs)
    
    def audit(self, message: str, **kwargs):
        """Log audit event."""
        self._log_structured(logging.INFO, LogEventType.AUDIT, message, **kwargs)
    
    def security(self, message: str, **kwargs):
        """Log security event."""
        self._log_structured(logging.WARNING, LogEventType.SECURITY, message, **kwargs)
    
    def performance(self, metrics: PerformanceMetrics):
        """Log performance metrics."""
        self._log_structured(
            logging.INFO, 
            LogEventType.PERFORMANCE, 
            f"Operation {metrics.operation} completed",
            metrics=metrics.to_dict()
        )
    
    def request(self, method: str, url: str, **kwargs):
        """Log request event."""
        self._log_structured(
            logging.INFO,
            LogEventType.REQUEST,
            f"{method} {url}",
            method=method,
            url=url,
            **kwargs
        )
    
    def response(self, status_code: int, duration_ms: float, **kwargs):
        """Log response event."""
        self._log_structured(
            logging.INFO,
            LogEventType.RESPONSE,
            f"Response {status_code}",
            status_code=status_code,
            duration_ms=duration_ms,
            **kwargs
        )


class MetricsCollector:
    """
    Metrics collector for monitoring and observability.
    
    Collects and aggregates metrics for performance monitoring
    and system health tracking.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.metrics: List[PerformanceMetrics] = []
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
    
    def record_performance(self, metrics: PerformanceMetrics) -> None:
        """Record performance metrics."""
        self.metrics.append(metrics)
        
        # Keep only recent metrics (last 1000)
        if len(self.metrics) > 1000:
            self.metrics = self.metrics[-1000:]
    
    def increment_counter(self, name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        self._counters[name] = self._counters.get(name, 0) + value
    
    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge metric."""
        self._gauges[name] = value
    
    def record_histogram(self, name: str, value: float) -> None:
        """Record a histogram value."""
        if name not in self._histograms:
            self._histograms[name] = []
        
        self._histograms[name].append(value)
        
        # Keep only recent values (last 1000)
        if len(self._histograms[name]) > 1000:
            self._histograms[name] = self._histograms[name][-1000:]
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all metrics."""
        recent_metrics = [m for m in self.metrics if (datetime.utcnow() - m.timestamp).seconds < 3600]
        
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
            "performance": {
                "total_operations": len(recent_metrics),
                "successful_operations": sum(1 for m in recent_metrics if m.success),
                "failed_operations": sum(1 for m in recent_metrics if not m.success),
                "average_duration_ms": sum(m.duration_ms for m in recent_metrics) / len(recent_metrics) if recent_metrics else 0
            }
        }
        
        # Histogram statistics
        for name, values in self._histograms.items():
            if values:
                sorted_values = sorted(values)
                count = len(sorted_values)
                summary["histograms"][name] = {
                    "count": count,
                    "min": min(sorted_values),
                    "max": max(sorted_values),
                    "avg": sum(sorted_values) / count,
                    "p50": sorted_values[count // 2],
                    "p95": sorted_values[int(count * 0.95)] if count > 1 else sorted_values[0],
                    "p99": sorted_values[int(count * 0.99)] if count > 1 else sorted_values[0]
                }
        
        return summary
    
    def clear_metrics(self) -> None:
        """Clear all metrics."""
        self.metrics.clear()
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


class LoggingManager:
    """
    Central logging manager for the application.
    
    Configures and manages all logging components including
    structured logging, metrics collection, and monitoring.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.metrics_collector = MetricsCollector(config)
        self._loggers: Dict[str, StructuredLogger] = {}
        
        # Configure root logging
        self._configure_root_logging()
    
    def get_logger(self, name: str) -> StructuredLogger:
        """Get or create a structured logger."""
        if name not in self._loggers:
            self._loggers[name] = StructuredLogger(name, self.config)
        return self._loggers[name]
    
    def _configure_root_logging(self) -> None:
        """Configure root Python logging."""
        # Clear existing handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Set logging level
        log_level = getattr(logging, self.config.logging.level.value)
        root_logger.setLevel(log_level)
        
        # Create formatter
        if self.config.logging.enable_structured_logging:
            formatter = logging.Formatter('%(message)s')  # JSON will be in message
        else:
            formatter = logging.Formatter(self.config.logging.format)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # File handler if specified
        if self.config.logging.file_path:
            try:
                file_handler = logging.handlers.RotatingFileHandler(
                    self.config.logging.file_path,
                    maxBytes=self.config.logging.max_file_size,
                    backupCount=self.config.logging.backup_count
                )
                file_handler.setLevel(log_level)
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
            except Exception as e:
                # Fallback to console only
                root_logger.error(f"Failed to configure file logging: {e}")
    
    @contextmanager
    def operation_context(self, operation: str, component: str = None, **kwargs):
        """Context manager for operation tracking."""
        start_time = time.time()
        context = LogContext(operation=operation, component=component, **kwargs)
        
        # Set context for all loggers
        for logger in self._loggers.values():
            logger.set_context(context)
        
        success = True
        error = None
        
        try:
            yield context
        except Exception as e:
            success = False
            error = e
            raise
        finally:
            # Record performance metrics
            duration_ms = (time.time() - start_time) * 1000
            metrics = PerformanceMetrics(
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                metadata={
                    "component": component,
                    "error": str(error) if error else None,
                    **kwargs
                }
            )
            
            self.metrics_collector.record_performance(metrics)
            
            # Log performance
            logger = self.get_logger(component or "app")
            logger.performance(metrics)
            
            # Clear context
            for logger in self._loggers.values():
                logger.set_context(LogContext())
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        return self.metrics_collector.get_metrics_summary()
    
    def health_check(self) -> Dict[str, Any]:
        """Perform logging system health check."""
        try:
            # Test logging
            test_logger = self.get_logger("health_check")
            test_logger.info("Health check test message")
            
            # Check file handler if configured
            file_accessible = True
            if self.config.logging.file_path:
                try:
                    with open(self.config.logging.file_path, 'a') as f:
                        pass
                except Exception:
                    file_accessible = False
            
            metrics = self.get_metrics_summary()
            
            return {
                "status": "healthy" if file_accessible else "degraded",
                "file_logging": file_accessible,
                "recent_metrics_count": metrics["performance"]["total_operations"],
                "loggers_count": len(self._loggers),
                "message": "Logging system operational" if file_accessible else "File logging unavailable"
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "message": "Logging system error"
            }


def setup_logging(config: AppConfig) -> LoggingManager:
    """Setup logging for the application."""
    return LoggingManager(config)


# Global logging manager instance
_logging_manager: Optional[LoggingManager] = None


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    global _logging_manager
    if _logging_manager is None:
        raise RuntimeError("Logging not initialized. Call setup_logging() first.")
    return _logging_manager.get_logger(name)


def initialize_logging(config: AppConfig) -> None:
    """Initialize global logging."""
    global _logging_manager
    _logging_manager = setup_logging(config)