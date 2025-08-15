"""
Security utilities for K6 MCP Server.

This module provides security functions for input validation, sanitization,
and protection against common vulnerabilities.
"""

import re
import json
import hashlib
import secrets
import subprocess
import platform
from pathlib import Path
from typing import List, Dict, Any, Optional

# Import resource module only on Unix systems
try:
    import resource
    RESOURCE_AVAILABLE = True
except ImportError:
    # resource module is not available on Windows
    RESOURCE_AVAILABLE = False
    resource = None
from typing import Any, Dict, List, Optional, Union
from functools import wraps
import asyncio
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Base exception for security-related errors."""
    pass


class InputValidationError(SecurityError):
    """Exception raised when input validation fails."""
    pass


class PathTraversalError(SecurityError):
    """Exception raised when path traversal is detected."""
    pass


class InjectionError(SecurityError):
    """Exception raised when injection attempt is detected."""
    pass


class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = {}
        self._cleanup_task = None
    
    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed for given identifier."""
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.window_seconds)
        
        # Clean old entries
        if identifier in self.requests:
            self.requests[identifier] = [
                req_time for req_time in self.requests[identifier]
                if req_time > window_start
            ]
        
        # Check rate limit
        if identifier not in self.requests:
            self.requests[identifier] = []
        
        if len(self.requests[identifier]) >= self.max_requests:
            return False
        
        self.requests[identifier].append(now)
        return True
    
    async def cleanup_old_entries(self):
        """Periodically clean old entries."""
        while True:
            await asyncio.sleep(self.window_seconds)
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=self.window_seconds)
            
            for identifier in list(self.requests.keys()):
                self.requests[identifier] = [
                    req_time for req_time in self.requests.get(identifier, [])
                    if req_time > window_start
                ]
                if not self.requests[identifier]:
                    del self.requests[identifier]


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """
    Sanitize filename to prevent injection attacks.
    
    Args:
        filename: The filename to sanitize
        max_length: Maximum allowed length
    
    Returns:
        Sanitized filename
    
    Raises:
        InputValidationError: If filename contains invalid characters
    """
    if not filename:
        raise InputValidationError("Filename cannot be empty")
    
    # Allow only alphanumeric, underscore, hyphen, and dot
    if not re.match(r'^[a-zA-Z0-9_.-]+$', filename):
        raise InputValidationError(
            f"Invalid filename '{filename}'. Only alphanumeric, underscore, "
            "hyphen, and dot characters are allowed."
        )
    
    # Prevent directory traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        raise InputValidationError("Directory traversal attempt detected")
    
    # Limit length
    if len(filename) > max_length:
        raise InputValidationError(f"Filename exceeds maximum length of {max_length}")
    
    # Prevent special files
    dangerous_names = {
        'con', 'prn', 'aux', 'nul', 'com1', 'com2', 'com3', 'com4',
        'com5', 'com6', 'com7', 'com8', 'com9', 'lpt1', 'lpt2', 'lpt3',
        'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9'
    }
    
    base_name = filename.lower().split('.')[0]
    if base_name in dangerous_names:
        raise InputValidationError(f"Reserved filename '{filename}' not allowed")
    
    return filename


def validate_safe_path(file_path: Union[str, Path], allowed_base: Path) -> Path:
    """
    Validate that a path is within the allowed directory.
    
    Args:
        file_path: Path to validate
        allowed_base: Base directory that must contain the path
    
    Returns:
        Resolved safe path
    
    Raises:
        PathTraversalError: If path is outside allowed directory
    """
    try:
        # Resolve to absolute paths
        resolved_path = Path(file_path).resolve()
        allowed_base = allowed_base.resolve()
        
        # Check if path is within allowed base
        if not str(resolved_path).startswith(str(allowed_base)):
            raise PathTraversalError(
                f"Path '{file_path}' is outside allowed directory '{allowed_base}'"
            )
        
        return resolved_path
    
    except Exception as e:
        if isinstance(e, PathTraversalError):
            raise
        raise PathTraversalError(f"Invalid path '{file_path}': {str(e)}")


def sanitize_url(url: str, allowed_schemes: List[str] = None) -> str:
    """
    Sanitize and validate URL.
    
    Args:
        url: URL to sanitize
        allowed_schemes: List of allowed URL schemes (default: ['http', 'https'])
    
    Returns:
        Sanitized URL
    
    Raises:
        InputValidationError: If URL is invalid or uses disallowed scheme
    """
    from urllib.parse import urlparse, urlunparse
    
    if allowed_schemes is None:
        allowed_schemes = ['http', 'https']
    
    if not url:
        raise InputValidationError("URL cannot be empty")
    
    try:
        parsed = urlparse(url)
        
        # Check scheme
        if parsed.scheme not in allowed_schemes:
            raise InputValidationError(
                f"URL scheme '{parsed.scheme}' not allowed. "
                f"Allowed schemes: {allowed_schemes}"
            )
        
        # Check for common injection patterns
        dangerous_patterns = [
            'javascript:', 'data:', 'vbscript:', 'file:', 'about:', 'chrome:'
        ]
        
        lower_url = url.lower()
        for pattern in dangerous_patterns:
            if pattern in lower_url:
                raise InputValidationError(f"Dangerous URL pattern detected: {pattern}")
        
        # Rebuild URL to ensure it's properly formatted
        clean_url = urlunparse(parsed)
        return clean_url
    
    except Exception as e:
        if isinstance(e, InputValidationError):
            raise
        raise InputValidationError(f"Invalid URL '{url}': {str(e)}")


def safe_json_string(value: Any) -> str:
    """
    Safely encode value for JavaScript/JSON context.
    
    Args:
        value: Value to encode
    
    Returns:
        JSON-encoded string safe for JavaScript context
    """
    # JSON encoding handles escaping for JavaScript context
    return json.dumps(str(value) if value is not None else "")


def sanitize_javascript_template(template: str, variables: Dict[str, Any]) -> str:
    """
    Safely interpolate variables into JavaScript template.
    
    Args:
        template: JavaScript template with {{variable}} placeholders
        variables: Dictionary of variables to interpolate
    
    Returns:
        Template with safely interpolated variables
    """
    result = template
    
    for key, value in variables.items():
        placeholder = f"{{{{{key}}}}}"
        if placeholder in result:
            # Safely encode the value for JavaScript context
            safe_value = safe_json_string(value)
            result = result.replace(placeholder, safe_value)
    
    return result


def sanitize_csv_cell(value: Any) -> str:
    """
    Sanitize CSV cell value to prevent injection attacks.
    
    Args:
        value: Cell value to sanitize
    
    Returns:
        Sanitized cell value
    """
    if value is None:
        return ""
    
    str_value = str(value)
    
    # Dangerous prefixes that could execute formulas
    dangerous_prefixes = ('=', '+', '-', '@', '\t', '\r', '\n', '|')
    
    if str_value and str_value[0] in dangerous_prefixes:
        # Prefix with single quote to neutralize formula
        return "'" + str_value
    
    return str_value


def safe_json_parse(json_str: str, max_size: int = 10_000_000) -> Dict[str, Any]:
    """
    Safely parse JSON with size limits.
    
    Args:
        json_str: JSON string to parse
        max_size: Maximum allowed size in bytes
    
    Returns:
        Parsed JSON object
    
    Raises:
        InputValidationError: If JSON is too large or invalid
    """
    if not json_str:
        raise InputValidationError("JSON string cannot be empty")
    
    # Check size
    if len(json_str) > max_size:
        raise InputValidationError(
            f"JSON payload size {len(json_str)} exceeds maximum {max_size}"
        )
    
    try:
        # Parse with strict mode
        return json.loads(json_str, strict=True)
    except json.JSONDecodeError as e:
        raise InputValidationError(f"Invalid JSON: {str(e)}")
    except RecursionError:
        raise InputValidationError("JSON structure too deeply nested")


def mask_sensitive_data(data: Dict[str, Any], sensitive_keys: List[str] = None) -> Dict[str, Any]:
    """
    Mask sensitive data in dictionary.
    
    Args:
        data: Dictionary potentially containing sensitive data
        sensitive_keys: List of keys to mask (default: common sensitive keys)
    
    Returns:
        Dictionary with masked sensitive values
    """
    if sensitive_keys is None:
        sensitive_keys = [
            'password', 'token', 'secret', 'key', 'api_key', 'apikey',
            'auth', 'authorization', 'credential', 'private'
        ]
    
    masked_data = {}
    
    for key, value in data.items():
        # Check if key contains sensitive word
        is_sensitive = any(
            sensitive_word in key.lower() 
            for sensitive_word in sensitive_keys
        )
        
        if is_sensitive:
            masked_data[key] = "***REDACTED***"
        elif isinstance(value, dict):
            # Recursively mask nested dictionaries
            masked_data[key] = mask_sensitive_data(value, sensitive_keys)
        else:
            masked_data[key] = value
    
    return masked_data


def _get_safe_environment() -> Dict[str, str]:
    """Get a safe environment for subprocess execution that works cross-platform."""
    import platform
    import os
    
    # Base safe environment
    safe_env = {
        'LANG': 'C.UTF-8' if platform.system() != 'Windows' else 'en_US',
    }
    
    # Platform-specific PATH handling
    if platform.system() == 'Windows':
        # On Windows, preserve system PATH but sanitize it
        system_path = os.environ.get('PATH', '')
        # Keep Windows system paths and add common tool locations
        safe_paths = [
            r'C:\Windows\system32',
            r'C:\Windows',
            r'C:\Windows\System32\Wbem',
            r'C:\Windows\System32\WindowsPowerShell\v1.0',
        ]
        
        # Add existing PATH but filter out suspicious entries
        for path in system_path.split(';'):
            path = path.strip()
            if path and not any(suspicious in path.lower() for suspicious in ['temp', 'tmp', 'appdata']):
                safe_paths.append(path)
        
        safe_env['PATH'] = ';'.join(safe_paths)
        safe_env['SYSTEMROOT'] = os.environ.get('SYSTEMROOT', r'C:\Windows')
        safe_env['TEMP'] = os.environ.get('TEMP', r'C:\Windows\Temp')
        safe_env['TMP'] = os.environ.get('TMP', r'C:\Windows\Temp')
        
    else:
        # Linux/Unix
        safe_env.update({
            'PATH': '/usr/local/bin:/usr/bin:/bin',
            'HOME': '/tmp'
        })
    
    return safe_env


def run_sandboxed_command(
    cmd: List[str],
    timeout: int = 3600,
    max_memory_mb: int = 2048,
    max_cpu_seconds: int = 1800,
    working_dir: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    """
    Run command with resource limits and sandboxing.
    
    Args:
        cmd: Command to run as list of arguments
        timeout: Maximum execution time in seconds
        max_memory_mb: Maximum memory in megabytes
        max_cpu_seconds: Maximum CPU time in seconds
        working_dir: Working directory for command
        env: Optional environment variables to add to the safe environment
    
    Returns:
        Completed process result
    
    Raises:
        SecurityError: If command execution fails or exceeds limits
    """
    def limit_resources():
        """Set resource limits for subprocess."""
        if not RESOURCE_AVAILABLE:
            # Resource limiting not available on Windows
            logger.warning("Resource limiting not available on this platform (Windows)")
            return
            
        # Limit CPU time
        resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds))
        
        # Limit memory (convert MB to bytes)
        max_memory_bytes = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
        
        # Limit number of file descriptors
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        
        # Limit number of processes
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    
    try:
        # Sanitize command arguments
        safe_cmd = []
        for arg in cmd:
            if not isinstance(arg, str):
                raise SecurityError(f"Command argument must be string, got {type(arg)}")
            # Basic check for shell metacharacters
            if any(char in arg for char in ['&', '|', ';', '$', '`', '\n', '\r']):
                logger.warning(f"Potentially dangerous character in command argument: {arg}")
            safe_cmd.append(arg)
        
        # Prepare environment
        safe_env = _get_safe_environment()
        if env:
            # Merge provided environment variables with safe environment
            safe_env.update(env)
        
        # Run with limits
        result = subprocess.run(
            safe_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=working_dir,
            preexec_fn=limit_resources if RESOURCE_AVAILABLE and hasattr(resource, 'setrlimit') else None,
            env=safe_env
        )
        
        return result
    
    except subprocess.TimeoutExpired as e:
        raise SecurityError(f"Command exceeded timeout of {timeout} seconds")
    except Exception as e:
        raise SecurityError(f"Command execution failed: {str(e)}")


def generate_request_id() -> str:
    """Generate unique request ID for correlation."""
    return secrets.token_hex(16)


def validate_test_id(test_id: str) -> str:
    """
    Validate and sanitize test ID.
    
    Args:
        test_id: Test ID to validate
    
    Returns:
        Validated test ID
    
    Raises:
        InputValidationError: If test ID is invalid
    """
    if not test_id:
        raise InputValidationError("Test ID cannot be empty")
    
    # Allow only alphanumeric, underscore, and hyphen
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', test_id):
        raise InputValidationError(
            "Test ID must be 1-64 characters, containing only "
            "alphanumeric, underscore, and hyphen"
        )
    
    return test_id


def validate_http_method(method: str) -> str:
    """
    Validate HTTP method.
    
    Args:
        method: HTTP method to validate
    
    Returns:
        Validated uppercase method
    
    Raises:
        InputValidationError: If method is invalid
    """
    allowed_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']
    
    method_upper = method.upper()
    if method_upper not in allowed_methods:
        raise InputValidationError(
            f"Invalid HTTP method '{method}'. Allowed: {allowed_methods}"
        )
    
    return method_upper


def validate_json_payload(payload: Any, max_size: int = 1_000_000) -> Dict[str, Any]:
    """
    Validate JSON payload.
    
    Args:
        payload: Payload to validate
        max_size: Maximum size in bytes
    
    Returns:
        Validated payload as dictionary
    
    Raises:
        InputValidationError: If payload is invalid
    """
    if payload is None:
        return {}
    
    if isinstance(payload, str):
        # Parse JSON string
        return safe_json_parse(payload, max_size)
    elif isinstance(payload, dict):
        # Validate size of dictionary
        json_str = json.dumps(payload)
        if len(json_str) > max_size:
            raise InputValidationError(f"Payload size exceeds maximum {max_size}")
        return payload
    else:
        raise InputValidationError(f"Invalid payload type: {type(payload)}")


def hash_content(content: Union[str, bytes]) -> str:
    """
    Generate SHA-256 hash of content.
    
    Args:
        content: Content to hash
    
    Returns:
        Hex-encoded hash
    """
    if isinstance(content, str):
        content = content.encode('utf-8')
    
    return hashlib.sha256(content).hexdigest()


def rate_limit(max_calls: int = 10, window: int = 60):
    """
    Decorator for rate limiting function calls.
    
    Args:
        max_calls: Maximum number of calls allowed
        window: Time window in seconds
    """
    limiter = RateLimiter(max_calls, window)
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Use function name as identifier (could be enhanced with user ID)
            identifier = func.__name__
            
            if not limiter.is_allowed(identifier):
                raise SecurityError(
                    f"Rate limit exceeded for {identifier}. "
                    f"Maximum {max_calls} calls per {window} seconds."
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    
    return decorator