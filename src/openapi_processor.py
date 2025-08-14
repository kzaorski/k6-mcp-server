"""
OpenAPI Processor for K6 MCP Server.

This module handles parsing, analysis, and test generation from OpenAPI specifications.
"""

import json
import random
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse
import logging

import requests
from pydantic import ValidationError

from openapi_models import (
    OpenAPISpec, OpenAPIOperation, EndpointAnalysis, APIAnalysis,
    HttpMethod, ParameterLocation, TestGenerationOptions, TestScenario,
    OpenAPIParameter, SecuritySchemeType, EndpointSelector
)
from multi_request_models import K6MultiRequestConfig, RequestStep
from security_utils import (
    safe_json_parse, sanitize_url, validate_safe_path,
    InputValidationError, SecurityError
)
from data_generators import DataGenerator

logger = logging.getLogger(__name__)


class OpenAPIProcessorError(Exception):
    """Base exception for OpenAPI processor errors."""
    pass


class OpenAPIProcessor:
    """
    Processes OpenAPI specifications and generates K6 test configurations.
    """

    def __init__(self, max_spec_size: int = 50_000_000):
        self.max_spec_size = max_spec_size
        self.data_generator = DataGenerator()

    async def load_openapi_spec(self, source: Union[str, Path, Dict[str, Any]]) -> OpenAPISpec:
        """
        Load OpenAPI specification from various sources.
        
        Args:
            source: URL, file path, or dictionary containing the spec
            
        Returns:
            Parsed OpenAPI specification
            
        Raises:
            OpenAPIProcessorError: If loading or parsing fails
        """
        try:
            if isinstance(source, dict):
                # Already a dictionary
                spec_dict = source
            elif isinstance(source, (str, Path)):
                source_str = str(source)
                
                if source_str.startswith(('http://', 'https://')):
                    # Load from URL
                    spec_dict = await self._load_from_url(source_str)
                else:
                    # Load from file
                    spec_dict = await self._load_from_file(Path(source_str))
            else:
                raise OpenAPIProcessorError(f"Unsupported source type: {type(source)}")

            # Validate and parse the specification
            spec = OpenAPISpec(**spec_dict)
            logger.info(f"Successfully loaded OpenAPI spec: {spec.info.title} v{spec.info.version}")
            
            return spec

        except ValidationError as e:
            logger.error(f"OpenAPI validation error: {e}")
            raise OpenAPIProcessorError(f"Invalid OpenAPI specification: {e}")
        except Exception as e:
            logger.error(f"Error loading OpenAPI spec: {e}")
            raise OpenAPIProcessorError(f"Failed to load OpenAPI specification: {e}")

    async def _load_from_url(self, url: str) -> Dict[str, Any]:
        """Load OpenAPI spec from URL."""
        try:
            # Validate URL
            sanitized_url = sanitize_url(url)
            
            # Make request with security headers and limits
            response = requests.get(
                sanitized_url,
                timeout=30,
                headers={'User-Agent': 'K6-MCP-Server/1.0'},
                stream=True
            )
            response.raise_for_status()
            
            # Check content size
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.max_spec_size:
                raise OpenAPIProcessorError(f"Specification too large: {content_length} bytes")
            
            # Read content with size limit
            content = ""
            total_size = 0
            for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
                total_size += len(chunk)
                if total_size > self.max_spec_size:
                    raise OpenAPIProcessorError(f"Specification exceeds size limit: {self.max_spec_size} bytes")
                content += chunk
            
            # Parse YAML or JSON
            return self._parse_content(content)

        except requests.RequestException as e:
            raise OpenAPIProcessorError(f"Failed to fetch OpenAPI spec from URL: {e}")

    async def _load_from_file(self, file_path: Path) -> Dict[str, Any]:
        """Load OpenAPI spec from file."""
        try:
            # Validate file path (if base dir is configured)
            # In production, you might want to restrict to specific directories
            if not file_path.exists():
                raise OpenAPIProcessorError(f"File not found: {file_path}")
            
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > self.max_spec_size:
                raise OpenAPIProcessorError(f"File too large: {file_size} bytes")
            
            # Read and parse file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return self._parse_content(content)

        except IOError as e:
            raise OpenAPIProcessorError(f"Failed to read file: {e}")

    def _parse_content(self, content: str) -> Dict[str, Any]:
        """Parse YAML or JSON content."""
        try:
            # Try JSON first
            return safe_json_parse(content, max_size=self.max_spec_size)
        except (json.JSONDecodeError, InputValidationError):
            try:
                # Try YAML
                return yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise OpenAPIProcessorError(f"Invalid YAML/JSON format: {e}")

    def analyze_api(self, spec: OpenAPISpec) -> APIAnalysis:
        """
        Analyze OpenAPI specification and extract test-relevant information.
        
        Args:
            spec: OpenAPI specification
            
        Returns:
            Complete API analysis
        """
        logger.info("Analyzing OpenAPI specification...")
        
        # Analyze individual endpoints
        endpoints = []
        auth_endpoints = []
        crud_resources = {}
        
        for path, path_item in spec.paths.items():
            for method, operation in path_item.get_operations().items():
                analysis = self._analyze_endpoint(path, method, operation, spec)
                endpoints.append(analysis)
                
                # Categorize endpoints
                if self._is_auth_endpoint(path, operation):
                    auth_endpoints.append(analysis)
                
                if analysis.is_crud_operation and analysis.crud_resource:
                    if analysis.crud_resource not in crud_resources:
                        crud_resources[analysis.crud_resource] = []
                    crud_resources[analysis.crud_resource].append(analysis)

        # Build dependency graph
        dependency_graph = self._build_dependency_graph(endpoints)
        
        # Generate workflow suggestions
        workflow_suggestions = self._generate_workflow_suggestions(endpoints, crud_resources, auth_endpoints)
        
        analysis = APIAnalysis(
            spec=spec,
            endpoints=endpoints,
            auth_endpoints=auth_endpoints,
            crud_resources=crud_resources,
            dependency_graph=dependency_graph,
            workflow_suggestions=workflow_suggestions
        )
        
        logger.info(f"Analysis complete: {len(endpoints)} endpoints, {len(auth_endpoints)} auth endpoints, "
                   f"{len(crud_resources)} CRUD resources")
        
        return analysis

    def _analyze_endpoint(self, path: str, method: HttpMethod, operation: OpenAPIOperation, 
                         spec: OpenAPISpec) -> EndpointAnalysis:
        """Analyze a single endpoint."""
        # Extract parameters by location
        all_params = (operation.parameters or []) + (spec.paths[path].parameters or [])
        path_params = [p for p in all_params if p.in_ == ParameterLocation.PATH]
        query_params = [p for p in all_params if p.in_ == ParameterLocation.QUERY]
        header_params = [p for p in all_params if p.in_ == ParameterLocation.HEADER]
        
        # Extract request body schema
        request_body_schema = None
        if operation.request_body:
            content = operation.request_body.content
            if 'application/json' in content:
                request_body_schema = content['application/json'].get('schema')
        
        # Extract response schemas
        response_schemas = {}
        for status_code, response in operation.responses.items():
            if response.content and 'application/json' in response.content:
                response_schemas[status_code] = response.content['application/json'].get('schema', {})
        
        # Determine if authentication is required
        requires_auth = self._requires_authentication(operation, spec)
        
        # CRUD analysis
        is_crud, resource = self._analyze_crud_operation(path, method, operation)
        
        return EndpointAnalysis(
            path=path,
            method=method,
            operation=operation,
            requires_auth=requires_auth,
            path_params=path_params,
            query_params=query_params,
            header_params=header_params,
            request_body_schema=request_body_schema,
            response_schemas=response_schemas,
            is_crud_operation=is_crud,
            crud_resource=resource
        )

    def _requires_authentication(self, operation: OpenAPIOperation, spec: OpenAPISpec) -> bool:
        """Determine if an operation requires authentication."""
        # Check operation-level security
        if operation.security is not None:
            return len(operation.security) > 0
        
        # Check global security
        if spec.security:
            return True
        
        return False

    def _analyze_crud_operation(self, path: str, method: HttpMethod, 
                               operation: OpenAPIOperation) -> Tuple[bool, Optional[str]]:
        """Analyze if this is a CRUD operation and extract resource name."""
        # Extract resource name from path
        # Examples: /users/{id} -> users, /api/v1/products/{productId} -> products
        path_segments = [seg for seg in path.split('/') if seg and not seg.startswith('{')]
        
        if not path_segments:
            return False, None
        
        # Common CRUD patterns
        resource_segment = None
        for segment in reversed(path_segments):
            # Skip version segments (v1, v2, api, etc.)
            if re.match(r'^(api|v\d+)$', segment, re.IGNORECASE):
                continue
            resource_segment = segment
            break
        
        if not resource_segment:
            return False, None
        
        # Determine CRUD operation type
        crud_patterns = {
            HttpMethod.GET: ['get', 'read', 'fetch', 'list'],
            HttpMethod.POST: ['create', 'add', 'new'],
            HttpMethod.PUT: ['update', 'replace', 'modify'],
            HttpMethod.PATCH: ['update', 'modify', 'patch'],
            HttpMethod.DELETE: ['delete', 'remove', 'destroy']
        }
        
        # Check if this matches CRUD patterns
        if method in crud_patterns:
            # Check path structure (collection vs item)
            has_id_param = any('{' in segment for segment in path.split('/'))
            
            if method == HttpMethod.GET:
                # GET can be both list (collection) and read (item)
                return True, resource_segment
            elif method == HttpMethod.POST:
                # POST is usually create on collection
                return not has_id_param, resource_segment
            elif method in [HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE]:
                # These usually operate on specific items
                return has_id_param, resource_segment
        
        return False, None

    def _is_auth_endpoint(self, path: str, operation: OpenAPIOperation) -> bool:
        """Check if this endpoint is authentication-related."""
        auth_keywords = ['auth', 'login', 'signin', 'token', 'oauth', 'session', 'logout', 'refresh']
        
        path_lower = path.lower()
        operation_id = (operation.operation_id or "").lower()
        summary = (operation.summary or "").lower()
        description = (operation.description or "").lower()
        
        return any(keyword in text for keyword in auth_keywords 
                  for text in [path_lower, operation_id, summary, description])

    def _build_dependency_graph(self, endpoints: List[EndpointAnalysis]) -> Dict[str, List[str]]:
        """Build dependency graph between operations."""
        dependency_graph = {}
        
        # Simple heuristic: operations that require auth depend on auth operations
        auth_operation_ids = []
        for endpoint in endpoints:
            if endpoint.operation.operation_id:
                if self._is_auth_endpoint(endpoint.path, endpoint.operation):
                    auth_operation_ids.append(endpoint.operation.operation_id)
        
        for endpoint in endpoints:
            if endpoint.operation.operation_id:
                dependencies = []
                
                # If requires auth and not an auth endpoint, depend on auth
                if endpoint.requires_auth and not self._is_auth_endpoint(endpoint.path, endpoint.operation):
                    dependencies.extend(auth_operation_ids)
                
                # CRUD dependencies: create before read/update/delete
                if endpoint.is_crud_operation and endpoint.crud_resource:
                    for other_endpoint in endpoints:
                        if (other_endpoint.crud_resource == endpoint.crud_resource and 
                            other_endpoint.method == HttpMethod.POST and
                            endpoint.method in [HttpMethod.GET, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE] and
                            other_endpoint.operation.operation_id):
                            # Path parameters suggest this operates on specific item
                            if endpoint.path_params:
                                dependencies.append(other_endpoint.operation.operation_id)
                
                if dependencies:
                    dependency_graph[endpoint.operation.operation_id] = list(set(dependencies))
        
        return dependency_graph

    def _generate_workflow_suggestions(self, endpoints: List[EndpointAnalysis], 
                                     crud_resources: Dict[str, List[EndpointAnalysis]],
                                     auth_endpoints: List[EndpointAnalysis]) -> List[Dict[str, Any]]:
        """Generate suggested workflow scenarios."""
        suggestions = []
        
        # Authentication workflow
        if auth_endpoints:
            suggestions.append({
                'name': 'Authentication Flow',
                'description': 'Test authentication endpoints',
                'type': 'auth',
                'endpoints': [(ep.path, ep.method.value) for ep in auth_endpoints]
            })
        
        # CRUD workflows
        for resource, resource_endpoints in crud_resources.items():
            if len(resource_endpoints) >= 2:  # At least 2 operations for a meaningful workflow
                suggestions.append({
                    'name': f'{resource.title()} CRUD Workflow',
                    'description': f'Complete CRUD operations for {resource}',
                    'type': 'crud',
                    'resource': resource,
                    'endpoints': [(ep.path, ep.method.value) for ep in resource_endpoints]
                })
        
        # Complete API workflow
        if len(endpoints) > 3:
            suggestions.append({
                'name': 'Complete API Workflow',
                'description': 'Test all major API endpoints in sequence',
                'type': 'complete',
                'endpoints': [(ep.path, ep.method.value) for ep in endpoints[:10]]  # Limit to first 10
            })
        
        return suggestions

    def generate_single_endpoint_tests(self, analysis: APIAnalysis, 
                                     options: TestGenerationOptions) -> List[K6MultiRequestConfig]:
        """Generate individual tests for each endpoint."""
        tests = []
        
        for endpoint in analysis.endpoints:
            try:
                test_config = self._create_single_endpoint_test(endpoint, analysis.spec, options)
                if test_config:
                    tests.append(test_config)
            except Exception as e:
                logger.warning(f"Failed to generate test for {endpoint.method} {endpoint.path}: {e}")
                continue
        
        logger.info(f"Generated {len(tests)} single endpoint tests")
        return tests

    def _create_single_endpoint_test(self, endpoint: EndpointAnalysis, spec: OpenAPISpec,
                                   options: TestGenerationOptions) -> Optional[K6MultiRequestConfig]:
        """Create a test configuration for a single endpoint."""
        base_url = spec.get_base_url()
        
        # Generate test data
        path_params = self._generate_path_parameters(endpoint.path_params, options)
        query_params = self._generate_query_parameters(endpoint.query_params, options)
        headers = self._generate_headers(endpoint.header_params, options)
        payload = None
        
        if endpoint.request_body_schema:
            payload = self._generate_payload_from_schema(endpoint.request_body_schema, options)
        
        # Build URL with path parameters
        url = base_url + endpoint.path
        for param_name, param_value in path_params.items():
            url = url.replace(f'{{{param_name}}}', str(param_value))
        
        # Create request step
        step_id = f"{endpoint.method.value.lower()}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}"
        step_name = endpoint.operation.summary or f"{endpoint.method.value} {endpoint.path}"
        
        step = RequestStep(
            step_id=step_id,
            name=step_name,
            url=url,
            method=endpoint.method.value,
            payload=payload,
            headers=headers,
            query_params=query_params,
            timeout=f"{int(options.duration.rstrip('s')) // 2}s",
            think_time=options.think_time
        )
        
        # Generate workflow name and description
        workflow_name = f"{endpoint.method.value}_{endpoint.path.replace('/', '_').replace('{', '').replace('}', '')}_test"
        description = f"Single endpoint test for {endpoint.method.value} {endpoint.path}"
        
        return K6MultiRequestConfig(
            workflow_name=workflow_name,
            description=description,
            virtual_users=options.virtual_users,
            duration=options.duration,
            steps=[step]
        )

    def generate_workflow_test(self, analysis: APIAnalysis, scenario: TestScenario,
                             options: TestGenerationOptions) -> Optional[K6MultiRequestConfig]:
        """Generate a workflow test from a test scenario."""
        steps = []
        base_url = analysis.spec.get_base_url()
        
        for i, (path, method) in enumerate(scenario.endpoints):
            # Find the endpoint analysis
            endpoint = None
            for ep in analysis.endpoints:
                if ep.path == path and ep.method.value == method:
                    endpoint = ep
                    break
            
            if not endpoint:
                logger.warning(f"Endpoint not found: {method} {path}")
                continue
            
            # Generate step
            step = self._create_workflow_step(endpoint, base_url, i, scenario, options)
            if step:
                steps.append(step)
        
        if not steps:
            logger.warning(f"No steps generated for scenario: {scenario.name}")
            return None
        
        return K6MultiRequestConfig(
            workflow_name=scenario.name.replace(' ', '_').lower(),
            description=scenario.description,
            virtual_users=options.virtual_users,
            duration=options.duration,
            steps=steps
        )

    def _create_workflow_step(self, endpoint: EndpointAnalysis, base_url: str, step_index: int,
                            scenario: TestScenario, options: TestGenerationOptions) -> Optional[RequestStep]:
        """Create a workflow step for an endpoint."""
        try:
            # Generate test data
            path_params = self._generate_path_parameters(endpoint.path_params, options)
            query_params = self._generate_query_parameters(endpoint.query_params, options)
            headers = self._generate_headers(endpoint.header_params, options)
            payload = None
            
            if endpoint.request_body_schema:
                payload = self._generate_payload_from_schema(endpoint.request_body_schema, options)
            
            # Build URL with path parameters  
            url = base_url + endpoint.path
            for param_name, param_value in path_params.items():
                # For workflow steps, use template variables for path params that might come from previous steps
                if f"step_{step_index-1}" in scenario.dependencies:
                    # Use template variable if this might be extracted from previous step
                    url = url.replace(f'{{{param_name}}}', f'{{{{extracted_{param_name}}}}}')
                else:
                    url = url.replace(f'{{{param_name}}}', str(param_value))
            
            # Create step
            step_id = f"step_{step_index}_{endpoint.method.value.lower()}"
            step_name = endpoint.operation.summary or f"{endpoint.method.value} {endpoint.path}"
            
            # Extract variables for next steps
            extract_variables = {}
            if endpoint.method == HttpMethod.POST and endpoint.is_crud_operation:
                # Extract ID from creation response
                extract_variables['created_id'] = '$.id'
                extract_variables[f'extracted_{endpoint.crud_resource}_id'] = '$.id'
            
            # Add authentication token extraction for auth endpoints
            if self._is_auth_endpoint(endpoint.path, endpoint.operation):
                extract_variables['auth_token'] = '$.token'
                extract_variables['access_token'] = '$.access_token'
                # Add to headers for subsequent requests
                if 'Authorization' not in headers:
                    headers['Authorization'] = 'Bearer {{access_token}}'
            
            # Set up dependencies
            depends_on = []
            if step_index > 0:
                depends_on.append(f"step_{step_index-1}")
            
            step = RequestStep(
                step_id=step_id,
                name=step_name,
                url=url,
                method=endpoint.method.value,
                payload=payload,
                headers=headers,
                query_params=query_params,
                extract_variables=extract_variables if extract_variables else None,
                depends_on=depends_on if depends_on else None,
                timeout=f"{int(options.duration.rstrip('s')) // 2}s",
                think_time=options.think_time
            )
            
            return step
            
        except Exception as e:
            logger.error(f"Failed to create workflow step for {endpoint.path}: {e}")
            return None

    def _generate_path_parameters(self, params: List[OpenAPIParameter], 
                                options: TestGenerationOptions) -> Dict[str, Any]:
        """Generate values for path parameters."""
        param_values = {}
        
        for param in params:
            if param.example is not None:
                param_values[param.name] = param.example
            elif param.schema_:
                param_values[param.name] = self._generate_value_from_schema(param.schema_, options)
            else:
                # Default values based on common parameter names
                if 'id' in param.name.lower():
                    param_values[param.name] = 1
                else:
                    param_values[param.name] = f"test_{param.name}"
        
        return param_values

    def _generate_query_parameters(self, params: List[OpenAPIParameter],
                                 options: TestGenerationOptions) -> Dict[str, str]:
        """Generate values for query parameters."""
        param_values = {}
        
        for param in params:
            if param.required or param.example is not None:
                if param.example is not None:
                    param_values[param.name] = str(param.example)
                elif param.schema_:
                    value = self._generate_value_from_schema(param.schema_, options)
                    param_values[param.name] = str(value)
                else:
                    param_values[param.name] = f"test_{param.name}"
        
        return param_values

    def _generate_headers(self, params: List[OpenAPIParameter],
                        options: TestGenerationOptions) -> Dict[str, str]:
        """Generate values for header parameters."""
        headers = {'Content-Type': 'application/json'}
        
        for param in params:
            if param.required or param.example is not None:
                if param.example is not None:
                    headers[param.name] = str(param.example)
                elif param.schema_:
                    value = self._generate_value_from_schema(param.schema_, options)
                    headers[param.name] = str(value)
                else:
                    headers[param.name] = f"test_{param.name}"
        
        return headers

    def _generate_payload_from_schema(self, schema: Dict[str, Any], 
                                    options: TestGenerationOptions) -> Dict[str, Any]:
        """Generate payload data from JSON schema."""
        result = self._generate_value_from_schema(schema, options)
        # Ensure we always return a dict for payload
        if isinstance(result, dict):
            return result
        else:
            # If schema didn't produce a dict, create a simple one
            return {"data": result}

    def _generate_value_from_schema(self, schema: Dict[str, Any], 
                                  options: TestGenerationOptions) -> Any:
        """Generate a value from JSON schema."""
        if not schema:
            return None
        
        schema_type = schema.get('type', 'string')
        
        # Use example if provided
        if 'example' in schema:
            return schema['example']
        
        # Generate based on type
        if schema_type == 'string':
            if 'enum' in schema:
                return schema['enum'][0]
            format_type = schema.get('format', '')
            if format_type == 'email':
                return 'test@example.com'
            elif format_type == 'date':
                return '2023-01-01'
            elif format_type == 'date-time':
                return '2023-01-01T00:00:00Z'
            elif format_type == 'uuid':
                return str(DataGenerator.generate_uuid())
            else:
                max_length = min(schema.get('maxLength', options.max_string_length), options.max_string_length)
                return DataGenerator.generate_random_string(min(10, max_length))
        
        elif schema_type == 'integer':
            minimum = schema.get('minimum', 1)
            maximum = schema.get('maximum', 100)
            return DataGenerator.generate_random_number(minimum, maximum)
        
        elif schema_type == 'number':
            minimum = schema.get('minimum', 1.0)
            maximum = schema.get('maximum', 100.0)
            return round(random.uniform(minimum, maximum), 2)
        
        elif schema_type == 'boolean':
            return True
        
        elif schema_type == 'array':
            items_schema = schema.get('items', {})
            max_items = min(schema.get('maxItems', options.max_array_items), options.max_array_items)
            return [self._generate_value_from_schema(items_schema, options) for _ in range(max_items)]
        
        elif schema_type == 'object':
            properties = schema.get('properties', {})
            required = schema.get('required', [])
            
            result = {}
            for prop_name, prop_schema in properties.items():
                if prop_name in required or len(result) < 3:  # Include required + some optional
                    result[prop_name] = self._generate_value_from_schema(prop_schema, options)
            
            return result
        
        else:
            return f"test_value"

    def filter_endpoints(self, analysis: APIAnalysis, options: TestGenerationOptions) -> List[EndpointAnalysis]:
        """
        Filter endpoints based on selection criteria in TestGenerationOptions.
        
        Args:
            analysis: Complete API analysis
            options: Test generation options with filtering criteria
            
        Returns:
            List of filtered endpoints
        """
        endpoints = analysis.endpoints.copy()
        
        # Apply endpoint selection if specified
        if options.selected_endpoints:
            selected_set = {(sel.path, sel.method.value) for sel in options.selected_endpoints if sel.include}
            endpoints = [ep for ep in endpoints if (ep.path, ep.method.value) in selected_set]
        
        # Apply method filtering
        if options.include_methods:
            endpoints = [ep for ep in endpoints if ep.method in options.include_methods]
        if options.exclude_methods:
            endpoints = [ep for ep in endpoints if ep.method not in options.exclude_methods]
        
        # Apply tag filtering
        if options.include_tags:
            endpoints = [ep for ep in endpoints 
                        if ep.operation.tags and any(tag in ep.operation.tags for tag in options.include_tags)]
        if options.exclude_tags:
            endpoints = [ep for ep in endpoints 
                        if not ep.operation.tags or not any(tag in ep.operation.tags for tag in options.exclude_tags)]
        
        # Apply custom filtering criteria
        if options.endpoint_filter:
            endpoints = self._apply_custom_filter(endpoints, options.endpoint_filter)
        
        logger.info(f"Filtered {len(analysis.endpoints)} endpoints to {len(endpoints)} endpoints")
        return endpoints

    def _apply_custom_filter(self, endpoints: List[EndpointAnalysis], 
                           filter_criteria: Dict[str, Any]) -> List[EndpointAnalysis]:
        """Apply custom filtering criteria to endpoints."""
        filtered = endpoints.copy()
        
        # Filter by path pattern
        if 'path_pattern' in filter_criteria:
            pattern = re.compile(filter_criteria['path_pattern'])
            filtered = [ep for ep in filtered if pattern.search(ep.path)]
        
        # Filter by operation ID pattern
        if 'operation_id_pattern' in filter_criteria:
            pattern = re.compile(filter_criteria['operation_id_pattern'])
            filtered = [ep for ep in filtered 
                       if ep.operation.operation_id and pattern.search(ep.operation.operation_id)]
        
        # Filter by authentication requirement
        if 'requires_auth' in filter_criteria:
            requires_auth = filter_criteria['requires_auth']
            filtered = [ep for ep in filtered if ep.requires_auth == requires_auth]
        
        # Filter by CRUD operations
        if 'is_crud' in filter_criteria:
            is_crud = filter_criteria['is_crud']
            filtered = [ep for ep in filtered if ep.is_crud_operation == is_crud]
        
        # Filter by summary/description content
        if 'description_contains' in filter_criteria:
            search_term = filter_criteria['description_contains'].lower()
            filtered = [ep for ep in filtered 
                       if (ep.operation.summary and search_term in ep.operation.summary.lower()) or
                          (ep.operation.description and search_term in ep.operation.description.lower())]
        
        return filtered

    def generate_selective_tests(self, analysis: APIAnalysis, 
                                options: TestGenerationOptions) -> List[K6MultiRequestConfig]:
        """
        Generate tests for selected endpoints only.
        
        Args:
            analysis: Complete API analysis
            options: Test generation options with endpoint selection
            
        Returns:
            List of K6 test configurations for selected endpoints
        """
        logger.info("Generating selective tests for chosen endpoints...")
        
        # Filter endpoints based on selection criteria
        filtered_endpoints = self.filter_endpoints(analysis, options)
        
        if not filtered_endpoints:
            logger.warning("No endpoints match the selection criteria")
            return []
        
        test_configs = []
        
        # Generate individual endpoint tests if requested
        if options.generate_single_endpoint_tests:
            # Create a modified analysis with only filtered endpoints
            filtered_analysis = APIAnalysis(
                spec=analysis.spec,
                endpoints=filtered_endpoints,
                auth_endpoints=[ep for ep in analysis.auth_endpoints if ep in filtered_endpoints],
                crud_resources={k: [ep for ep in v if ep in filtered_endpoints] 
                              for k, v in analysis.crud_resources.items() 
                              if any(ep in filtered_endpoints for ep in v)},
                dependency_graph=analysis.dependency_graph,
                workflow_suggestions=analysis.workflow_suggestions
            )
            single_tests = self.generate_single_endpoint_tests(filtered_analysis, options)
            test_configs.extend(single_tests)
        
        # Generate workflow tests for filtered endpoints
        if options.generate_workflow_tests and len(filtered_endpoints) > 1:
            # Group endpoints by resource for CRUD workflows
            resource_groups = {}
            for endpoint in filtered_endpoints:
                if endpoint.crud_resource:
                    resource = endpoint.crud_resource
                    if resource not in resource_groups:
                        resource_groups[resource] = []
                    resource_groups[resource].append(endpoint)
            
            # Generate CRUD workflows for each resource
            for resource, resource_endpoints in resource_groups.items():
                if len(resource_endpoints) > 1:
                    workflow_config = self._generate_selective_crud_workflow(
                        analysis, resource, resource_endpoints, options
                    )
                    if workflow_config:
                        test_configs.append(workflow_config)
        
        logger.info(f"Generated {len(test_configs)} selective test configurations")
        return test_configs

    def _generate_selective_crud_workflow(self, analysis: APIAnalysis, resource: str,
                                        endpoints: List[EndpointAnalysis], 
                                        options: TestGenerationOptions) -> Optional[K6MultiRequestConfig]:
        """Generate a CRUD workflow for selected endpoints of a resource."""
        # Sort endpoints by logical CRUD order: POST (create), GET (read), PUT (update), DELETE (delete)
        method_priority = {'POST': 1, 'GET': 2, 'PUT': 3, 'PATCH': 3, 'DELETE': 4}
        
        # Separate list operations from individual operations
        list_ops = [ep for ep in endpoints if '{' not in ep.path]
        individual_ops = [ep for ep in endpoints if '{' in ep.path]
        
        # Sort individual operations by method priority
        individual_ops.sort(key=lambda ep: method_priority.get(ep.method.value, 5))
        
        # Build the workflow: create -> read -> update -> delete, with list operations at appropriate points
        workflow_steps = []
        base_url = analysis.spec.get_base_url()
        
        # Add list operation at the beginning if available
        list_get = next((ep for ep in list_ops if ep.method == HttpMethod.GET), None)
        if list_get:
            step = self._create_single_endpoint_test(list_get, analysis.spec, options)
            if step and step.steps:
                list_step = step.steps[0]  # Get the first (and only) step
                list_step.step_id = f"list_{resource}"
                list_step.name = f"List {resource.title()}"
                workflow_steps.append(list_step)
        
        # Add individual operations
        for endpoint in individual_ops:
            step_config = self._create_single_endpoint_test(endpoint, analysis.spec, options)
            if step_config and step_config.steps:
                step = step_config.steps[0]  # Get the first (and only) step
                step.step_id = f"{endpoint.method.value.lower()}_{resource}"
                step.name = f"{endpoint.method.value.title()} {resource.title()}"
                
                # Add dependencies for proper ordering
                if endpoint.method == HttpMethod.GET and '{' in endpoint.path:
                    # This is a GET by ID operation, it should depend on CREATE
                    create_step = next((s for s in workflow_steps if s.step_id.startswith('post_')), None)
                    if create_step:
                        step.depends_on = [create_step.step_id]
                        # Extract resource ID from create response
                        if create_step.extract_variables is None:
                            create_step.extract_variables = {}
                        create_step.extract_variables[f"{resource}_id"] = f"$.id"
                        
                        # Use extracted ID in URL
                        step.url = step.url.replace(f"{{{resource}Id}}", f"{{{{{resource}_id}}}}")
                        step.url = step.url.replace(f"{{{resource}_id}}", f"{{{{{resource}_id}}}}")
                
                elif endpoint.method in [HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE]:
                    # Depend on create operation
                    create_step = next((s for s in workflow_steps if s.step_id.startswith('post_')), None)
                    if create_step:
                        step.depends_on = [create_step.step_id]
                        # Ensure create step extracts the ID
                        if create_step.extract_variables is None:
                            create_step.extract_variables = {}
                        create_step.extract_variables[f"{resource}_id"] = f"$.id"
                        
                        # Use extracted ID in URL
                        step.url = step.url.replace(f"{{{resource}Id}}", f"{{{{{resource}_id}}}}")
                        step.url = step.url.replace(f"{{{resource}_id}}", f"{{{{{resource}_id}}}}")
                
                workflow_steps.append(step)
        
        if not workflow_steps:
            return None
        
        return K6MultiRequestConfig(
            workflow_name=f"{resource}_selective_crud_workflow",
            description=f"Selective CRUD workflow for {resource} resource with chosen endpoints",
            virtual_users=options.virtual_users,
            duration=options.duration,
            steps=workflow_steps
        )

    def preview_selected_endpoints(self, analysis: APIAnalysis, 
                                 options: TestGenerationOptions) -> Dict[str, Any]:
        """
        Preview which endpoints would be selected and tested.
        
        Args:
            analysis: Complete API analysis
            options: Test generation options with endpoint selection
            
        Returns:
            Preview information about selected endpoints
        """
        filtered_endpoints = self.filter_endpoints(analysis, options)
        
        preview = {
            'total_endpoints_available': len(analysis.endpoints),
            'selected_endpoints_count': len(filtered_endpoints),
            'selected_endpoints': []
        }
        
        for endpoint in filtered_endpoints:
            ep_info = {
                'path': endpoint.path,
                'method': endpoint.method.value,
                'summary': endpoint.operation.summary,
                'requires_auth': endpoint.requires_auth,
                'is_crud_operation': endpoint.is_crud_operation,
                'crud_resource': endpoint.crud_resource,
                'tags': endpoint.operation.tags or [],
                'parameters_count': len(endpoint.path_params + endpoint.query_params + endpoint.header_params),
                'has_request_body': endpoint.request_body_schema is not None
            }
            
            # Add priority if using selected_endpoints
            if options.selected_endpoints:
                selector = next(
                    (sel for sel in options.selected_endpoints 
                     if sel.path == endpoint.path and sel.method == endpoint.method), 
                    None
                )
                if selector:
                    ep_info['priority'] = selector.priority
                    ep_info['custom_name'] = selector.custom_name
                    ep_info['custom_data'] = selector.custom_data
            
            preview['selected_endpoints'].append(ep_info)
        
        # Group by resource for better organization
        resources = {}
        for ep_info in preview['selected_endpoints']:
            resource = ep_info.get('crud_resource', 'other')
            if resource not in resources:
                resources[resource] = []
            resources[resource].append(ep_info)
        
        preview['endpoints_by_resource'] = resources
        
        # Analyze test generation potential
        preview['test_generation_analysis'] = {
            'single_endpoint_tests': len(filtered_endpoints) if options.generate_single_endpoint_tests else 0,
            'possible_crud_workflows': len([r for r, eps in resources.items() if r != 'other' and len(eps) > 1]),
            'auth_endpoints': len([ep for ep in filtered_endpoints if ep.requires_auth]),
            'endpoints_with_examples': len([ep for ep in filtered_endpoints 
                                          if ep.operation.parameters and any(p.example for p in ep.operation.parameters)])
        }
        
        return preview

    def batch_select_endpoints(self, analysis: APIAnalysis, 
                             batch_criteria: List[Dict[str, Any]]) -> List[EndpointSelector]:
        """
        Batch select endpoints using multiple criteria.
        
        Args:
            analysis: Complete API analysis
            batch_criteria: List of selection criteria dictionaries
            
        Returns:
            List of EndpointSelector objects for all matching endpoints
        """
        selected_endpoints = []
        
        for criteria in batch_criteria:
            # Create options for this criteria
            options = TestGenerationOptions(
                endpoint_filter=criteria.get("filter", {}),
                include_methods=[HttpMethod(m) for m in criteria.get("include_methods", [])] if criteria.get("include_methods") else None,
                exclude_methods=[HttpMethod(m) for m in criteria.get("exclude_methods", [])] if criteria.get("exclude_methods") else None,
                include_tags=criteria.get("include_tags"),
                exclude_tags=criteria.get("exclude_tags")
            )
            
            # Filter endpoints
            filtered = self.filter_endpoints(analysis, options)
            
            # Convert to selectors
            priority = criteria.get("priority", 1)
            custom_name_template = criteria.get("custom_name_template", "")
            
            for endpoint in filtered:
                # Generate custom name if template provided
                custom_name = None
                if custom_name_template:
                    custom_name = custom_name_template.format(
                        method=endpoint.method.value,
                        path=endpoint.path,
                        operation_id=endpoint.operation.operation_id or "",
                        summary=endpoint.operation.summary or "",
                        resource=endpoint.crud_resource or ""
                    )
                
                selector = EndpointSelector(
                    path=endpoint.path,
                    method=endpoint.method,
                    include=True,
                    priority=priority,
                    custom_name=custom_name
                )
                selected_endpoints.append(selector)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_selectors = []
        for selector in selected_endpoints:
            key = (selector.path, selector.method.value)
            if key not in seen:
                seen.add(key)
                unique_selectors.append(selector)
        
        logger.info(f"Batch selected {len(unique_selectors)} unique endpoints from {len(batch_criteria)} criteria")
        return unique_selectors

    def create_endpoint_selection_presets(self, analysis: APIAnalysis) -> Dict[str, List[EndpointSelector]]:
        """
        Create common endpoint selection presets for quick access.
        
        Args:
            analysis: Complete API analysis
            
        Returns:
            Dictionary of preset names to endpoint selectors
        """
        presets = {}
        
        # Preset 1: All authentication endpoints
        auth_options = TestGenerationOptions(
            endpoint_filter={"requires_auth": False}  # Auth endpoints typically don't require auth themselves
        )
        auth_filtered = self.filter_endpoints(analysis, auth_options)
        auth_endpoints = [ep for ep in auth_filtered if any(keyword in ep.path.lower() 
                                                           for keyword in ['auth', 'login', 'token', 'session'])]
        presets["authentication_endpoints"] = [
            EndpointSelector(path=ep.path, method=ep.method, priority=1, custom_name=f"Auth: {ep.operation.summary}")
            for ep in auth_endpoints
        ]
        
        # Preset 2: All CRUD endpoints
        crud_selectors = []
        for resource, resource_endpoints in analysis.crud_resources.items():
            for ep in resource_endpoints:
                custom_name = f"{resource.title()} {ep.method.value}"
                crud_selectors.append(
                    EndpointSelector(path=ep.path, method=ep.method, priority=2, custom_name=custom_name)
                )
        presets["crud_endpoints"] = crud_selectors
        
        # Preset 3: Read-only endpoints (GET methods)
        readonly_options = TestGenerationOptions(include_methods=[HttpMethod.GET])
        readonly_filtered = self.filter_endpoints(analysis, readonly_options)
        presets["readonly_endpoints"] = [
            EndpointSelector(path=ep.path, method=ep.method, priority=3, custom_name=f"Read: {ep.operation.summary}")
            for ep in readonly_filtered
        ]
        
        # Preset 4: Write endpoints (POST, PUT, PATCH, DELETE)
        write_options = TestGenerationOptions(
            include_methods=[HttpMethod.POST, HttpMethod.PUT, HttpMethod.PATCH, HttpMethod.DELETE]
        )
        write_filtered = self.filter_endpoints(analysis, write_options)
        presets["write_endpoints"] = [
            EndpointSelector(path=ep.path, method=ep.method, priority=1, custom_name=f"Write: {ep.operation.summary}")
            for ep in write_filtered
        ]
        
        # Preset 5: High priority endpoints (based on common critical operations)
        critical_patterns = [r'/.*login.*', r'/.*auth.*', r'/.*user.*', r'/.*order.*', r'/.*payment.*']
        high_priority = []
        for pattern in critical_patterns:
            pattern_options = TestGenerationOptions(
                endpoint_filter={"path_pattern": pattern}
            )
            pattern_filtered = self.filter_endpoints(analysis, pattern_options)
            high_priority.extend(pattern_filtered)
        
        # Remove duplicates
        seen_high_priority = set()
        unique_high_priority = []
        for ep in high_priority:
            key = (ep.path, ep.method.value)
            if key not in seen_high_priority:
                seen_high_priority.add(key)
                unique_high_priority.append(ep)
        
        presets["high_priority_endpoints"] = [
            EndpointSelector(path=ep.path, method=ep.method, priority=1, custom_name=f"Critical: {ep.operation.summary}")
            for ep in unique_high_priority
        ]
        
        logger.info(f"Created {len(presets)} endpoint selection presets")
        for preset_name, selectors in presets.items():
            logger.info(f"  {preset_name}: {len(selectors)} endpoints")
        
        return presets