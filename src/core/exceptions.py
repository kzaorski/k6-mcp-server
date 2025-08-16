"""
Custom exceptions for K6 MCP Server.

Provides a hierarchy of custom exceptions for better error handling
and debugging throughout the application.
"""

from typing import Any, Dict, Optional


class K6MCPError(Exception):
    """Base exception for all K6 MCP Server errors."""
    
    def __init__(self, message: str, code: str = None, details: Dict[str, Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details
        }


class ValidationError(K6MCPError):
    """Raised when input validation fails."""
    pass


class ConfigurationError(K6MCPError):
    """Raised when configuration is invalid or missing."""
    pass


class ServiceError(K6MCPError):
    """Raised when a service operation fails."""
    pass


class RepositoryError(K6MCPError):
    """Raised when a repository operation fails."""
    pass


class TestExecutionError(K6MCPError):
    """Raised when K6 test execution fails."""
    pass


class WorkflowError(K6MCPError):
    """Raised when workflow execution fails."""
    pass


class ResourceNotFoundError(K6MCPError):
    """Raised when a requested resource is not found."""
    pass


class ResourceExistsError(K6MCPError):
    """Raised when trying to create a resource that already exists."""
    pass


class SecurityError(K6MCPError):
    """Raised when security validation fails."""
    pass


class RateLimitError(K6MCPError):
    """Raised when rate limit is exceeded."""
    pass


class CircuitBreakerError(K6MCPError):
    """Raised when circuit breaker is open."""
    pass