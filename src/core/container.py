"""
Dependency Injection Container for K6 MCP Server.

Provides centralized dependency management and service lifecycle management.
"""

import logging
from typing import Any, Dict, Optional, Type, TypeVar, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceLifetime(Enum):
    """Service lifetime management options."""
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


@dataclass
class ServiceDescriptor:
    """Describes how a service should be instantiated."""
    service_type: Type
    implementation_type: Optional[Type] = None
    factory: Optional[Callable] = None
    lifetime: ServiceLifetime = ServiceLifetime.SINGLETON
    dependencies: list = field(default_factory=list)


class DIContainer:
    """
    Lightweight dependency injection container with service lifetime management.
    
    Features:
    - Service registration with lifetime management
    - Constructor dependency injection
    - Factory methods support
    - Circular dependency detection
    - Service disposal and cleanup
    """
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._instances: Dict[Type, Any] = {}
        self._scoped_instances: Dict[Type, Any] = {}
        self._building_services: set = set()
        
    def register_singleton(self, service_type: Type[T], implementation_type: Optional[Type[T]] = None) -> 'DIContainer':
        """Register a service as singleton (created once and reused)."""
        return self._register(service_type, implementation_type, ServiceLifetime.SINGLETON)
    
    def register_transient(self, service_type: Type[T], implementation_type: Optional[Type[T]] = None) -> 'DIContainer':
        """Register a service as transient (created every time it's requested)."""
        return self._register(service_type, implementation_type, ServiceLifetime.TRANSIENT)
    
    def register_scoped(self, service_type: Type[T], implementation_type: Optional[Type[T]] = None) -> 'DIContainer':
        """Register a service as scoped (created once per scope)."""
        return self._register(service_type, implementation_type, ServiceLifetime.SCOPED)
    
    def register_factory(self, service_type: Type[T], factory: Callable[[], T], lifetime: ServiceLifetime = ServiceLifetime.SINGLETON) -> 'DIContainer':
        """Register a service with a factory method."""
        descriptor = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            lifetime=lifetime
        )
        self._services[service_type] = descriptor
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'DIContainer':
        """Register a pre-created instance as singleton."""
        descriptor = ServiceDescriptor(
            service_type=service_type,
            lifetime=ServiceLifetime.SINGLETON
        )
        self._services[service_type] = descriptor
        self._instances[service_type] = instance
        return self
    
    def resolve(self, service_type: Type[T]) -> T:
        """Resolve a service instance."""
        if service_type in self._building_services:
            raise ValueError(f"Circular dependency detected for {service_type.__name__}")
        
        descriptor = self._services.get(service_type)
        if not descriptor:
            raise ValueError(f"Service {service_type.__name__} is not registered")
        
        # Check for existing instances based on lifetime
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            if service_type in self._instances:
                return self._instances[service_type]
        elif descriptor.lifetime == ServiceLifetime.SCOPED:
            if service_type in self._scoped_instances:
                return self._scoped_instances[service_type]
        
        # Create new instance
        self._building_services.add(service_type)
        try:
            instance = self._create_instance(descriptor)
            
            # Store instance based on lifetime
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                self._instances[service_type] = instance
            elif descriptor.lifetime == ServiceLifetime.SCOPED:
                self._scoped_instances[service_type] = instance
            
            return instance
        finally:
            self._building_services.discard(service_type)
    
    def new_scope(self) -> 'DIScope':
        """Create a new dependency injection scope."""
        return DIScope(self)
    
    def clear_scope(self):
        """Clear all scoped instances."""
        for instance in self._scoped_instances.values():
            if hasattr(instance, 'dispose'):
                try:
                    instance.dispose()
                except Exception as e:
                    logger.warning(f"Error disposing service: {e}")
        self._scoped_instances.clear()
    
    def dispose(self):
        """Dispose all services and clean up resources."""
        # Dispose scoped instances
        self.clear_scope()
        
        # Dispose singletons
        for instance in self._instances.values():
            if hasattr(instance, 'dispose'):
                try:
                    # Check if dispose is async
                    import asyncio
                    if asyncio.iscoroutinefunction(instance.dispose):
                        logger.warning(f"Async dispose method found on {type(instance).__name__}, but container.dispose() is not async")
                    else:
                        instance.dispose()
                except Exception as e:
                    logger.warning(f"Error disposing service: {e}")
        
        self._instances.clear()
        self._services.clear()
    
    def _register(self, service_type: Type[T], implementation_type: Optional[Type[T]], lifetime: ServiceLifetime) -> 'DIContainer':
        """Internal registration method."""
        impl_type = implementation_type or service_type
        descriptor = ServiceDescriptor(
            service_type=service_type,
            implementation_type=impl_type,
            lifetime=lifetime
        )
        self._services[service_type] = descriptor
        return self
    
    def _create_instance(self, descriptor: ServiceDescriptor):
        """Create a service instance using factory or constructor."""
        if descriptor.factory:
            return descriptor.factory()
        
        implementation_type = descriptor.implementation_type or descriptor.service_type
        
        # Get constructor parameters
        try:
            import inspect
            signature = inspect.signature(implementation_type.__init__)
            parameters = list(signature.parameters.values())[1:]  # Skip 'self'
            
            # Resolve dependencies
            args = []
            for param in parameters:
                if param.annotation and param.annotation != inspect.Parameter.empty:
                    dep_instance = self.resolve(param.annotation)
                    args.append(dep_instance)
                elif param.default != inspect.Parameter.empty:
                    continue  # Use default value
                else:
                    raise ValueError(f"Cannot resolve parameter {param.name} for {implementation_type.__name__}")
            
            return implementation_type(*args)
            
        except Exception as e:
            logger.error(f"Error creating instance of {implementation_type.__name__}: {e}")
            # Fallback to parameterless constructor
            return implementation_type()


class DIScope:
    """
    Dependency injection scope for managing scoped service lifetimes.
    """
    
    def __init__(self, container: DIContainer):
        self._container = container
        self._original_scoped = container._scoped_instances.copy()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dispose()
    
    def resolve(self, service_type: Type[T]) -> T:
        """Resolve a service within this scope."""
        return self._container.resolve(service_type)
    
    def dispose(self):
        """Dispose the scope and clean up scoped instances."""
        # Dispose only new scoped instances created in this scope
        current_scoped = self._container._scoped_instances
        for service_type, instance in current_scoped.items():
            if service_type not in self._original_scoped:
                if hasattr(instance, 'dispose'):
                    try:
                        instance.dispose()
                    except Exception as e:
                        logger.warning(f"Error disposing scoped service: {e}")
        
        # Restore original scoped instances
        self._container._scoped_instances = self._original_scoped