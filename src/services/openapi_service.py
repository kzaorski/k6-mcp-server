"""
OpenAPI Service.

Business logic for OpenAPI specification processing and test generation.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, urljoin

from core.config import AppConfig
from core.base import OperationResult
from core.events import EventType
from domain.models import K6TestConfig, WorkflowConfig, RequestStep, HttpMethod, LoadPattern
from utils.performance import performance_monitor, global_health
from .base_service import EnhancedBaseService

logger = logging.getLogger(__name__)


class OpenAPIService(EnhancedBaseService):
    """
    Service for processing OpenAPI specifications and generating tests.
    
    Provides OpenAPI parsing, endpoint analysis, and automated
    test generation with proper validation and error handling.
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self._openapi_cache: Dict[str, Dict[str, Any]] = {}
    
    async def _initialize_impl(self) -> None:
        """Initialize the OpenAPI service."""
        await super()._initialize_impl()
        
        # Register health check
        global_health.register_check("openapi_service", self.health_check_impl)
        
        self.logger.info("OpenAPI service initialized")
    
    @performance_monitor("openapi_service.load_openapi_spec")
    async def load_openapi_spec(self, spec_url: str) -> OperationResult[Dict[str, Any]]:
        """
        Load and parse OpenAPI specification.
        
        Args:
            spec_url: URL to OpenAPI specification (JSON or YAML)
            
        Returns:
            Operation result with parsed OpenAPI specification
        """
        return await self.execute_with_tracking(
            "load_openapi_spec",
            lambda: self._load_openapi_spec_internal(spec_url),
            spec_url=spec_url
        )
    
    @performance_monitor("openapi_service.generate_tests_from_spec")
    async def generate_tests_from_spec(
        self,
        spec_url: str,
        base_url: str = None,
        test_config: Dict[str, Any] = None
    ) -> OperationResult[List[K6TestConfig]]:
        """
        Generate K6 test configurations from OpenAPI specification.
        
        Args:
            spec_url: URL to OpenAPI specification
            base_url: Base URL for API endpoints
            test_config: Additional test configuration options
            
        Returns:
            Operation result with generated test configurations
        """
        return await self.execute_with_tracking(
            "generate_tests_from_spec",
            lambda: self._generate_tests_from_spec_internal(spec_url, base_url, test_config),
            spec_url=spec_url
        )
    
    @performance_monitor("openapi_service.generate_workflow_from_spec")
    async def generate_workflow_from_spec(
        self,
        spec_url: str,
        workflow_name: str,
        base_url: str = None,
        endpoints: List[str] = None
    ) -> OperationResult[WorkflowConfig]:
        """
        Generate workflow configuration from OpenAPI specification.
        
        Args:
            spec_url: URL to OpenAPI specification
            workflow_name: Name for the generated workflow
            base_url: Base URL for API endpoints
            endpoints: Specific endpoints to include in workflow
            
        Returns:
            Operation result with generated workflow configuration
        """
        return await self.execute_with_tracking(
            "generate_workflow_from_spec",
            lambda: self._generate_workflow_from_spec_internal(spec_url, workflow_name, base_url, endpoints),
            spec_url=spec_url,
            workflow_name=workflow_name
        )
    
    @performance_monitor("openapi_service.analyze_api_endpoints")
    async def analyze_api_endpoints(self, spec_url: str) -> OperationResult[Dict[str, Any]]:
        """
        Analyze OpenAPI specification and provide endpoint summary.
        
        Args:
            spec_url: URL to OpenAPI specification
            
        Returns:
            Operation result with endpoint analysis
        """
        return await self.safe_execute(self._analyze_api_endpoints_internal, spec_url)
    
    async def validate_openapi_spec(self, spec_url: str) -> OperationResult[List[str]]:
        """
        Validate OpenAPI specification.
        
        Args:
            spec_url: URL to OpenAPI specification
            
        Returns:
            Operation result with validation errors (empty list if valid)
        """
        return await self.safe_execute(self._validate_openapi_spec_internal, spec_url)
    
    # Private methods
    
    async def _load_openapi_spec_internal(self, spec_url: str) -> Dict[str, Any]:
        """Internal OpenAPI specification loading logic."""
        # Check cache first
        if spec_url in self._openapi_cache:
            self.logger.debug(f"Using cached OpenAPI spec for {spec_url}")
            return self._openapi_cache[spec_url]
        
        try:
            # In a real implementation, this would use aiohttp to fetch the spec
            # For now, simulate loading a spec
            if spec_url.startswith("http"):
                # Simulate HTTP fetch
                await asyncio.sleep(0.1)
                
                # Example OpenAPI spec structure
                spec = {
                    "openapi": "3.0.0",
                    "info": {
                        "title": "Example API",
                        "version": "1.0.0",
                        "description": "Example API for testing"
                    },
                    "servers": [
                        {"url": "https://api.example.com/v1"}
                    ],
                    "paths": {
                        "/users": {
                            "get": {
                                "summary": "List users",
                                "operationId": "listUsers",
                                "responses": {
                                    "200": {
                                        "description": "List of users",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "type": "array",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": {
                                                            "id": {"type": "string"},
                                                            "name": {"type": "string"},
                                                            "email": {"type": "string"}
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            "post": {
                                "summary": "Create user",
                                "operationId": "createUser",
                                "requestBody": {
                                    "required": True,
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "email": {"type": "string"}
                                                },
                                                "required": ["name", "email"]
                                            }
                                        }
                                    }
                                },
                                "responses": {
                                    "201": {
                                        "description": "User created",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "string"},
                                                        "name": {"type": "string"},
                                                        "email": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "/users/{id}": {
                            "get": {
                                "summary": "Get user by ID",
                                "operationId": "getUserById",
                                "parameters": [
                                    {
                                        "name": "id",
                                        "in": "path",
                                        "required": True,
                                        "schema": {"type": "string"}
                                    }
                                ],
                                "responses": {
                                    "200": {
                                        "description": "User details",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "string"},
                                                        "name": {"type": "string"},
                                                        "email": {"type": "string"}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                
            else:
                # For file:// URLs or local paths, read from file
                import yaml
                with open(spec_url, 'r') as f:
                    if spec_url.endswith('.yaml') or spec_url.endswith('.yml'):
                        spec = yaml.safe_load(f)
                    else:
                        spec = json.load(f)
            
            # Cache the loaded spec
            self._openapi_cache[spec_url] = spec
            
            await self.publish_event(EventType.CONFIGURATION_LOADED, {
                "spec_url": spec_url,
                "api_title": spec.get("info", {}).get("title", "Unknown"),
                "version": spec.get("info", {}).get("version", "Unknown"),
                "endpoint_count": len(spec.get("paths", {}))
            })
            
            return spec
            
        except Exception as e:
            raise Exception(f"Failed to load OpenAPI specification from {spec_url}: {str(e)}")
    
    async def _generate_tests_from_spec_internal(
        self,
        spec_url: str,
        base_url: str,
        test_config: Dict[str, Any]
    ) -> List[K6TestConfig]:
        """Internal test generation logic."""
        spec = await self._load_openapi_spec_internal(spec_url)
        
        # Determine base URL
        if not base_url:
            servers = spec.get("servers", [])
            if servers:
                base_url = servers[0].get("url", "")
            else:
                raise ValueError("No base URL provided and no servers found in OpenAPI spec")
        
        # Default test configuration
        default_config = {
            "virtual_users": 1,
            "duration": "30s",
            "load_pattern": LoadPattern.CONSTANT
        }
        if test_config:
            default_config.update(test_config)
        
        generated_tests = []
        paths = spec.get("paths", {})
        
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method.upper() not in [m.value for m in HttpMethod]:
                    continue
                
                # Generate test configuration for this endpoint
                test_config = K6TestConfig(
                    url=urljoin(base_url, path),
                    method=HttpMethod(method.upper()),
                    virtual_users=default_config["virtual_users"],
                    duration=default_config["duration"],
                    load_pattern=default_config["load_pattern"]
                )
                
                # Add headers if specified
                if operation.get("requestBody"):
                    content_type = self._get_content_type(operation["requestBody"])
                    if content_type:
                        test_config.headers = {"Content-Type": content_type}
                
                # Generate payload for POST/PUT/PATCH
                if method.upper() in ["POST", "PUT", "PATCH"] and operation.get("requestBody"):
                    payload = self._generate_payload_from_schema(operation["requestBody"])
                    if payload:
                        test_config.payload = payload
                
                generated_tests.append(test_config)
        
        await self.publish_event(EventType.TEST_PREPARED, {
            "spec_url": spec_url,
            "generated_test_count": len(generated_tests)
        })
        
        return generated_tests
    
    async def _generate_workflow_from_spec_internal(
        self,
        spec_url: str,
        workflow_name: str,
        base_url: str,
        endpoints: List[str]
    ) -> WorkflowConfig:
        """Internal workflow generation logic."""
        spec = await self._load_openapi_spec_internal(spec_url)
        
        # Determine base URL
        if not base_url:
            servers = spec.get("servers", [])
            if servers:
                base_url = servers[0].get("url", "")
            else:
                raise ValueError("No base URL provided and no servers found in OpenAPI spec")
        
        paths = spec.get("paths", {})
        workflow_steps = []
        
        # If specific endpoints are requested, filter to those
        if endpoints:
            filtered_paths = {path: paths[path] for path in endpoints if path in paths}
            paths = filtered_paths
        
        step_counter = 1
        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method.upper() not in [m.value for m in HttpMethod]:
                    continue
                
                # Generate step for this endpoint
                step_id = f"step_{step_counter}_{method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"
                step_name = operation.get("summary", f"{method.upper()} {path}")
                
                step = RequestStep(
                    step_id=step_id,
                    name=step_name,
                    url=urljoin(base_url, path),
                    method=HttpMethod(method.upper())
                )
                
                # Add headers if needed
                if operation.get("requestBody"):
                    content_type = self._get_content_type(operation["requestBody"])
                    if content_type:
                        step.headers = {"Content-Type": content_type}
                
                # Generate payload for POST/PUT/PATCH
                if method.upper() in ["POST", "PUT", "PATCH"] and operation.get("requestBody"):
                    payload = self._generate_payload_from_schema(operation["requestBody"])
                    if payload:
                        step.payload = payload
                
                # Add variable extraction for responses
                if operation.get("responses", {}).get("200") or operation.get("responses", {}).get("201"):
                    response_schema = self._get_response_schema(operation["responses"])
                    if response_schema:
                        extract_vars = self._generate_extract_variables(response_schema, step_id)
                        if extract_vars:
                            step.extract_variables = extract_vars
                
                workflow_steps.append(step)
                step_counter += 1
        
        if not workflow_steps:
            raise ValueError("No valid endpoints found to generate workflow")
        
        # Create workflow configuration
        workflow_config = WorkflowConfig(
            workflow_name=workflow_name,
            description=f"Generated workflow from OpenAPI spec: {spec.get('info', {}).get('title', 'Unknown')}",
            steps=workflow_steps,
            virtual_users=1,
            duration="60s",
            load_pattern=LoadPattern.CONSTANT
        )
        
        await self.publish_event(EventType.WORKFLOW_STARTED, {
            "spec_url": spec_url,
            "workflow_name": workflow_name,
            "step_count": len(workflow_steps)
        })
        
        return workflow_config
    
    async def _analyze_api_endpoints_internal(self, spec_url: str) -> Dict[str, Any]:
        """Internal endpoint analysis logic."""
        spec = await self._load_openapi_spec_internal(spec_url)
        
        analysis = {
            "api_info": spec.get("info", {}),
            "servers": spec.get("servers", []),
            "endpoint_summary": {
                "total_paths": 0,
                "total_operations": 0,
                "methods": {},
                "paths_with_parameters": 0,
                "authenticated_endpoints": 0
            },
            "endpoints": []
        }
        
        paths = spec.get("paths", {})
        analysis["endpoint_summary"]["total_paths"] = len(paths)
        
        for path, path_item in paths.items():
            has_parameters = "{" in path
            if has_parameters:
                analysis["endpoint_summary"]["paths_with_parameters"] += 1
            
            for method, operation in path_item.items():
                if method.upper() not in [m.value for m in HttpMethod]:
                    continue
                
                analysis["endpoint_summary"]["total_operations"] += 1
                
                # Count methods
                method_upper = method.upper()
                analysis["endpoint_summary"]["methods"][method_upper] = \
                    analysis["endpoint_summary"]["methods"].get(method_upper, 0) + 1
                
                # Check for authentication
                if operation.get("security") or spec.get("security"):
                    analysis["endpoint_summary"]["authenticated_endpoints"] += 1
                
                # Add endpoint details
                endpoint_info = {
                    "path": path,
                    "method": method_upper,
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "operationId": operation.get("operationId", ""),
                    "has_parameters": has_parameters,
                    "has_request_body": bool(operation.get("requestBody")),
                    "requires_auth": bool(operation.get("security") or spec.get("security")),
                    "response_codes": list(operation.get("responses", {}).keys())
                }
                
                analysis["endpoints"].append(endpoint_info)
        
        return analysis
    
    async def _validate_openapi_spec_internal(self, spec_url: str) -> List[str]:
        """Internal OpenAPI specification validation logic."""
        errors = []
        
        try:
            spec = await self._load_openapi_spec_internal(spec_url)
        except Exception as e:
            return [f"Failed to load specification: {str(e)}"]
        
        # Basic structure validation
        if not isinstance(spec, dict):
            errors.append("Specification must be a JSON object")
            return errors
        
        # Check required fields
        if "openapi" not in spec:
            errors.append("Missing required field: openapi")
        
        if "info" not in spec:
            errors.append("Missing required field: info")
        else:
            info = spec["info"]
            if "title" not in info:
                errors.append("Missing required field: info.title")
            if "version" not in info:
                errors.append("Missing required field: info.version")
        
        if "paths" not in spec:
            errors.append("Missing required field: paths")
        
        # Validate OpenAPI version
        openapi_version = spec.get("openapi", "")
        if not openapi_version.startswith("3."):
            errors.append(f"Unsupported OpenAPI version: {openapi_version}. Only 3.x is supported.")
        
        # Validate paths
        paths = spec.get("paths", {})
        if not paths:
            errors.append("No paths defined in specification")
        
        for path, path_item in paths.items():
            if not path.startswith("/"):
                errors.append(f"Path '{path}' must start with '/'")
            
            if not isinstance(path_item, dict):
                errors.append(f"Path item for '{path}' must be an object")
                continue
            
            # Validate operations
            for method, operation in path_item.items():
                if method.upper() in [m.value for m in HttpMethod]:
                    if not isinstance(operation, dict):
                        errors.append(f"Operation {method.upper()} {path} must be an object")
                        continue
                    
                    if "responses" not in operation:
                        errors.append(f"Missing responses for {method.upper()} {path}")
        
        # Validate servers if present
        servers = spec.get("servers", [])
        for i, server in enumerate(servers):
            if "url" not in server:
                errors.append(f"Server {i} missing required field: url")
        
        return errors
    
    def _get_content_type(self, request_body: Dict[str, Any]) -> Optional[str]:
        """Extract content type from request body specification."""
        content = request_body.get("content", {})
        if "application/json" in content:
            return "application/json"
        elif "application/xml" in content:
            return "application/xml"
        elif "application/x-www-form-urlencoded" in content:
            return "application/x-www-form-urlencoded"
        elif content:
            # Return first available content type
            return list(content.keys())[0]
        return None
    
    def _generate_payload_from_schema(self, request_body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Generate example payload from OpenAPI schema."""
        content = request_body.get("content", {})
        
        # Try JSON first
        if "application/json" in content:
            schema = content["application/json"].get("schema", {})
            return self._generate_example_from_schema(schema)
        
        # Try other content types
        for content_type, content_spec in content.items():
            schema = content_spec.get("schema", {})
            if schema:
                return self._generate_example_from_schema(schema)
        
        return None
    
    def _generate_example_from_schema(self, schema: Dict[str, Any]) -> Any:
        """Generate example data from JSON schema."""
        schema_type = schema.get("type", "object")
        
        if schema_type == "object":
            properties = schema.get("properties", {})
            example = {}
            
            for prop_name, prop_schema in properties.items():
                example[prop_name] = self._generate_example_from_schema(prop_schema)
            
            return example
        
        elif schema_type == "array":
            items_schema = schema.get("items", {})
            return [self._generate_example_from_schema(items_schema)]
        
        elif schema_type == "string":
            return schema.get("example", "example_string")
        
        elif schema_type == "integer":
            return schema.get("example", 123)
        
        elif schema_type == "number":
            return schema.get("example", 123.45)
        
        elif schema_type == "boolean":
            return schema.get("example", True)
        
        else:
            return None
    
    def _get_response_schema(self, responses: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract response schema from responses specification."""
        # Try successful responses first
        for status_code in ["200", "201", "202"]:
            if status_code in responses:
                response = responses[status_code]
                content = response.get("content", {})
                
                if "application/json" in content:
                    return content["application/json"].get("schema")
                
                # Try other content types
                for content_spec in content.values():
                    schema = content_spec.get("schema")
                    if schema:
                        return schema
        
        return None
    
    def _generate_extract_variables(self, schema: Dict[str, Any], step_id: str) -> Optional[Dict[str, str]]:
        """Generate variable extraction configuration from response schema."""
        if not schema or schema.get("type") != "object":
            return None
        
        extract_vars = {}
        properties = schema.get("properties", {})
        
        # Extract common fields
        for field_name in ["id", "uuid", "token", "access_token", "user_id"]:
            if field_name in properties:
                extract_vars[f"{step_id}_{field_name}"] = f"$.{field_name}"
        
        return extract_vars if extract_vars else None
    
    async def health_check_impl(self) -> Dict[str, Any]:
        """Implementation-specific health check."""
        cache_size = len(self._openapi_cache)
        
        healthy = cache_size <= 100  # Arbitrary limit for cached specs
        status = "healthy" if healthy else "degraded"
        message = f"Cached specs: {cache_size}"
        
        if not healthy:
            message += " (high cache usage)"
        
        return {
            "healthy": healthy,
            "component": "openapi_service",
            "status": status,
            "message": message,
            "cached_specs": cache_size,
            "supported_openapi_versions": ["3.0", "3.1"],
            "warning": "High cache usage" if not healthy else None
        }