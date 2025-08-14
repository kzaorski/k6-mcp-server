"""
Security decorators for K6 MCP Server tool handlers.

This module provides decorators for adding security checks to tool handlers.
"""

import functools
import logging
from typing import Any, Callable, Dict, Optional

from security_config import SecurityConfig, AuditLogger
from security_utils import (
    RateLimiter,
    generate_request_id,
    mask_sensitive_data,
    SecurityError
)

logger = logging.getLogger(__name__)


def with_security_checks(
    rate_limiter: Optional[RateLimiter] = None,
    audit_logger: Optional[AuditLogger] = None,
    require_auth: bool = False,
    mask_sensitive: bool = True
):
    """
    Decorator to add security checks to tool handlers.
    
    Args:
        rate_limiter: Rate limiter instance
        audit_logger: Audit logger instance
        require_auth: Whether to require authentication
        mask_sensitive: Whether to mask sensitive data in logs
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            request_id = generate_request_id()
            tool_name = func.__name__
            
            try:
                # Extract arguments for logging (first arg is usually the config)
                if args and hasattr(args[0], 'dict'):
                    config_dict = args[0].dict() if hasattr(args[0], 'dict') else {}
                    if mask_sensitive:
                        config_dict = mask_sensitive_data(config_dict)
                else:
                    config_dict = {}
                
                # Log the tool invocation
                logger.info(f"[{request_id}] Tool invoked: {tool_name}")
                
                # Check rate limiting
                if rate_limiter:
                    # Use tool name as identifier (in production, use user ID)
                    if not rate_limiter.is_allowed(tool_name):
                        error_msg = f"Rate limit exceeded for {tool_name}"
                        logger.warning(f"[{request_id}] {error_msg}")
                        
                        if audit_logger:
                            audit_logger.log_rate_limit_exceeded(tool_name)
                        
                        raise SecurityError(error_msg)
                
                # Check authentication (placeholder for future implementation)
                if require_auth and SecurityConfig.AUTH_ENABLED:
                    # In production, extract and validate auth token
                    auth_token = kwargs.get('auth_token') or ''
                    if auth_token != SecurityConfig.AUTH_TOKEN:
                        error_msg = "Authentication required"
                        logger.warning(f"[{request_id}] Authentication failed for {tool_name}")
                        
                        if audit_logger:
                            audit_logger.log_authentication_attempt(success=False)
                        
                        raise SecurityError(error_msg)
                
                # Log to audit log
                if audit_logger and tool_name in ['run_k6_test', 'run_k6_multi_request_test']:
                    test_id = config_dict.get('test_id') or kwargs.get('test_id') or request_id
                    audit_logger.log_test_execution(test_id, config_dict)
                
                # Execute the actual function
                result = await func(*args, **kwargs)
                
                # Log successful execution
                logger.info(f"[{request_id}] Tool completed successfully: {tool_name}")
                
                return result
                
            except SecurityError:
                # Re-raise security errors
                raise
            except Exception as e:
                # Log errors
                logger.error(f"[{request_id}] Error in {tool_name}: {str(e)}")
                
                if audit_logger:
                    audit_logger.log_error(
                        error_type=type(e).__name__,
                        error_message=str(e),
                        test_id=request_id
                    )
                
                # Re-raise the original exception
                raise
        
        return wrapper
    
    return decorator


def validate_input(validation_func: Callable[[Any], Any]):
    """
    Decorator to validate input parameters.
    
    Args:
        validation_func: Function to validate and sanitize input
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                # Validate first argument (usually the config)
                if args:
                    validated_args = list(args)
                    validated_args[0] = validation_func(args[0])
                    args = tuple(validated_args)
                
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Input validation failed for {func.__name__}: {str(e)}")
                raise
        
        return wrapper
    
    return decorator


def require_confirmation(confirmation_required: bool = True):
    """
    Decorator to require user confirmation before executing.
    
    Args:
        confirmation_required: Whether confirmation is required
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if confirmation_required and SecurityConfig.REQUIRE_TEST_CONFIRMATION:
                # Check if confirmation was provided
                confirmed = kwargs.get('confirmed', False)
                if not confirmed:
                    # Return a message indicating confirmation is needed
                    return {
                        'requires_confirmation': True,
                        'message': 'This action requires confirmation. Please confirm to proceed.'
                    }
            
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def sanitize_output(func: Callable) -> Callable:
    """
    Decorator to sanitize output by masking sensitive data.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        
        # If result is a dictionary, mask sensitive data
        if isinstance(result, dict):
            return mask_sensitive_data(result)
        
        return result
    
    return wrapper