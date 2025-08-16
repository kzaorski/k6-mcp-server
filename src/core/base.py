"""
Base classes and abstractions for K6 MCP Server.

Provides common base classes with shared functionality for services,
repositories, and handlers.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar, Generic
from dataclasses import dataclass
from datetime import datetime

from .config import AppConfig

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class OperationResult(Generic[T]):
    """
    Standard result container for operations.
    
    Provides consistent error handling and success/failure indication.
    """
    success: bool
    data: Optional[T] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    @classmethod
    def success_result(cls, data: T = None, metadata: Dict[str, Any] = None) -> 'OperationResult[T]':
        """Create a successful operation result."""
        return cls(success=True, data=data, metadata=metadata or {})
    
    @classmethod
    def error_result(cls, error_message: str, error_code: str = None, metadata: Dict[str, Any] = None) -> 'OperationResult[T]':
        """Create a failed operation result."""
        return cls(
            success=False,
            error_message=error_message,
            error_code=error_code,
            metadata=metadata or {}
        )


class BaseService(ABC):
    """
    Base class for all services.
    
    Provides common functionality like configuration access,
    logging, and lifecycle management.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the service. Override in derived classes."""
        if self._initialized:
            return
        
        self.logger.info(f"Initializing {self.__class__.__name__}")
        await self._initialize_impl()
        self._initialized = True
        self.logger.info(f"{self.__class__.__name__} initialized successfully")
    
    async def _initialize_impl(self) -> None:
        """Override this method to implement service-specific initialization."""
        pass
    
    async def dispose(self) -> None:
        """Dispose of resources. Override in derived classes."""
        if not self._initialized:
            return
        
        self.logger.info(f"Disposing {self.__class__.__name__}")
        await self._dispose_impl()
        self._initialized = False
        self.logger.info(f"{self.__class__.__name__} disposed")
    
    async def _dispose_impl(self) -> None:
        """Override this method to implement service-specific cleanup."""
        pass
    
    def ensure_initialized(self) -> None:
        """Ensure the service is initialized."""
        if not self._initialized:
            raise RuntimeError(f"{self.__class__.__name__} is not initialized. Call initialize() first.")


class BaseRepository(ABC, Generic[T]):
    """
    Base class for repositories.
    
    Provides common CRUD operations and data access patterns.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def get_by_id(self, id: str) -> Optional[T]:
        """Get entity by ID."""
        pass
    
    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        """Get all entities with pagination."""
        pass
    
    @abstractmethod
    async def create(self, entity: T) -> OperationResult[T]:
        """Create new entity."""
        pass
    
    @abstractmethod
    async def update(self, id: str, entity: T) -> OperationResult[T]:
        """Update existing entity."""
        pass
    
    @abstractmethod
    async def delete(self, id: str) -> OperationResult[bool]:
        """Delete entity by ID."""
        pass
    
    async def exists(self, id: str) -> bool:
        """Check if entity exists."""
        entity = await self.get_by_id(id)
        return entity is not None


class BaseHandler(ABC):
    """
    Base class for request handlers.
    
    Provides common functionality for handling MCP tool calls
    and managing request/response cycles.
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def handle(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a tool call."""
        pass
    
    def create_success_response(self, content: str) -> Dict[str, Any]:
        """Create a successful response."""
        return {
            "content": [
                {"type": "text", "text": content}
            ]
        }
    
    def create_error_response(self, message: str, is_error: bool = True) -> Dict[str, Any]:
        """Create an error response."""
        return {
            "content": [
                {"type": "text", "text": message}
            ],
            "isError": is_error
        }
    
    def log_operation_start(self, operation: str, **kwargs) -> str:
        """Log the start of an operation and return operation ID."""
        operation_id = f"{operation}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        self.logger.info(f"Starting operation {operation_id}: {operation}", extra=kwargs)
        return operation_id
    
    def log_operation_end(self, operation_id: str, success: bool, **kwargs) -> None:
        """Log the end of an operation."""
        status = "SUCCESS" if success else "FAILURE"
        self.logger.info(f"Operation {operation_id} completed: {status}", extra=kwargs)
    
    def log_operation_error(self, operation_id: str, error: Exception, **kwargs) -> None:
        """Log an operation error."""
        self.logger.error(f"Operation {operation_id} failed: {error}", exc_info=True, extra=kwargs)


class Disposable(ABC):
    """
    Interface for disposable resources.
    """
    
    @abstractmethod
    async def dispose(self) -> None:
        """Dispose of resources."""
        pass


class Singleton:
    """
    Mixin class for singleton pattern implementation.
    """
    
    _instances = {}
    
    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__new__(cls)
        return cls._instances[cls]


@dataclass
class HealthCheck:
    """Health check result."""
    component: str
    status: str  # "healthy", "unhealthy", "degraded"
    message: Optional[str] = None
    timestamp: datetime = None
    duration_ms: Optional[float] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class HealthCheckProvider(ABC):
    """
    Interface for components that can provide health checks.
    """
    
    @abstractmethod
    async def health_check(self) -> HealthCheck:
        """Perform health check and return result."""
        pass