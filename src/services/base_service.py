"""
Base service implementation with common functionality.

Provides common service patterns including event publishing,
error handling, and lifecycle management.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, TypeVar

from core.base import BaseService, OperationResult
from core.config import AppConfig
from core.events import EventBus, Event, EventType, get_event_bus, publish_event
from core.exceptions import ServiceError, ValidationError

T = TypeVar('T')

logger = logging.getLogger(__name__)


class EnhancedBaseService(BaseService):
    """
    Enhanced base service with event publishing and error handling.
    
    Provides common functionality for all business services including
    event publishing, operation tracking, and standardized error handling.
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.event_bus = get_event_bus()
        self._operation_counter = 0
        self._active_operations: Dict[str, Dict[str, Any]] = {}
    
    async def _initialize_impl(self) -> None:
        """Initialize the enhanced service."""
        await self.publish_event(EventType.CONFIGURATION_LOADED, {
            "service": self.__class__.__name__,
            "config_environment": self.config.environment.value
        })
    
    async def _dispose_impl(self) -> None:
        """Dispose of service resources."""
        # Cancel any active operations
        for operation_id, operation_info in self._active_operations.items():
            if "task" in operation_info:
                task = operation_info["task"]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
        
        self._active_operations.clear()
    
    async def publish_event(self, event_type: EventType, data: Dict[str, Any] = None, correlation_id: str = None) -> None:
        """Publish an event."""
        await publish_event(
            event_type=event_type,
            data=data or {},
            source=self.__class__.__name__
        )
    
    def _generate_operation_id(self) -> str:
        """Generate unique operation ID."""
        self._operation_counter += 1
        return f"{self.__class__.__name__}_{self._operation_counter}_{id(self)}"
    
    async def _track_operation(self, operation_id: str, operation_name: str, **metadata) -> None:
        """Track an active operation."""
        self._active_operations[operation_id] = {
            "name": operation_name,
            "started_at": asyncio.get_event_loop().time(),
            "metadata": metadata
        }
    
    async def _complete_operation(self, operation_id: str, success: bool = True, result: Any = None, error: Exception = None) -> None:
        """Complete an operation."""
        if operation_id in self._active_operations:
            operation_info = self._active_operations.pop(operation_id)
            duration = asyncio.get_event_loop().time() - operation_info["started_at"]
            
            # Log operation completion
            if success:
                self.logger.info(f"Operation {operation_info['name']} completed successfully in {duration:.2f}s")
            else:
                self.logger.error(f"Operation {operation_info['name']} failed after {duration:.2f}s: {error}")
            
            # Publish event
            await self.publish_event(
                EventType.HEALTH_CHECK if success else EventType.TEST_FAILED,
                {
                    "operation_id": operation_id,
                    "operation_name": operation_info['name'],
                    "duration_seconds": duration,
                    "success": success,
                    "error": str(error) if error else None,
                    **operation_info["metadata"]
                }
            )
    
    async def execute_with_tracking(self, operation_name: str, operation_func, **kwargs):
        """Execute an operation with tracking and error handling."""
        operation_id = self._generate_operation_id()
        
        try:
            await self._track_operation(operation_id, operation_name, **kwargs)
            
            # Execute the operation
            if asyncio.iscoroutinefunction(operation_func):
                result = await operation_func()
            else:
                result = operation_func()
            
            await self._complete_operation(operation_id, True, result)
            return result
            
        except Exception as e:
            await self._complete_operation(operation_id, False, error=e)
            raise
    
    def validate_input(self, data: Any, validator_func: callable = None) -> Any:
        """Validate input data."""
        if validator_func:
            try:
                return validator_func(data)
            except Exception as e:
                raise ValidationError(f"Input validation failed: {str(e)}")
        return data
    
    def create_success_result(self, data: T = None, message: str = None, metadata: Dict[str, Any] = None) -> OperationResult[T]:
        """Create a successful operation result."""
        return OperationResult.success_result(data, metadata)
    
    def create_error_result(self, message: str, error_code: str = None, metadata: Dict[str, Any] = None) -> OperationResult[None]:
        """Create an error operation result."""
        return OperationResult.error_result(message, error_code, metadata)
    
    async def safe_execute(self, operation_func, *args, **kwargs) -> OperationResult[Any]:
        """Safely execute an operation with standardized error handling."""
        try:
            if asyncio.iscoroutinefunction(operation_func):
                result = await operation_func(*args, **kwargs)
            else:
                result = operation_func(*args, **kwargs)
            
            return self.create_success_result(result)
            
        except ValidationError as e:
            self.logger.warning(f"Validation error in {operation_func.__name__}: {e}")
            return self.create_error_result(str(e), "VALIDATION_ERROR")
        
        except ServiceError as e:
            self.logger.error(f"Service error in {operation_func.__name__}: {e}")
            return self.create_error_result(str(e), e.code)
        
        except Exception as e:
            self.logger.error(f"Unexpected error in {operation_func.__name__}: {e}", exc_info=True)
            return self.create_error_result(f"Operation failed: {str(e)}", "INTERNAL_ERROR")
    
    def get_active_operations(self) -> Dict[str, Dict[str, Any]]:
        """Get information about active operations."""
        current_time = asyncio.get_event_loop().time()
        return {
            operation_id: {
                **info,
                "duration_seconds": current_time - info["started_at"]
            }
            for operation_id, info in self._active_operations.items()
        }
    
    async def health_check_impl(self) -> Dict[str, Any]:
        """Implementation-specific health check (override in subclasses)."""
        return {
            "status": "healthy",
            "active_operations": len(self._active_operations),
            "total_operations": self._operation_counter
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        base_health = {
            "service": self.__class__.__name__,
            "initialized": self._initialized,
            "active_operations": len(self._active_operations)
        }
        
        impl_health = await self.health_check_impl()
        return {**base_health, **impl_health}