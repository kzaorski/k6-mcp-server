"""
Domain validation utilities.

Provides custom validators and validation logic for domain models.
"""

import re
from typing import Any, List, Optional
from urllib.parse import urlparse
from pydantic import field_validator


def validate_url(url: str) -> str:
    """Validate URL format."""
    if not url:
        raise ValueError("URL cannot be empty")
    
    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            raise ValueError("URL must have a valid domain")
    except Exception:
        raise ValueError("Invalid URL format")
    
    return url


def validate_duration(duration: str) -> str:
    """Validate K6 duration format."""
    if not duration:
        raise ValueError("Duration cannot be empty")
    
    pattern = r'^\d+[smh]$'
    if not re.match(pattern, duration):
        raise ValueError("Duration must be in format: number + s/m/h (e.g., '30s', '5m', '1h')")
    
    return duration


def validate_identifier(identifier: str) -> str:
    """Validate identifier format (letters, numbers, underscore, hyphen)."""
    if not identifier:
        raise ValueError("Identifier cannot be empty")
    
    pattern = r'^[a-zA-Z][a-zA-Z0-9_-]*$'
    if not re.match(pattern, identifier):
        raise ValueError("Identifier must start with letter and contain only letters, numbers, underscore, hyphen")
    
    return identifier


def validate_json_path(json_path: str) -> str:
    """Validate JSON path format."""
    if not json_path:
        raise ValueError("JSON path cannot be empty")
    
    if not json_path.startswith('$'):
        raise ValueError("JSON path must start with '$'")
    
    return json_path


def validate_virtual_users(virtual_users: int, max_allowed: int = 10000) -> int:
    """Validate virtual users count."""
    if virtual_users < 1:
        raise ValueError("Virtual users must be at least 1")
    
    if virtual_users > max_allowed:
        raise ValueError(f"Virtual users cannot exceed {max_allowed}")
    
    return virtual_users


def validate_headers(headers: dict) -> dict:
    """Validate HTTP headers."""
    if not headers:
        return headers
    
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("Header names and values must be strings")
        
        # Basic header name validation
        if not re.match(r'^[a-zA-Z0-9-_]+$', name):
            raise ValueError(f"Invalid header name: {name}")
    
    return headers


def validate_payload_size(payload: Any, max_size_mb: int = 10) -> Any:
    """Validate payload size."""
    if payload is None:
        return payload
    
    import json
    import sys
    
    # Estimate size
    if isinstance(payload, dict):
        size_bytes = sys.getsizeof(json.dumps(payload))
    else:
        size_bytes = sys.getsizeof(str(payload))
    
    max_size_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_size_bytes:
        raise ValueError(f"Payload size ({size_bytes} bytes) exceeds maximum allowed ({max_size_bytes} bytes)")
    
    return payload


class ValidationMixin:
    """Mixin class providing common validation methods."""
    
    @field_validator('url')
    @classmethod
    def validate_url_field(cls, v):
        return validate_url(v)
    
    @field_validator('duration')
    @classmethod
    def validate_duration_field(cls, v):
        if v is not None:
            return validate_duration(v)
        return v
    
    @field_validator('timeout')
    @classmethod
    def validate_timeout_field(cls, v):
        if v is not None:
            return validate_duration(v)
        return v
    
    @field_validator('virtual_users')
    @classmethod
    def validate_virtual_users_field(cls, v):
        return validate_virtual_users(v)
    
    @field_validator('headers')
    @classmethod
    def validate_headers_field(cls, v):
        return validate_headers(v)
    
    @field_validator('payload')
    @classmethod
    def validate_payload_field(cls, v):
        return validate_payload_size(v)