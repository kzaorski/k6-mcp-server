"""
Enhanced Error Handling and Resilience Module for K6 MCP Server.

This module provides comprehensive error handling, retry mechanisms, graceful degradation,
and error recovery strategies for the K6 MCP Server components.
"""

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, Union
import subprocess

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels for handling strategy determination."""
    LOW = "low"           # Log and continue
    MEDIUM = "medium"     # Retry with backoff
    HIGH = "high"         # Retry with fallback
    CRITICAL = "critical" # Immediate escalation


class ErrorCategory(Enum):
    """Categories of errors for specific handling strategies."""
    NETWORK = "network"           # Connection, timeout, DNS issues
    VALIDATION = "validation"     # Input validation, schema errors
    FILESYSTEM = "filesystem"     # File operations, permissions
    SECURITY = "security"         # Security violations, sandboxing
    EXECUTION = "execution"       # Process execution, K6 runtime
    DEPENDENCY = "dependency"     # Missing dependencies, version issues
    RESOURCE = "resource"         # Memory, disk, CPU limits
    CONFIGURATION = "configuration" # Config errors, invalid settings


@dataclass
class ErrorContext:
    """Context information for error handling decisions."""
    operation: str
    component: str
    user_request: Optional[str] = None
    test_id: Optional[str] = None
    attempt_count: int = 1
    max_attempts: int = 3
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class ErrorResult:
    """Result of error handling attempt."""
    success: bool
    error: Optional[Exception] = None
    fallback_used: bool = False
    attempt_count: int = 1
    total_duration: float = 0.0
    message: str = ""


class EnhancedError(Exception):
    """Base enhanced error with context and recovery information."""
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.EXECUTION,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[ErrorContext] = None,
        original_error: Optional[Exception] = None,
        recovery_suggestions: Optional[List[str]] = None
    ):
        super().__init__(message)
        self.category = category
        self.severity = severity
        self.context = context
        self.original_error = original_error
        self.recovery_suggestions = recovery_suggestions or []
        self.timestamp = time.time()
    
    def __str__(self) -> str:
        base_msg = f"[{self.category.value.upper()}] {super().__str__()}"
        if self.recovery_suggestions:
            suggestions = "\n".join(f"  - {s}" for s in self.recovery_suggestions)
            base_msg += f"\n\nRecovery suggestions:\n{suggestions}"
        return base_msg


class NetworkError(EnhancedError):
    """Network-related errors with automatic retry."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.MEDIUM,
            **kwargs
        )


class ValidationError(EnhancedError):
    """Validation errors - typically no retry needed."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            **kwargs
        )


class DependencyError(EnhancedError):
    """Missing dependency errors with fallback suggestions."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.DEPENDENCY,
            severity=ErrorSeverity.HIGH,
            **kwargs
        )


class ResourceExhaustionError(EnhancedError):
    """Resource limit errors with graceful degradation."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.HIGH,
            **kwargs
        )


class ErrorHandler:
    """Centralized error handling with retry, fallback and recovery mechanisms."""
    
    def __init__(self):
        self.error_counts: Dict[str, int] = {}
        self.circuit_breakers: Dict[str, Dict[str, Any]] = {}
        self.fallback_handlers: Dict[ErrorCategory, List[Callable]] = {
            ErrorCategory.NETWORK: [self._network_fallback],
            ErrorCategory.DEPENDENCY: [self._dependency_fallback],
            ErrorCategory.FILESYSTEM: [self._filesystem_fallback],
            ErrorCategory.EXECUTION: [self._execution_fallback],
            ErrorCategory.RESOURCE: [self._resource_fallback],
        }
    
    async def handle_with_retry(
        self,
        operation: Callable,
        context: ErrorContext,
        retry_config: Optional[RetryConfig] = None
    ) -> ErrorResult:
        """
        Execute operation with retry logic and error handling.
        
        Args:
            operation: Async function to execute
            context: Error context for handling decisions
            retry_config: Retry configuration (uses defaults if None)
        
        Returns:
            ErrorResult with success status and details
        """
        if retry_config is None:
            retry_config = RetryConfig()
        
        start_time = time.time()
        last_error = None
        fallback_used = False
        
        for attempt in range(1, retry_config.max_attempts + 1):
            try:
                # Check circuit breaker
                if self._is_circuit_open(context.component):
                    raise EnhancedError(
                        f"Circuit breaker open for {context.component}",
                        category=ErrorCategory.EXECUTION,
                        severity=ErrorSeverity.HIGH,
                        context=context
                    )
                
                # Execute operation
                result = await operation()
                
                # Reset circuit breaker on success
                self._reset_circuit_breaker(context.component)
                
                total_duration = time.time() - start_time
                return ErrorResult(
                    success=True,
                    attempt_count=attempt,
                    total_duration=total_duration,
                    fallback_used=fallback_used,
                    message=f"Operation succeeded on attempt {attempt}"
                )
                
            except Exception as e:
                last_error = e
                
                # Enhance error with context if not already enhanced
                if not isinstance(e, EnhancedError):
                    enhanced_error = self._enhance_error(e, context)
                else:
                    enhanced_error = e
                
                logger.warning(
                    f"Attempt {attempt}/{retry_config.max_attempts} failed for {context.operation}: {enhanced_error}"
                )
                
                # Update error tracking
                self._track_error(context.component, enhanced_error)
                
                # Check if we should retry
                if attempt < retry_config.max_attempts and self._should_retry(enhanced_error):
                    # Calculate delay with exponential backoff and jitter
                    delay = self._calculate_delay(attempt, retry_config)
                    logger.info(f"Retrying in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
                    continue
                
                # Try fallback on final attempt
                if attempt == retry_config.max_attempts:
                    fallback_result = await self._try_fallback(enhanced_error, context)
                    if fallback_result is not None:
                        total_duration = time.time() - start_time
                        return ErrorResult(
                            success=True,
                            attempt_count=attempt,
                            total_duration=total_duration,
                            fallback_used=True,
                            message=f"Fallback succeeded after {attempt} attempts"
                        )
                
                # Circuit breaker logic
                self._update_circuit_breaker(context.component, enhanced_error)
        
        # All attempts failed
        total_duration = time.time() - start_time
        return ErrorResult(
            success=False,
            error=last_error,
            attempt_count=retry_config.max_attempts,
            total_duration=total_duration,
            message=f"All {retry_config.max_attempts} attempts failed"
        )
    
    def _enhance_error(self, error: Exception, context: ErrorContext) -> EnhancedError:
        """Convert regular exception to enhanced error with context."""
        # Determine category and severity based on error type and message
        category, severity = self._categorize_error(error)
        
        # Generate recovery suggestions
        suggestions = self._generate_recovery_suggestions(error, category)
        
        return EnhancedError(
            message=str(error),
            category=category,
            severity=severity,
            context=context,
            original_error=error,
            recovery_suggestions=suggestions
        )
    
    def _categorize_error(self, error: Exception) -> tuple[ErrorCategory, ErrorSeverity]:
        """Categorize error and determine severity."""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # Network errors
        if any(keyword in error_str for keyword in [
            'connection', 'timeout', 'dns', 'network', 'unreachable', 'refused'
        ]) or any(exc_type in error_type for exc_type in [
            'connectionerror', 'timeout', 'networkerror'
        ]):
            return ErrorCategory.NETWORK, ErrorSeverity.MEDIUM
        
        # Validation errors
        if any(keyword in error_str for keyword in [
            'validation', 'invalid', 'malformed', 'schema'
        ]) or 'validationerror' in error_type:
            return ErrorCategory.VALIDATION, ErrorSeverity.LOW
        
        # Filesystem errors
        if any(keyword in error_str for keyword in [
            'file not found', 'permission denied', 'no such file', 'access denied'
        ]) or any(exc_type in error_type for exc_type in [
            'filenotfounderror', 'permissionerror', 'oserror'
        ]):
            return ErrorCategory.FILESYSTEM, ErrorSeverity.MEDIUM
        
        # Security errors
        if any(keyword in error_str for keyword in [
            'security', 'unauthorized', 'forbidden', 'authentication'
        ]):
            return ErrorCategory.SECURITY, ErrorSeverity.HIGH
        
        # Resource errors
        if any(keyword in error_str for keyword in [
            'memory', 'disk space', 'resource', 'limit exceeded'
        ]) or 'memoryerror' in error_type:
            return ErrorCategory.RESOURCE, ErrorSeverity.HIGH
        
        # Dependency errors
        if any(keyword in error_str for keyword in [
            'command not found', 'no such file or directory', 'k6', 'executable'
        ]):
            return ErrorCategory.DEPENDENCY, ErrorSeverity.HIGH
        
        # Default to execution error
        return ErrorCategory.EXECUTION, ErrorSeverity.MEDIUM
    
    def _generate_recovery_suggestions(self, error: Exception, category: ErrorCategory) -> List[str]:
        """Generate contextual recovery suggestions."""
        suggestions = []
        error_str = str(error).lower()
        
        if category == ErrorCategory.NETWORK:
            suggestions.extend([
                "Check internet connectivity and network configuration",
                "Verify target URL is accessible",
                "Consider increasing timeout values",
                "Check for firewall or proxy issues"
            ])
        
        elif category == ErrorCategory.DEPENDENCY:
            if 'k6' in error_str:
                suggestions.extend([
                    "Ensure K6 is installed and available in PATH",
                    "Run 'k6 version' to verify installation",
                    "Install K6 from https://k6.io/docs/getting-started/installation/"
                ])
            else:
                suggestions.extend([
                    "Check if required dependencies are installed",
                    "Verify system PATH configuration",
                    "Install missing dependencies"
                ])
        
        elif category == ErrorCategory.FILESYSTEM:
            suggestions.extend([
                "Check file permissions and ownership",
                "Verify directory structure exists",
                "Ensure sufficient disk space",
                "Check file paths for correctness"
            ])
        
        elif category == ErrorCategory.RESOURCE:
            suggestions.extend([
                "Reduce test load or complexity",
                "Check available system resources",
                "Consider running tests on more powerful hardware",
                "Implement test result streaming to reduce memory usage"
            ])
        
        elif category == ErrorCategory.VALIDATION:
            suggestions.extend([
                "Check input data format and structure",
                "Verify configuration parameters",
                "Review API documentation for correct format"
            ])
        
        return suggestions
    
    def _should_retry(self, error: EnhancedError) -> bool:
        """Determine if error should trigger a retry."""
        # Don't retry validation errors
        if error.category == ErrorCategory.VALIDATION:
            return False
        
        # Don't retry security errors
        if error.category == ErrorCategory.SECURITY:
            return False
        
        # Retry network, filesystem, and execution errors
        if error.category in [ErrorCategory.NETWORK, ErrorCategory.FILESYSTEM, ErrorCategory.EXECUTION]:
            return True
        
        # Retry resource errors with degraded settings
        if error.category == ErrorCategory.RESOURCE:
            return True
        
        # Don't retry dependency errors by default
        return False
    
    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        delay = min(
            config.base_delay * (config.exponential_base ** (attempt - 1)),
            config.max_delay
        )
        
        if config.jitter:
            import random
            delay = delay * (0.5 + 0.5 * random.random())
        
        return delay
    
    async def _try_fallback(self, error: EnhancedError, context: ErrorContext) -> Optional[Any]:
        """Attempt fallback handling for the error."""
        handlers = self.fallback_handlers.get(error.category, [])
        
        for handler in handlers:
            try:
                logger.info(f"Trying fallback handler for {error.category.value}")
                result = await handler(error, context)
                if result is not None:
                    logger.info("Fallback handler succeeded")
                    return result
            except Exception as e:
                logger.warning(f"Fallback handler failed: {e}")
                continue
        
        return None
    
    # Circuit breaker methods
    def _is_circuit_open(self, component: str) -> bool:
        """Check if circuit breaker is open for component."""
        if component not in self.circuit_breakers:
            return False
        
        breaker = self.circuit_breakers[component]
        if breaker['state'] != 'open':
            return False
        
        # Check if we should try half-open
        if time.time() - breaker['opened_at'] > breaker['timeout']:
            breaker['state'] = 'half-open'
            return False
        
        return True
    
    def _update_circuit_breaker(self, component: str, error: EnhancedError):
        """Update circuit breaker state based on error."""
        if component not in self.circuit_breakers:
            self.circuit_breakers[component] = {
                'state': 'closed',
                'failure_count': 0,
                'threshold': 5,
                'timeout': 60,
                'opened_at': None
            }
        
        breaker = self.circuit_breakers[component]
        
        if error.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            breaker['failure_count'] += 1
            
            if breaker['failure_count'] >= breaker['threshold']:
                breaker['state'] = 'open'
                breaker['opened_at'] = time.time()
                logger.warning(f"Circuit breaker opened for {component}")
    
    def _reset_circuit_breaker(self, component: str):
        """Reset circuit breaker on successful operation."""
        if component in self.circuit_breakers:
            self.circuit_breakers[component].update({
                'state': 'closed',
                'failure_count': 0,
                'opened_at': None
            })
    
    def _track_error(self, component: str, error: EnhancedError):
        """Track error frequency for monitoring."""
        key = f"{component}:{error.category.value}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
    
    # Fallback handlers
    async def _network_fallback(self, error: EnhancedError, context: ErrorContext) -> Optional[str]:
        """Fallback for network errors - return cached or degraded response."""
        return f"Network operation failed but continuing with degraded functionality: {error}"
    
    async def _dependency_fallback(self, error: EnhancedError, context: ErrorContext) -> Optional[str]:
        """Fallback for dependency errors - suggest manual steps."""
        if 'k6' in str(error).lower():
            return "K6 not available - please install K6 and ensure it's in your PATH"
        return f"Dependency missing: {error}"
    
    async def _filesystem_fallback(self, error: EnhancedError, context: ErrorContext) -> Optional[str]:
        """Fallback for filesystem errors - try alternative paths."""
        return f"Filesystem operation failed - check permissions and paths: {error}"
    
    async def _execution_fallback(self, error: EnhancedError, context: ErrorContext) -> Optional[str]:
        """Fallback for execution errors - provide degraded results."""
        return f"Execution failed but providing partial results: {error}"
    
    async def _resource_fallback(self, error: EnhancedError, context: ErrorContext) -> Optional[str]:
        """Fallback for resource errors - suggest reduced load."""
        return "Resource limit reached - consider reducing test complexity or virtual users"


def with_error_handling(
    retry_config: Optional[RetryConfig] = None,
    component: str = "unknown",
    operation: str = "operation"
):
    """Decorator for automatic error handling with retry."""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            error_handler = ErrorHandler()
            context = ErrorContext(
                operation=operation,
                component=component
            )
            
            async def execute():
                return await func(*args, **kwargs)
            
            result = await error_handler.handle_with_retry(
                execute, context, retry_config
            )
            
            if not result.success:
                if result.error:
                    raise result.error
                else:
                    raise RuntimeError(result.message)
            
            return result
        
        return wrapper
    return decorator


def graceful_degradation(fallback_value: Any = None, log_error: bool = True):
    """Decorator for graceful degradation - return fallback on error."""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    logger.warning(f"Function {func.__name__} failed gracefully: {e}")
                return fallback_value
        return wrapper
    return decorator


# Global error handler instance
global_error_handler = ErrorHandler()