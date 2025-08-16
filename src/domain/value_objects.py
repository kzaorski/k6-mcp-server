"""
Value objects for K6 MCP Server domain.

Contains immutable value objects that represent domain concepts
with built-in validation and behavior.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from enum import Enum
import re
from urllib.parse import urlparse


@dataclass(frozen=True)
class TestId:
    """Value object representing a test identifier."""
    value: str
    
    def __post_init__(self):
        if not self.value:
            raise ValueError("Test ID cannot be empty")
        
        if not re.match(r'^[a-zA-Z0-9_-]+$', self.value):
            raise ValueError("Test ID can only contain letters, numbers, underscore, and hyphen")
    
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Url:
    """Value object representing a URL with validation."""
    value: str
    
    def __post_init__(self):
        if not self.value:
            raise ValueError("URL cannot be empty")
        
        if not self.value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        
        try:
            parsed = urlparse(self.value)
            if not parsed.netloc:
                raise ValueError("URL must have a valid domain")
        except Exception:
            raise ValueError("Invalid URL format")
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def domain(self) -> str:
        """Get the domain part of the URL."""
        return urlparse(self.value).netloc
    
    @property
    def scheme(self) -> str:
        """Get the scheme (http/https) of the URL."""
        return urlparse(self.value).scheme
    
    @property
    def path(self) -> str:
        """Get the path part of the URL."""
        return urlparse(self.value).path or "/"


@dataclass(frozen=True)
class Duration:
    """Value object representing a K6 duration."""
    value: str
    
    def __post_init__(self):
        if not self.value:
            raise ValueError("Duration cannot be empty")
        
        if not re.match(r'^\d+[smh]$', self.value):
            raise ValueError("Duration must be in format: number + s/m/h")
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def seconds(self) -> int:
        """Convert duration to seconds."""
        if self.value.endswith('s'):
            return int(self.value[:-1])
        elif self.value.endswith('m'):
            return int(self.value[:-1]) * 60
        elif self.value.endswith('h'):
            return int(self.value[:-1]) * 3600
        else:
            raise ValueError("Invalid duration format")


@dataclass(frozen=True)
class VirtualUsers:
    """Value object representing virtual users count."""
    value: int
    
    def __post_init__(self):
        if self.value < 1:
            raise ValueError("Virtual users must be at least 1")
        
        if self.value > 10000:
            raise ValueError("Virtual users cannot exceed 10000")
    
    def __str__(self) -> str:
        return str(self.value)
    
    def __int__(self) -> int:
        return self.value


@dataclass(frozen=True)
class JsonPath:
    """Value object representing a JSON path for data extraction."""
    value: str
    
    def __post_init__(self):
        if not self.value:
            raise ValueError("JSON path cannot be empty")
        
        if not self.value.startswith('$'):
            raise ValueError("JSON path must start with '$'")
    
    def __str__(self) -> str:
        return self.value


class TestStatus(str, Enum):
    """Enumeration of test statuses."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    
    def is_final(self) -> bool:
        """Check if this status is final (test won't change anymore)."""
        return self in [TestStatus.COMPLETED, TestStatus.FAILED, TestStatus.CANCELLED]
    
    def is_active(self) -> bool:
        """Check if this status indicates an active test."""
        return self in [TestStatus.PENDING, TestStatus.CONFIRMED, TestStatus.RUNNING]


@dataclass(frozen=True)
class HttpHeaders:
    """Value object representing HTTP headers."""
    headers: Dict[str, str]
    
    def __post_init__(self):
        if not isinstance(self.headers, dict):
            raise ValueError("Headers must be a dictionary")
        
        for name, value in self.headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("Header names and values must be strings")
            
            if not re.match(r'^[a-zA-Z0-9-_]+$', name):
                raise ValueError(f"Invalid header name: {name}")
    
    def get(self, name: str, default: str = None) -> Optional[str]:
        """Get header value by name (case-insensitive)."""
        name_lower = name.lower()
        for header_name, value in self.headers.items():
            if header_name.lower() == name_lower:
                return value
        return default
    
    def has(self, name: str) -> bool:
        """Check if header exists (case-insensitive)."""
        return self.get(name) is not None
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary."""
        return dict(self.headers)


@dataclass(frozen=True)
class Threshold:
    """Value object representing a performance threshold."""
    metric: str
    condition: str
    
    def __post_init__(self):
        if not self.metric:
            raise ValueError("Threshold metric cannot be empty")
        
        if not self.condition:
            raise ValueError("Threshold condition cannot be empty")
        
        # Validate common threshold patterns
        valid_patterns = [
            r'p\(\d+\)<\d+',  # p(95)<500
            r'rate<\d+\.?\d*',  # rate<0.01
            r'avg<\d+\.?\d*',  # avg<1000
            r'med<\d+\.?\d*',  # med<500
            r'min<\d+\.?\d*',  # min<100
            r'max<\d+\.?\d*',  # max<2000
        ]
        
        if not any(re.match(pattern, self.condition) for pattern in valid_patterns):
            # Allow any condition for flexibility, but could add stricter validation
            pass
    
    def __str__(self) -> str:
        return f"{self.metric}: {self.condition}"
    
    @property
    def k6_format(self) -> str:
        """Get threshold in K6 format."""
        return self.condition


@dataclass(frozen=True)
class WorkflowName:
    """Value object representing a workflow name."""
    value: str
    
    def __post_init__(self):
        if not self.value:
            raise ValueError("Workflow name cannot be empty")
        
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', self.value):
            raise ValueError("Workflow name must start with letter and contain only letters, numbers, underscore, hyphen")
        
        if len(self.value) > 100:
            raise ValueError("Workflow name cannot exceed 100 characters")
    
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class StepId:
    """Value object representing a workflow step identifier."""
    value: str
    
    def __post_init__(self):
        if not self.value:
            raise ValueError("Step ID cannot be empty")
        
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', self.value):
            raise ValueError("Step ID must be a valid identifier")
        
        if len(self.value) > 50:
            raise ValueError("Step ID cannot exceed 50 characters")
    
    def __str__(self) -> str:
        return self.value