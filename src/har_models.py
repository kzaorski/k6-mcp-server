"""
HAR (HTTP Archive) Models for K6 MCP Server.

This module defines Pydantic models for parsing HAR files and converting them
to K6 multi-request workflows with intelligent static files management.
"""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, validator


class RequestType(str, Enum):
    """Classification of HTTP requests based on purpose and content."""
    STATIC = "static"      # CSS, JS, images, fonts
    API = "api"            # JSON REST endpoints, API calls  
    PAGE = "page"          # HTML documents, navigation
    AJAX = "ajax"          # XHR requests, dynamic content
    UNKNOWN = "unknown"    # Unclassified requests


class StaticFilesHandling(str, Enum):
    """Static files processing strategies."""
    EXCLUDE = "exclude"    # Skip all static files
    INCLUDE = "include"    # Include all static files 
    SIMULATE = "simulate"  # Create representative sample
    GROUP = "group"        # Group by page and load in parallel


class StaticFilesLoadPattern(str, Enum):
    """Static files loading patterns for realistic simulation."""
    BURST = "burst"              # Load all static files in parallel burst
    DISTRIBUTED = "distributed"  # Distribute loading over time
    REALISTIC = "realistic"      # Based on actual HAR timing data


class HARHeader(BaseModel):
    """HAR header name-value pair."""
    name: str
    value: str
    comment: Optional[str] = ""


class HARCookie(BaseModel):
    """HAR cookie information."""
    name: str
    value: str
    path: Optional[str] = None
    domain: Optional[str] = None
    expires: Optional[datetime] = None
    httpOnly: Optional[bool] = None
    secure: Optional[bool] = None
    comment: Optional[str] = ""


class HARQueryParam(BaseModel):
    """HAR query string parameter."""
    name: str
    value: str
    comment: Optional[str] = ""


class HARPostData(BaseModel):
    """HAR POST data information."""
    mimeType: str
    text: Optional[str] = None
    params: Optional[List[HARQueryParam]] = None
    comment: Optional[str] = ""


class HARRequest(BaseModel):
    """HAR request information."""
    method: str
    url: str
    httpVersion: str
    headers: List[HARHeader]
    queryString: List[HARQueryParam]
    cookies: List[HARCookie]
    headersSize: int
    bodySize: int
    postData: Optional[HARPostData] = None
    comment: Optional[str] = ""
    
    def get_header(self, header_name: str) -> Optional[str]:
        """Get header value by name (case-insensitive)."""
        for header in self.headers:
            if header.name.lower() == header_name.lower():
                return header.value
        return None
    
    def get_cookie(self, cookie_name: str) -> Optional[str]:
        """Get cookie value by name."""
        for cookie in self.cookies:
            if cookie.name == cookie_name:
                return cookie.value
        return None
    
    def is_static_resource(self) -> bool:
        """Check if request is for a static resource based on URL and headers."""
        static_extensions = {
            '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
            '.woff', '.woff2', '.ttf', '.eot', '.map', '.webp', '.avif'
        }
        
        # Check file extension
        url_lower = self.url.lower()
        if any(url_lower.endswith(ext) for ext in static_extensions):
            return True
        
        # Check content type from request headers (if available)
        content_type = self.get_header('content-type')
        if content_type:
            static_content_types = [
                'text/css', 'application/javascript', 'text/javascript',
                'image/', 'font/', 'application/font'
            ]
            if any(content_type.lower().startswith(ct) for ct in static_content_types):
                return True
        
        return False


class HARContent(BaseModel):
    """HAR response content information."""
    size: int
    compression: Optional[int] = None
    mimeType: str
    text: Optional[str] = None
    encoding: Optional[str] = None
    comment: Optional[str] = ""


class HARResponse(BaseModel):
    """HAR response information."""
    status: int
    statusText: str
    httpVersion: str
    headers: List[HARHeader]
    cookies: List[HARCookie]
    content: HARContent
    redirectURL: str = ""
    headersSize: int
    bodySize: int
    comment: Optional[str] = ""
    
    def get_header(self, header_name: str) -> Optional[str]:
        """Get response header value by name (case-insensitive)."""
        for header in self.headers:
            if header.name.lower() == header_name.lower():
                return header.value
        return None
    
    def is_json_response(self) -> bool:
        """Check if response contains JSON data."""
        content_type = self.get_header('content-type')
        return content_type and 'application/json' in content_type.lower()
    
    def is_html_response(self) -> bool:
        """Check if response contains HTML data."""
        content_type = self.get_header('content-type')
        return content_type and 'text/html' in content_type.lower()


class HARTimings(BaseModel):
    """HAR timing information."""
    blocked: Optional[float] = None
    dns: Optional[float] = None
    connect: Optional[float] = None
    send: float
    wait: float
    receive: float
    ssl: Optional[float] = None
    comment: Optional[str] = ""
    
    @property
    def total_time(self) -> float:
        """Calculate total request time."""
        return (self.blocked or 0) + (self.dns or 0) + (self.connect or 0) + \
               self.send + self.wait + self.receive + (self.ssl or 0)


class HAREntry(BaseModel):
    """HAR entry representing a single HTTP transaction."""
    pageref: Optional[str] = None
    startedDateTime: datetime
    time: float
    request: HARRequest
    response: HARResponse
    cache: Optional[Dict[str, Any]] = None
    timings: HARTimings
    serverIPAddress: Optional[str] = None
    connection: Optional[str] = None
    comment: Optional[str] = ""
    
    def classify_request_type(self) -> RequestType:
        """Classify the request type based on various indicators."""
        # Check if it's a static resource
        if self.request.is_static_resource():
            return RequestType.STATIC
        
        # Check for AJAX requests
        if self.request.get_header('X-Requested-With') == 'XMLHttpRequest':
            return RequestType.AJAX
        
        # Check for API endpoints (JSON responses)
        if self.response.is_json_response():
            return RequestType.API
        
        # Check for HTML pages
        if self.response.is_html_response():
            return RequestType.PAGE
        
        return RequestType.UNKNOWN


class HARPage(BaseModel):
    """HAR page information."""
    startedDateTime: datetime
    id: str
    title: str
    pageTimings: Dict[str, Any] = {}
    comment: Optional[str] = ""


class HARLog(BaseModel):
    """HAR log containing all HTTP transactions."""
    version: str
    creator: Dict[str, Any]
    browser: Optional[Dict[str, Any]] = None
    pages: Optional[List[HARPage]] = None
    entries: List[HAREntry]
    comment: Optional[str] = ""


class HARFile(BaseModel):
    """Complete HAR file structure."""
    log: HARLog


class PageGroup(BaseModel):
    """Group of requests belonging to the same page/navigation."""
    page_id: str
    main_request: HAREntry  # The primary HTML request
    static_requests: List[HAREntry] = []
    ajax_requests: List[HAREntry] = []
    api_requests: List[HAREntry] = []
    start_time: datetime
    page_title: Optional[str] = None
    
    @property
    def total_requests(self) -> int:
        """Total number of requests in this page group."""
        return 1 + len(self.static_requests) + len(self.ajax_requests) + len(self.api_requests)
    
    @property
    def static_files_count(self) -> int:
        """Number of static files in this page group."""
        return len(self.static_requests)
    
    def add_request(self, entry: HAREntry):
        """Add a request to appropriate category in this page group."""
        request_type = entry.classify_request_type()
        
        if request_type == RequestType.STATIC:
            self.static_requests.append(entry)
        elif request_type == RequestType.AJAX:
            self.ajax_requests.append(entry)
        elif request_type == RequestType.API:
            self.api_requests.append(entry)


class HARConversionOptions(BaseModel):
    """Configuration options for HAR to K6 conversion."""
    
    # Core conversion settings
    detect_authentication: bool = True
    extract_dynamic_data: bool = True
    preserve_timing: bool = False
    base_url_replacement: Optional[str] = None
    
    # Static files management
    static_files_handling: StaticFilesHandling = StaticFilesHandling.EXCLUDE
    static_file_patterns: List[str] = Field(default_factory=lambda: [
        "*.css", "*.js", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", 
        "*.ico", "*.woff", "*.woff2", "*.ttf", "*.eot", "*.map", "*.webp"
    ])
    simulate_static_load: bool = False
    static_files_parallel: bool = True
    static_files_think_time: float = 0.1
    max_static_files_per_page: int = 20
    static_files_load_pattern: StaticFilesLoadPattern = StaticFilesLoadPattern.BURST
    
    # Request filtering
    exclude_domains: List[str] = Field(default_factory=list)
    include_only_domains: List[str] = Field(default_factory=list)
    exclude_status_codes: List[int] = Field(default_factory=lambda: [404, 500])
    min_response_time: Optional[float] = None  # Filter out very fast requests
    
    # Advanced options
    detect_page_boundaries: bool = True
    group_requests_by_timing: bool = True
    timing_gap_threshold: float = 2.0  # Seconds - gap indicating new page/action
    preserve_user_agent: bool = True
    extract_csrf_tokens: bool = True
    
    @validator('static_files_handling')
    def validate_static_handling(cls, v):
        if v not in StaticFilesHandling:
            raise ValueError(f'static_files_handling must be one of {list(StaticFilesHandling)}')
        return v
    
    @validator('static_files_load_pattern') 
    def validate_load_pattern(cls, v):
        if v not in StaticFilesLoadPattern:
            raise ValueError(f'static_files_load_pattern must be one of {list(StaticFilesLoadPattern)}')
        return v
    
    @validator('static_file_patterns')
    def validate_patterns(cls, v):
        # Validate glob patterns
        for pattern in v:
            if not pattern.startswith('*.'):
                raise ValueError(f'Static file pattern "{pattern}" must start with "*."')
        return v


class ChainPoint(BaseModel):
    """Represents a potential response chaining opportunity."""
    source_step_id: str
    source_field: str          # JSON path or header name
    target_step_id: str
    target_location: str       # 'url', 'header', 'payload'
    target_field: str
    extraction_path: str       # JSON path for extraction
    confidence: float = 1.0    # Confidence level (0.0-1.0)
    chain_type: str           # 'cookie', 'token', 'id', 'csrf', etc.
    
    class Config:
        schema_extra = {
            "example": {
                "source_step_id": "login",
                "source_field": "accessToken",
                "target_step_id": "get_profile", 
                "target_location": "header",
                "target_field": "Authorization",
                "extraction_path": "$.data.accessToken",
                "confidence": 0.95,
                "chain_type": "token"
            }
        }


class HARAnalysisResult(BaseModel):
    """Result of HAR file analysis."""
    total_requests: int
    unique_domains: List[str]
    request_types: Dict[str, int]  # RequestType -> count
    page_groups: List[PageGroup]
    potential_chains: List[ChainPoint]
    static_files_summary: Dict[str, Any]
    timing_analysis: Dict[str, float]
    recommendations: List[str]
    
    @property
    def static_files_ratio(self) -> float:
        """Percentage of requests that are static files."""
        static_count = self.request_types.get(RequestType.STATIC, 0)
        return (static_count / self.total_requests * 100) if self.total_requests > 0 else 0.0


class StaticFilesConfig(BaseModel):
    """Configuration for static files handling in generated K6 script."""
    enabled: bool = False
    load_pattern: StaticFilesLoadPattern = StaticFilesLoadPattern.BURST
    parallel_loading: bool = True
    max_per_page: int = 20
    think_time: float = 0.1
    simulate_caching: bool = False
    priority_resources: List[str] = Field(default_factory=lambda: ["*.css"])
    
    class Config:
        schema_extra = {
            "example": {
                "enabled": True,
                "load_pattern": "burst",
                "parallel_loading": True,
                "max_per_page": 15,
                "think_time": 0.5,
                "simulate_caching": False,
                "priority_resources": ["*.css", "critical.js"]
            }
        }