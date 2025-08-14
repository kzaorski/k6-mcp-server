"""
OpenAPI models for K6 MCP Server.

This module defines data models for OpenAPI specifications and provides
utilities for parsing and validating OpenAPI documents.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, validator
import logging

logger = logging.getLogger(__name__)


class HttpMethod(str, Enum):
    """HTTP methods supported by OpenAPI."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"


class ParameterLocation(str, Enum):
    """Parameter locations in OpenAPI."""
    QUERY = "query"
    HEADER = "header"
    PATH = "path"
    COOKIE = "cookie"


class SecuritySchemeType(str, Enum):
    """Security scheme types."""
    API_KEY = "apiKey"
    HTTP = "http"
    OAUTH2 = "oauth2"
    OPENID_CONNECT = "openIdConnect"


class AuthLocation(str, Enum):
    """API Key authentication locations."""
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


class EndpointSelector(BaseModel):
    """Endpoint selection criteria for test generation."""
    path: str
    method: HttpMethod
    include: bool = True
    priority: int = 1  # 1=high, 2=medium, 3=low
    custom_name: Optional[str] = None
    custom_data: Optional[Dict[str, Any]] = None


class TestGenerationOptions(BaseModel):
    """Options for test generation from OpenAPI spec."""
    generate_single_endpoint_tests: bool = True
    generate_workflow_tests: bool = True
    generate_crud_workflows: bool = True
    generate_auth_workflows: bool = True
    include_examples: bool = True
    include_schema_validation: bool = False
    max_array_items: int = 3
    max_string_length: int = 50
    virtual_users: int = 1
    duration: str = "30s"
    think_time: float = 1.0
    
    # New endpoint selection options
    selected_endpoints: Optional[List[EndpointSelector]] = None
    endpoint_filter: Optional[Dict[str, Any]] = None  # Filtering criteria
    include_tags: Optional[List[str]] = None  # Only endpoints with these tags
    exclude_tags: Optional[List[str]] = None  # Exclude endpoints with these tags
    include_methods: Optional[List[HttpMethod]] = None  # Only these HTTP methods
    exclude_methods: Optional[List[HttpMethod]] = None  # Exclude these HTTP methods


class OpenAPIInfo(BaseModel):
    """OpenAPI Info Object."""
    title: str
    description: Optional[str] = None
    version: str
    contact: Optional[Dict[str, Any]] = None
    license: Optional[Dict[str, Any]] = None


class OpenAPIServer(BaseModel):
    """OpenAPI Server Object."""
    url: str
    description: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None


class OpenAPIParameter(BaseModel):
    """OpenAPI Parameter Object."""
    name: str
    in_: ParameterLocation = Field(alias="in")
    description: Optional[str] = None
    required: bool = False
    deprecated: bool = False
    schema_: Optional[Dict[str, Any]] = Field(default=None, alias="schema")
    example: Optional[Any] = None
    examples: Optional[Dict[str, Any]] = None


class OpenAPIRequestBody(BaseModel):
    """OpenAPI Request Body Object."""
    description: Optional[str] = None
    content: Dict[str, Any]
    required: bool = False


class OpenAPIResponse(BaseModel):
    """OpenAPI Response Object."""
    description: str
    headers: Optional[Dict[str, Any]] = None
    content: Optional[Dict[str, Any]] = None
    links: Optional[Dict[str, Any]] = None


class OpenAPISecurityScheme(BaseModel):
    """OpenAPI Security Scheme Object."""
    type: SecuritySchemeType
    description: Optional[str] = None
    name: Optional[str] = None  # For apiKey
    in_: Optional[AuthLocation] = Field(default=None, alias="in")  # For apiKey
    scheme: Optional[str] = None  # For http
    bearer_format: Optional[str] = Field(default=None, alias="bearerFormat")  # For http
    flows: Optional[Dict[str, Any]] = None  # For oauth2
    open_id_connect_url: Optional[str] = Field(default=None, alias="openIdConnectUrl")


class OpenAPIOperation(BaseModel):
    """OpenAPI Operation Object."""
    tags: Optional[List[str]] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = Field(default=None, alias="operationId")
    parameters: Optional[List[OpenAPIParameter]] = None
    request_body: Optional[OpenAPIRequestBody] = Field(default=None, alias="requestBody")
    responses: Dict[str, OpenAPIResponse]
    deprecated: bool = False
    security: Optional[List[Dict[str, List[str]]]] = None


class OpenAPIPathItem(BaseModel):
    """OpenAPI Path Item Object."""
    summary: Optional[str] = None
    description: Optional[str] = None
    get: Optional[OpenAPIOperation] = None
    put: Optional[OpenAPIOperation] = None
    post: Optional[OpenAPIOperation] = None
    delete: Optional[OpenAPIOperation] = None
    options: Optional[OpenAPIOperation] = None
    head: Optional[OpenAPIOperation] = None
    patch: Optional[OpenAPIOperation] = None
    trace: Optional[OpenAPIOperation] = None
    servers: Optional[List[OpenAPIServer]] = None
    parameters: Optional[List[OpenAPIParameter]] = None

    def get_operations(self) -> Dict[HttpMethod, OpenAPIOperation]:
        """Get all operations defined for this path."""
        operations = {}
        for method in HttpMethod:
            operation = getattr(self, method.value.lower(), None)
            if operation:
                operations[method] = operation
        return operations

    def get_operation_by_method(self, method: str) -> Optional[OpenAPIOperation]:
        """Get operation by HTTP method."""
        method_lower = method.lower()
        return getattr(self, method_lower, None)


class OpenAPIComponents(BaseModel):
    """OpenAPI Components Object."""
    schemas: Optional[Dict[str, Any]] = None
    responses: Optional[Dict[str, OpenAPIResponse]] = None
    parameters: Optional[Dict[str, OpenAPIParameter]] = None
    examples: Optional[Dict[str, Any]] = None
    request_bodies: Optional[Dict[str, OpenAPIRequestBody]] = Field(default=None, alias="requestBodies")
    headers: Optional[Dict[str, Any]] = None
    security_schemes: Optional[Dict[str, OpenAPISecurityScheme]] = Field(default=None, alias="securitySchemes")
    links: Optional[Dict[str, Any]] = None
    callbacks: Optional[Dict[str, Any]] = None


class OpenAPISpec(BaseModel):
    """Complete OpenAPI Specification."""
    openapi: str
    info: OpenAPIInfo
    servers: Optional[List[OpenAPIServer]] = None
    paths: Dict[str, OpenAPIPathItem]
    components: Optional[OpenAPIComponents] = None
    security: Optional[List[Dict[str, List[str]]]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    external_docs: Optional[Dict[str, Any]] = Field(default=None, alias="externalDocs")

    @validator('openapi')
    def validate_openapi_version(cls, v):
        """Validate OpenAPI version."""
        if not v.startswith('3.'):
            raise ValueError('Only OpenAPI 3.x specifications are supported')
        return v

    def get_base_url(self) -> str:
        """Get the first server URL as base URL."""
        if self.servers and len(self.servers) > 0:
            return self.servers[0].url
        return "http://localhost"

    def get_all_endpoints(self) -> List[tuple[str, HttpMethod, OpenAPIOperation]]:
        """Get all endpoints as (path, method, operation) tuples."""
        endpoints = []
        for path, path_item in self.paths.items():
            for method, operation in path_item.get_operations().items():
                endpoints.append((path, method, operation))
        return endpoints

    def get_endpoints_by_tag(self, tag: str) -> List[tuple[str, HttpMethod, OpenAPIOperation]]:
        """Get endpoints filtered by tag."""
        endpoints = []
        for path, method, operation in self.get_all_endpoints():
            if operation.tags and tag in operation.tags:
                endpoints.append((path, method, operation))
        return endpoints

    def get_security_schemes(self) -> Dict[str, OpenAPISecurityScheme]:
        """Get all security schemes."""
        if self.components and self.components.security_schemes:
            return self.components.security_schemes
        return {}

    def has_authentication(self) -> bool:
        """Check if the API requires authentication."""
        # Check global security
        if self.security:
            return True
        
        # Check operation-level security
        for path, method, operation in self.get_all_endpoints():
            if operation.security:
                return True
        
        return False

    def get_auth_endpoints(self) -> List[tuple[str, HttpMethod, OpenAPIOperation]]:
        """Get endpoints that might be authentication related."""
        auth_keywords = ['auth', 'login', 'signin', 'token', 'oauth', 'session']
        auth_endpoints = []
        
        for path, method, operation in self.get_all_endpoints():
            path_lower = path.lower()
            operation_id = (operation.operation_id or "").lower()
            summary = (operation.summary or "").lower()
            
            if any(keyword in path_lower or keyword in operation_id or keyword in summary 
                   for keyword in auth_keywords):
                auth_endpoints.append((path, method, operation))
        
        return auth_endpoints


class EndpointAnalysis(BaseModel):
    """Analysis result for a single endpoint."""
    path: str
    method: HttpMethod
    operation: OpenAPIOperation
    requires_auth: bool
    path_params: List[OpenAPIParameter]
    query_params: List[OpenAPIParameter]
    header_params: List[OpenAPIParameter]
    request_body_schema: Optional[Dict[str, Any]] = None
    response_schemas: Dict[str, Any]
    is_crud_operation: bool = False
    crud_resource: Optional[str] = None
    dependencies: List[str] = []  # Operation IDs this endpoint depends on


class APIAnalysis(BaseModel):
    """Complete API analysis result."""
    spec: OpenAPISpec
    endpoints: List[EndpointAnalysis]
    auth_endpoints: List[EndpointAnalysis]
    crud_resources: Dict[str, List[EndpointAnalysis]]
    dependency_graph: Dict[str, List[str]]  # operation_id -> [dependent_operation_ids]
    workflow_suggestions: List[Dict[str, Any]]


class TestScenario(BaseModel):
    """Test scenario configuration."""
    name: str
    description: str
    endpoints: List[tuple[str, str]]  # (path, method) pairs
    dependencies: Dict[str, str]  # step_id -> dependency_step_id
    auth_required: bool = False
    test_data: Dict[str, Any] = {}