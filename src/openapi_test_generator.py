"""
Advanced test generation engine for OpenAPI specifications.

This module provides intelligent test generation capabilities including
smart workflow detection, authentication flow analysis, and data-driven
test scenario creation.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
import logging

from openapi_models import (
    OpenAPISpec, EndpointAnalysis, APIAnalysis, HttpMethod,
    TestGenerationOptions, TestScenario, SecuritySchemeType
)
from multi_request_models import K6MultiRequestConfig, RequestStep
from openapi_processor import OpenAPIProcessor

logger = logging.getLogger(__name__)


@dataclass
class WorkflowPattern:
    """Represents a detected workflow pattern."""
    name: str
    description: str
    endpoints: List[Tuple[str, HttpMethod]]
    dependencies: Dict[str, str]
    variables_to_extract: Dict[str, str]
    pattern_type: str  # 'auth', 'crud', 'search', 'pagination', 'upload'
    priority: int = 1


class AuthFlowDetector:
    """Detects authentication flows in OpenAPI specifications."""
    
    def __init__(self):
        self.auth_patterns = {
            'login': r'(login|signin|auth|authenticate)',
            'logout': r'(logout|signout)',
            'refresh': r'(refresh|renew).*token',
            'register': r'(register|signup)',
            'reset': r'(reset|forgot).*password',
            'verify': r'(verify|confirm)',
        }
    
    def detect_auth_flows(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect authentication workflow patterns."""
        flows = []
        
        # Group auth endpoints by type
        auth_endpoints_by_type = self._categorize_auth_endpoints(analysis.auth_endpoints)
        
        # Standard login flow
        if 'login' in auth_endpoints_by_type:
            login_flow = self._create_login_flow(auth_endpoints_by_type, analysis)
            if login_flow:
                flows.append(login_flow)
        
        # OAuth flow detection
        oauth_flow = self._detect_oauth_flow(analysis)
        if oauth_flow:
            flows.append(oauth_flow)
        
        # Registration flow
        if 'register' in auth_endpoints_by_type:
            register_flow = self._create_registration_flow(auth_endpoints_by_type, analysis)
            if register_flow:
                flows.append(register_flow)
        
        # Password reset flow
        if 'reset' in auth_endpoints_by_type and 'verify' in auth_endpoints_by_type:
            reset_flow = self._create_password_reset_flow(auth_endpoints_by_type, analysis)
            if reset_flow:
                flows.append(reset_flow)
        
        return flows
    
    def _categorize_auth_endpoints(self, auth_endpoints: List[EndpointAnalysis]) -> Dict[str, List[EndpointAnalysis]]:
        """Categorize authentication endpoints by their function."""
        categories = {}
        
        for endpoint in auth_endpoints:
            path_lower = endpoint.path.lower()
            operation_id = (endpoint.operation.operation_id or "").lower()
            summary = (endpoint.operation.summary or "").lower()
            
            text_to_analyze = f"{path_lower} {operation_id} {summary}"
            
            for category, pattern in self.auth_patterns.items():
                if re.search(pattern, text_to_analyze):
                    if category not in categories:
                        categories[category] = []
                    categories[category].append(endpoint)
                    break
        
        return categories
    
    def _create_login_flow(self, auth_endpoints_by_type: Dict[str, List[EndpointAnalysis]], 
                          analysis: APIAnalysis) -> Optional[WorkflowPattern]:
        """Create a login workflow pattern."""
        login_endpoints = auth_endpoints_by_type.get('login', [])
        if not login_endpoints:
            return None
        
        # Use POST login endpoint if available, otherwise first one
        login_endpoint = None
        for ep in login_endpoints:
            if ep.method == HttpMethod.POST:
                login_endpoint = ep
                break
        
        if not login_endpoint:
            login_endpoint = login_endpoints[0]
        
        endpoints = [(login_endpoint.path, login_endpoint.method)]
        
        # Add a protected endpoint to test the token
        protected_endpoints = [ep for ep in analysis.endpoints 
                             if ep.requires_auth and not self._is_auth_endpoint(ep)]
        if protected_endpoints:
            test_endpoint = protected_endpoints[0]
            endpoints.append((test_endpoint.path, test_endpoint.method))
        
        return WorkflowPattern(
            name="Login Authentication Flow",
            description="Login and test authentication token",
            endpoints=endpoints,
            dependencies={'step_1': 'step_0'} if len(endpoints) > 1 else {},
            variables_to_extract={
                'step_0': '$.token|$.access_token|$.accessToken',
            },
            pattern_type='auth',
            priority=10
        )
    
    def _detect_oauth_flow(self, analysis: APIAnalysis) -> Optional[WorkflowPattern]:
        """Detect OAuth 2.0 flows."""
        security_schemes = analysis.spec.get_security_schemes()
        
        oauth_schemes = {name: scheme for name, scheme in security_schemes.items() 
                        if scheme.type == SecuritySchemeType.OAUTH2}
        
        if not oauth_schemes:
            return None
        
        # Look for OAuth-related endpoints
        oauth_endpoints = []
        for endpoint in analysis.endpoints:
            path_lower = endpoint.path.lower()
            if any(keyword in path_lower for keyword in ['oauth', 'token', 'authorize']):
                oauth_endpoints.append((endpoint.path, endpoint.method))
        
        if oauth_endpoints:
            return WorkflowPattern(
                name="OAuth 2.0 Flow",
                description="OAuth authentication flow",
                endpoints=oauth_endpoints,
                dependencies={},
                variables_to_extract={'step_0': '$.access_token'},
                pattern_type='auth',
                priority=8
            )
        
        return None
    
    def _create_registration_flow(self, auth_endpoints_by_type: Dict[str, List[EndpointAnalysis]],
                                analysis: APIAnalysis) -> Optional[WorkflowPattern]:
        """Create a registration workflow pattern."""
        register_endpoints = auth_endpoints_by_type.get('register', [])
        if not register_endpoints:
            return None
        
        # Find POST registration endpoint
        register_endpoint = None
        for ep in register_endpoints:
            if ep.method == HttpMethod.POST:
                register_endpoint = ep
                break
        
        if not register_endpoint:
            return None
        
        endpoints = [(register_endpoint.path, register_endpoint.method)]
        
        # Add verification step if available
        if 'verify' in auth_endpoints_by_type:
            verify_endpoint = auth_endpoints_by_type['verify'][0]
            endpoints.append((verify_endpoint.path, verify_endpoint.method))
        
        return WorkflowPattern(
            name="User Registration Flow",
            description="Register new user account",
            endpoints=endpoints,
            dependencies={'step_1': 'step_0'} if len(endpoints) > 1 else {},
            variables_to_extract={
                'step_0': '$.userId|$.id',
            },
            pattern_type='auth',
            priority=7
        )
    
    def _create_password_reset_flow(self, auth_endpoints_by_type: Dict[str, List[EndpointAnalysis]],
                                  analysis: APIAnalysis) -> Optional[WorkflowPattern]:
        """Create a password reset workflow pattern."""
        reset_endpoints = auth_endpoints_by_type.get('reset', [])
        verify_endpoints = auth_endpoints_by_type.get('verify', [])
        
        if not reset_endpoints or not verify_endpoints:
            return None
        
        endpoints = [
            (reset_endpoints[0].path, reset_endpoints[0].method),
            (verify_endpoints[0].path, verify_endpoints[0].method)
        ]
        
        return WorkflowPattern(
            name="Password Reset Flow",
            description="Reset user password",
            endpoints=endpoints,
            dependencies={'step_1': 'step_0'},
            variables_to_extract={
                'step_0': '$.resetToken|$.token',
            },
            pattern_type='auth',
            priority=5
        )
    
    def _is_auth_endpoint(self, endpoint: EndpointAnalysis) -> bool:
        """Check if endpoint is authentication-related."""
        auth_keywords = ['auth', 'login', 'signin', 'token', 'oauth', 'session', 'logout', 'register']
        path_lower = endpoint.path.lower()
        operation_id = (endpoint.operation.operation_id or "").lower()
        summary = (endpoint.operation.summary or "").lower()
        
        return any(keyword in text for keyword in auth_keywords 
                  for text in [path_lower, operation_id, summary])


class CRUDFlowDetector:
    """Detects CRUD workflow patterns in OpenAPI specifications."""
    
    def detect_crud_flows(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect CRUD workflow patterns."""
        flows = []
        
        for resource_name, endpoints in analysis.crud_resources.items():
            if len(endpoints) < 2:
                continue
            
            # Standard CRUD flow: Create -> Read -> Update -> Delete
            crud_flow = self._create_standard_crud_flow(resource_name, endpoints)
            if crud_flow:
                flows.append(crud_flow)
            
            # Read-only flow for GET-heavy APIs
            read_flow = self._create_read_only_flow(resource_name, endpoints)
            if read_flow:
                flows.append(read_flow)
        
        return flows
    
    def _create_standard_crud_flow(self, resource_name: str, 
                                 endpoints: List[EndpointAnalysis]) -> Optional[WorkflowPattern]:
        """Create a standard CRUD workflow."""
        # Find endpoints by operation type
        operations = {}
        for endpoint in endpoints:
            if endpoint.method == HttpMethod.POST:
                operations['create'] = endpoint
            elif endpoint.method == HttpMethod.GET:
                # Distinguish between list (no path params) and get (with path params)
                if endpoint.path_params:
                    operations['read'] = endpoint
                else:
                    operations['list'] = endpoint
            elif endpoint.method == HttpMethod.PUT:
                operations['update'] = endpoint
            elif endpoint.method == HttpMethod.PATCH:
                operations['patch'] = endpoint
            elif endpoint.method == HttpMethod.DELETE:
                operations['delete'] = endpoint
        
        # Build flow sequence
        flow_endpoints = []
        dependencies = {}
        variables_to_extract = {}
        
        # Create
        if 'create' in operations:
            flow_endpoints.append((operations['create'].path, operations['create'].method))
            variables_to_extract['step_0'] = f'$.id|$.{resource_name}Id'
        
        # Read (if we created something)
        if 'read' in operations and flow_endpoints:
            flow_endpoints.append((operations['read'].path, operations['read'].method))
            dependencies['step_1'] = 'step_0'
        
        # Update
        if 'update' in operations and flow_endpoints:
            step_index = len(flow_endpoints)
            flow_endpoints.append((operations['update'].path, operations['update'].method))
            dependencies[f'step_{step_index}'] = 'step_0'
        elif 'patch' in operations and flow_endpoints:
            step_index = len(flow_endpoints)
            flow_endpoints.append((operations['patch'].path, operations['patch'].method))
            dependencies[f'step_{step_index}'] = 'step_0'
        
        # Delete
        if 'delete' in operations and flow_endpoints:
            step_index = len(flow_endpoints)
            flow_endpoints.append((operations['delete'].path, operations['delete'].method))
            dependencies[f'step_{step_index}'] = 'step_0'
        
        if len(flow_endpoints) < 2:
            return None
        
        return WorkflowPattern(
            name=f"{resource_name.title()} CRUD Flow",
            description=f"Complete CRUD operations for {resource_name}",
            endpoints=flow_endpoints,
            dependencies=dependencies,
            variables_to_extract=variables_to_extract,
            pattern_type='crud',
            priority=6
        )
    
    def _create_read_only_flow(self, resource_name: str, 
                             endpoints: List[EndpointAnalysis]) -> Optional[WorkflowPattern]:
        """Create a read-only workflow for GET-heavy APIs."""
        get_endpoints = [ep for ep in endpoints if ep.method == HttpMethod.GET]
        
        if len(get_endpoints) < 2:
            return None
        
        # Sort by complexity (list endpoints first, then detail endpoints)
        get_endpoints.sort(key=lambda ep: len(ep.path_params))
        
        flow_endpoints = [(ep.path, ep.method) for ep in get_endpoints]
        
        # Extract ID from list for detail requests
        dependencies = {}
        variables_to_extract = {}
        
        if len(get_endpoints) > 1 and not get_endpoints[0].path_params and get_endpoints[1].path_params:
            # First endpoint is list, second is detail
            variables_to_extract['step_0'] = f'$.[0].id|$.data[0].id'
            dependencies['step_1'] = 'step_0'
        
        return WorkflowPattern(
            name=f"{resource_name.title()} Read Flow",
            description=f"Read operations for {resource_name}",
            endpoints=flow_endpoints,
            dependencies=dependencies,
            variables_to_extract=variables_to_extract,
            pattern_type='crud',
            priority=4
        )


class AdvancedPatternDetector:
    """Detects advanced API patterns like search, pagination, file upload."""
    
    def detect_advanced_patterns(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect advanced API patterns."""
        patterns = []
        
        # Search patterns
        search_patterns = self._detect_search_patterns(analysis)
        patterns.extend(search_patterns)
        
        # Pagination patterns
        pagination_patterns = self._detect_pagination_patterns(analysis)
        patterns.extend(pagination_patterns)
        
        # File upload patterns
        upload_patterns = self._detect_upload_patterns(analysis)
        patterns.extend(upload_patterns)
        
        # Batch operation patterns
        batch_patterns = self._detect_batch_patterns(analysis)
        patterns.extend(batch_patterns)
        
        return patterns
    
    def _detect_search_patterns(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect search and filter patterns."""
        patterns = []
        
        search_endpoints = []
        for endpoint in analysis.endpoints:
            path_lower = endpoint.path.lower()
            operation_id = (endpoint.operation.operation_id or "").lower()
            
            # Look for search-related keywords
            if any(keyword in path_lower or keyword in operation_id 
                   for keyword in ['search', 'query', 'find', 'filter']):
                search_endpoints.append(endpoint)
            
            # Look for query parameters that suggest search
            if any(param.name.lower() in ['search', 'query', 'filter', 'q'] 
                   for param in endpoint.query_params):
                search_endpoints.append(endpoint)
        
        if search_endpoints:
            # Create search flow
            flow_endpoints = [(ep.path, ep.method) for ep in search_endpoints[:3]]
            
            patterns.append(WorkflowPattern(
                name="Search and Filter Flow",
                description="Test search and filtering capabilities",
                endpoints=flow_endpoints,
                dependencies={},
                variables_to_extract={},
                pattern_type='search',
                priority=3
            ))
        
        return patterns
    
    def _detect_pagination_patterns(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect pagination patterns."""
        patterns = []
        
        paginated_endpoints = []
        for endpoint in analysis.endpoints:
            # Look for pagination parameters
            pagination_params = ['page', 'limit', 'offset', 'size', 'per_page', 'pageSize']
            if any(param.name.lower() in pagination_params for param in endpoint.query_params):
                paginated_endpoints.append(endpoint)
        
        if paginated_endpoints:
            # Create pagination test flow
            endpoint = paginated_endpoints[0]
            flow_endpoints = [
                (endpoint.path, endpoint.method),  # Page 1
                (endpoint.path, endpoint.method),  # Page 2
            ]
            
            patterns.append(WorkflowPattern(
                name="Pagination Flow",
                description="Test pagination functionality",
                endpoints=flow_endpoints,
                dependencies={},
                variables_to_extract={'step_0': '$.total|$.totalPages'},
                pattern_type='pagination',
                priority=2
            ))
        
        return patterns
    
    def _detect_upload_patterns(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect file upload patterns."""
        patterns = []
        
        upload_endpoints = []
        for endpoint in analysis.endpoints:
            if endpoint.request_body_schema:
                # Look for multipart/form-data or file-related content types
                if endpoint.operation.request_body:
                    content_types = endpoint.operation.request_body.content.keys()
                    if any('multipart' in ct or 'form-data' in ct for ct in content_types):
                        upload_endpoints.append(endpoint)
            
            # Look for upload-related paths
            path_lower = endpoint.path.lower()
            if any(keyword in path_lower for keyword in ['upload', 'file', 'attachment', 'media']):
                upload_endpoints.append(endpoint)
        
        if upload_endpoints:
            patterns.append(WorkflowPattern(
                name="File Upload Flow",
                description="Test file upload functionality",
                endpoints=[(ep.path, ep.method) for ep in upload_endpoints[:2]],
                dependencies={},
                variables_to_extract={'step_0': '$.fileId|$.id'},
                pattern_type='upload',
                priority=3
            ))
        
        return patterns
    
    def _detect_batch_patterns(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect batch operation patterns."""
        patterns = []
        
        batch_endpoints = []
        for endpoint in analysis.endpoints:
            path_lower = endpoint.path.lower()
            operation_id = (endpoint.operation.operation_id or "").lower()
            
            if any(keyword in path_lower or keyword in operation_id 
                   for keyword in ['batch', 'bulk', 'multiple']):
                batch_endpoints.append(endpoint)
        
        if batch_endpoints:
            patterns.append(WorkflowPattern(
                name="Batch Operations Flow",
                description="Test batch/bulk operations",
                endpoints=[(ep.path, ep.method) for ep in batch_endpoints],
                dependencies={},
                variables_to_extract={},
                pattern_type='batch',
                priority=2
            ))
        
        return patterns


class SmartTestGenerator:
    """Advanced test generator with intelligent pattern detection."""
    
    def __init__(self):
        self.processor = OpenAPIProcessor()
        self.auth_detector = AuthFlowDetector()
        self.crud_detector = CRUDFlowDetector()
        self.advanced_detector = AdvancedPatternDetector()
    
    def generate_intelligent_tests(self, analysis: APIAnalysis, 
                                 options: TestGenerationOptions) -> List[K6MultiRequestConfig]:
        """Generate intelligent test scenarios based on detected patterns."""
        test_configs = []
        
        # Generate single endpoint tests if requested
        if options.generate_single_endpoint_tests:
            single_tests = self.processor.generate_single_endpoint_tests(analysis, options)
            test_configs.extend(single_tests)
        
        # Detect and generate workflow patterns
        if options.generate_workflow_tests:
            workflows = self._detect_all_patterns(analysis)
            
            # Sort by priority and generate tests
            workflows.sort(key=lambda w: w.priority, reverse=True)
            
            for workflow in workflows[:10]:  # Limit to top 10 workflows
                try:
                    test_config = self._generate_workflow_test(workflow, analysis, options)
                    if test_config:
                        test_configs.append(test_config)
                except Exception as e:
                    logger.warning(f"Failed to generate test for workflow {workflow.name}: {e}")
                    continue
        
        logger.info(f"Generated {len(test_configs)} intelligent test configurations")
        return test_configs
    
    def _detect_all_patterns(self, analysis: APIAnalysis) -> List[WorkflowPattern]:
        """Detect all workflow patterns in the API."""
        patterns = []
        
        # Authentication patterns
        auth_patterns = self.auth_detector.detect_auth_flows(analysis)
        patterns.extend(auth_patterns)
        
        # CRUD patterns
        crud_patterns = self.crud_detector.detect_crud_flows(analysis)
        patterns.extend(crud_patterns)
        
        # Advanced patterns
        advanced_patterns = self.advanced_detector.detect_advanced_patterns(analysis)
        patterns.extend(advanced_patterns)
        
        logger.info(f"Detected {len(patterns)} workflow patterns")
        return patterns
    
    def _generate_workflow_test(self, pattern: WorkflowPattern, analysis: APIAnalysis,
                              options: TestGenerationOptions) -> Optional[K6MultiRequestConfig]:
        """Generate a test configuration from a workflow pattern."""
        steps = []
        base_url = analysis.spec.get_base_url()
        
        for i, (path, method) in enumerate(pattern.endpoints):
            # Find the endpoint analysis
            endpoint = None
            for ep in analysis.endpoints:
                if ep.path == path and ep.method == method:
                    endpoint = ep
                    break
            
            if not endpoint:
                logger.warning(f"Endpoint not found: {method} {path}")
                continue
            
            # Create workflow step
            step = self._create_pattern_step(
                endpoint, base_url, i, pattern, analysis, options
            )
            if step:
                steps.append(step)
        
        if not steps:
            return None
        
        return K6MultiRequestConfig(
            workflow_name=pattern.name.replace(' ', '_').lower(),
            description=pattern.description,
            virtual_users=options.virtual_users,
            duration=options.duration,
            steps=steps
        )
    
    def _create_pattern_step(self, endpoint: EndpointAnalysis, base_url: str, step_index: int,
                           pattern: WorkflowPattern, analysis: APIAnalysis,
                           options: TestGenerationOptions) -> Optional[RequestStep]:
        """Create a workflow step optimized for the detected pattern."""
        try:
            # Generate test data based on pattern type
            test_data = self._generate_pattern_test_data(endpoint, pattern, options)
            
            # Build URL
            url = base_url + endpoint.path
            
            # Handle path parameters with pattern-aware substitution
            for param in endpoint.path_params:
                param_name = param.name
                
                # Check if this should come from a previous step
                step_key = f'step_{step_index}'
                if (step_key in pattern.dependencies and 
                    step_index > 0 and 
                    pattern.variables_to_extract.get(f'step_{step_index-1}')):
                    
                    # Use template variable from previous step
                    if 'id' in param_name.lower():
                        url = url.replace(f'{{{param_name}}}', '{{extracted_id}}')
                    else:
                        url = url.replace(f'{{{param_name}}}', f'{{{{extracted_{param_name}}}}}')
                else:
                    # Use generated value
                    param_value = test_data.get('path_params', {}).get(param_name, f'test_{param_name}')
                    url = url.replace(f'{{{param_name}}}', str(param_value))
            
            # Create step
            step_id = f"step_{step_index}"
            step_name = self._generate_step_name(endpoint, pattern, step_index)
            
            # Extract variables based on pattern
            extract_variables = {}
            if step_index == 0 and pattern.variables_to_extract.get('step_0'):
                extract_path = pattern.variables_to_extract['step_0']
                # Parse multiple possible extraction paths
                for path in extract_path.split('|'):
                    var_name = self._extract_variable_name(path.strip())
                    extract_variables[var_name] = path.strip()
                    # Also add generic extraction
                    if 'id' in path.lower():
                        extract_variables['extracted_id'] = path.strip()
            
            # Set up authentication if needed
            headers = test_data.get('headers', {})
            if endpoint.requires_auth and step_index > 0:
                # Add auth token from previous auth step
                if not any('authorization' in h.lower() for h in headers.keys()):
                    headers['Authorization'] = 'Bearer {{auth_token}}'
            
            # Handle special pattern-specific configurations
            if pattern.pattern_type == 'auth' and step_index == 0:
                # Auth endpoints might need credentials
                if endpoint.method == HttpMethod.POST:
                    if not test_data.get('payload'):
                        test_data['payload'] = self._generate_auth_payload(endpoint, pattern)
            
            # Set dependencies
            depends_on = []
            step_key = f'step_{step_index}'
            if step_key in pattern.dependencies:
                depends_on.append(pattern.dependencies[step_key])
            
            step = RequestStep(
                step_id=step_id,
                name=step_name,
                url=url,
                method=endpoint.method.value,
                payload=test_data.get('payload'),
                headers=headers,
                query_params=test_data.get('query_params', {}),
                extract_variables=extract_variables if extract_variables else None,
                depends_on=depends_on if depends_on else None,
                timeout=f"{int(options.duration.rstrip('s')) // 2}s",
                think_time=options.think_time
            )
            
            return step
            
        except Exception as e:
            logger.error(f"Failed to create pattern step for {endpoint.path}: {e}")
            return None
    
    def _generate_pattern_test_data(self, endpoint: EndpointAnalysis, 
                                  pattern: WorkflowPattern, options: TestGenerationOptions) -> Dict[str, Any]:
        """Generate test data optimized for the specific pattern type."""
        # Use the base processor for standard data generation
        path_params = self.processor._generate_path_parameters(endpoint.path_params, options)
        query_params = self.processor._generate_query_parameters(endpoint.query_params, options)
        headers = self.processor._generate_headers(endpoint.header_params, options)
        
        payload = None
        if endpoint.request_body_schema:
            payload = self.processor._generate_payload_from_schema(endpoint.request_body_schema, options)
        
        # Pattern-specific optimizations
        if pattern.pattern_type == 'search' and query_params:
            # Add realistic search terms
            for param_name in query_params.keys():
                if 'search' in param_name.lower() or 'q' in param_name.lower():
                    query_params[param_name] = 'test query'
                elif 'filter' in param_name.lower():
                    query_params[param_name] = 'active'
        
        elif pattern.pattern_type == 'pagination':
            # Add pagination parameters
            for param_name in query_params.keys():
                if param_name.lower() in ['page', 'pagesize', 'per_page']:
                    query_params[param_name] = '1'
                elif param_name.lower() in ['limit', 'size']:
                    query_params[param_name] = '10'
                elif param_name.lower() == 'offset':
                    query_params[param_name] = '0'
        
        return {
            'path_params': path_params,
            'query_params': query_params,
            'headers': headers,
            'payload': payload
        }
    
    def _generate_auth_payload(self, endpoint: EndpointAnalysis, pattern: WorkflowPattern) -> Dict[str, Any]:
        """Generate authentication payload."""
        if pattern.name.lower().startswith('login'):
            return {
                'username': 'testuser@example.com',
                'password': 'testpassword123',
                'email': 'testuser@example.com'
            }
        elif pattern.name.lower().startswith('register'):
            return {
                'username': 'newuser@example.com',
                'password': 'newpassword123',
                'email': 'newuser@example.com',
                'firstName': 'Test',
                'lastName': 'User'
            }
        
        return {}
    
    def _generate_step_name(self, endpoint: EndpointAnalysis, pattern: WorkflowPattern, step_index: int) -> str:
        """Generate a descriptive step name."""
        if endpoint.operation.summary:
            return endpoint.operation.summary
        
        # Pattern-specific naming
        if pattern.pattern_type == 'auth':
            if step_index == 0:
                return f"Authenticate user"
            else:
                return f"Test authenticated access"
        elif pattern.pattern_type == 'crud':
            crud_actions = ['Create', 'Read', 'Update', 'Delete']
            if step_index < len(crud_actions):
                return f"{crud_actions[step_index]} {pattern.name.split()[0]}"
        
        return f"{endpoint.method.value} {endpoint.path}"
    
    def _extract_variable_name(self, json_path: str) -> str:
        """Extract a meaningful variable name from JSON path."""
        if 'token' in json_path.lower():
            return 'auth_token'
        elif 'id' in json_path.lower():
            return 'extracted_id'
        else:
            # Extract last part of path
            parts = json_path.replace('$.', '').split('.')
            return f"extracted_{parts[-1]}" if parts else 'extracted_value'