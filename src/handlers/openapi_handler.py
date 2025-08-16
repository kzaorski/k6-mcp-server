"""
OpenAPI Handler.

Handles MCP tool calls for OpenAPI operations including specification
loading, test generation, and API analysis.
"""

import logging
from typing import Any, Dict

from core.base import BaseHandler
from core.config import AppConfig
from services.openapi_service import OpenAPIService

logger = logging.getLogger(__name__)


class OpenAPIHandler(BaseHandler):
    """
    Handler for OpenAPI-related MCP tool calls.
    
    Processes requests for OpenAPI specification processing,
    test generation, and API analysis with proper validation.
    """
    
    def __init__(self, config: AppConfig, openapi_service: OpenAPIService):
        super().__init__(config)
        self.openapi_service = openapi_service
    
    async def handle(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle OpenAPI tool calls."""
        
        try:
            if name == "load_openapi_spec":
                return await self._handle_load_openapi_spec(arguments)
            
            elif name == "generate_tests_from_openapi":
                return await self._handle_generate_tests_from_spec(arguments)
            
            elif name == "generate_workflow_from_openapi":
                return await self._handle_generate_workflow_from_spec(arguments)
            
            elif name == "analyze_openapi_endpoints":
                return await self._handle_analyze_api_endpoints(arguments)
            
            elif name == "validate_openapi_spec":
                return await self._handle_validate_openapi_spec(arguments)
            
            else:
                return self.create_error_response(f"Unknown OpenAPI tool: {name}")
                
        except Exception as e:
            self.logger.error(f"Error handling OpenAPI {name}: {e}", exc_info=True)
            return self.create_error_response(f"OpenAPI handler error: {str(e)}")
    
    async def _handle_load_openapi_spec(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle OpenAPI specification loading."""
        spec_url = arguments.get("spec_url")
        if not spec_url:
            return self.create_error_response("spec_url is required")
        
        operation_id = self.log_operation_start("load_openapi_spec", spec_url=spec_url)
        
        try:
            result = await self.openapi_service.load_openapi_spec(spec_url)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                spec = result.data
                spec_info = spec.get("info", {})
                paths = spec.get("paths", {})
                servers = spec.get("servers", [])
                
                # Count operations
                total_operations = 0
                methods = {}
                for path_item in paths.values():
                    for method, operation in path_item.items():
                        if method.upper() in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
                            total_operations += 1
                            methods[method.upper()] = methods.get(method.upper(), 0) + 1
                
                load_summary = f"""✅ **OpenAPI Specification Loaded Successfully**

📋 **API Information:**
• Title: {spec_info.get('title', 'Unknown')}
• Version: {spec_info.get('version', 'Unknown')}
• Description: {spec_info.get('description', 'No description')}

🌐 **Servers:**"""
                
                if servers:
                    for i, server in enumerate(servers, 1):
                        load_summary += f"\n{i}. {server.get('url', 'Unknown URL')}"
                        if server.get('description'):
                            load_summary += f" - {server['description']}"
                else:
                    load_summary += "\n• No servers defined"
                
                load_summary += f"""

📊 **API Endpoints:**
• Total Paths: {len(paths)}
• Total Operations: {total_operations}
• HTTP Methods: {', '.join(f'{method}({count})' for method, count in methods.items())}

✅ **Ready for Processing:**
• Use 'generate_tests_from_openapi' to create K6 tests
• Use 'generate_workflow_from_openapi' to create workflows
• Use 'analyze_openapi_endpoints' for detailed analysis"""
                
                return self.create_success_response(load_summary)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to load OpenAPI specification: {str(e)}")
    
    async def _handle_generate_tests_from_spec(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test generation from OpenAPI specification."""
        spec_url = arguments.get("spec_url")
        base_url = arguments.get("base_url")
        test_config = arguments.get("test_config", {})
        
        if not spec_url:
            return self.create_error_response("spec_url is required")
        
        operation_id = self.log_operation_start("generate_tests_from_spec", spec_url=spec_url)
        
        try:
            result = await self.openapi_service.generate_tests_from_spec(spec_url, base_url, test_config)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                generated_tests = result.data
                test_summary = f"""✅ **Tests Generated from OpenAPI Specification**

📊 **Generation Summary:**
• Specification: {spec_url}
• Base URL: {base_url or 'Auto-detected from spec'}
• Generated Tests: {len(generated_tests)}

📋 **Generated Test Configurations:**"""
                
                # Group tests by method
                method_groups = {}
                for test in generated_tests:
                    method = test.method.value
                    if method not in method_groups:
                        method_groups[method] = []
                    method_groups[method].append(test)
                
                for method, tests in method_groups.items():
                    test_summary += f"\n\n**{method} Operations ({len(tests)}):**"
                    for test in tests[:5]:  # Show first 5 tests per method
                        test_summary += f"\n• {test.url}"
                        if test.payload:
                            test_summary += " (with payload)"
                    
                    if len(tests) > 5:
                        test_summary += f"\n• ... and {len(tests) - 5} more {method} tests"
                
                test_summary += f"""

🔧 **Test Configuration Applied:**
• Virtual Users: {test_config.get('virtual_users', 1)}
• Duration: {test_config.get('duration', '30s')}
• Load Pattern: {test_config.get('load_pattern', 'constant')}

⚠️ **Next Steps:**
• Each generated test can be executed using 'run_k6_single_test'
• Review and customize test configurations as needed
• Consider creating workflows for related operations"""
                
                return self.create_success_response(test_summary)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to generate tests from OpenAPI spec: {str(e)}")
    
    async def _handle_generate_workflow_from_spec(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow generation from OpenAPI specification."""
        spec_url = arguments.get("spec_url")
        workflow_name = arguments.get("workflow_name")
        base_url = arguments.get("base_url")
        endpoints = arguments.get("endpoints")
        
        if not spec_url:
            return self.create_error_response("spec_url is required")
        if not workflow_name:
            return self.create_error_response("workflow_name is required")
        
        operation_id = self.log_operation_start("generate_workflow_from_spec", 
                                               spec_url=spec_url, workflow_name=workflow_name)
        
        try:
            result = await self.openapi_service.generate_workflow_from_spec(
                spec_url, workflow_name, base_url, endpoints
            )
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                workflow_config = result.data
                workflow_summary = f"""✅ **Workflow Generated from OpenAPI Specification**

🎯 **Workflow Information:**
• Name: {workflow_config.workflow_name}
• Description: {workflow_config.description}
• Specification: {spec_url}
• Base URL: {base_url or 'Auto-detected from spec'}
• Total Steps: {len(workflow_config.steps)}

📋 **Workflow Steps:**"""
                
                for i, step in enumerate(workflow_config.steps, 1):
                    workflow_summary += f"\n{i}. **{step.name}**"
                    workflow_summary += f" - {step.method} {step.url}"
                    if step.depends_on:
                        workflow_summary += f" (depends on: {', '.join(step.depends_on)})"
                    if step.extract_variables:
                        workflow_summary += f" (extracts: {', '.join(step.extract_variables.keys())})"
                
                workflow_summary += f"""

🔧 **Workflow Configuration:**
• Virtual Users: {workflow_config.virtual_users}
• Duration: {workflow_config.duration}
• Load Pattern: {workflow_config.load_pattern}
• Execution Mode: {workflow_config.execution_mode}
• Stop on Failure: {workflow_config.stop_on_failure}

⚠️ **Ready for Execution:**
• Use 'run_k6_workflow_test' to execute this workflow
• Review step dependencies and variable extractions
• Customize payloads and conditions as needed"""
                
                return self.create_success_response(workflow_summary)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to generate workflow from OpenAPI spec: {str(e)}")
    
    async def _handle_analyze_api_endpoints(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle API endpoint analysis."""
        spec_url = arguments.get("spec_url")
        if not spec_url:
            return self.create_error_response("spec_url is required")
        
        operation_id = self.log_operation_start("analyze_api_endpoints", spec_url=spec_url)
        
        try:
            result = await self.openapi_service.analyze_api_endpoints(spec_url)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                analysis = result.data
                api_info = analysis.get("api_info", {})
                endpoint_summary = analysis.get("endpoint_summary", {})
                endpoints = analysis.get("endpoints", [])
                
                analysis_text = f"""📊 **OpenAPI Endpoint Analysis**

📋 **API Information:**
• Title: {api_info.get('title', 'Unknown')}
• Version: {api_info.get('version', 'Unknown')}
• Description: {api_info.get('description', 'No description')}

📊 **Endpoint Summary:**
• Total Paths: {endpoint_summary.get('total_paths', 0)}
• Total Operations: {endpoint_summary.get('total_operations', 0)}
• Paths with Parameters: {endpoint_summary.get('paths_with_parameters', 0)}
• Authenticated Endpoints: {endpoint_summary.get('authenticated_endpoints', 0)}

🔧 **HTTP Methods Distribution:**"""
                
                methods = endpoint_summary.get("methods", {})
                for method, count in methods.items():
                    analysis_text += f"\n• {method}: {count} operations"
                
                analysis_text += f"\n\n📋 **Endpoint Details:**"
                
                # Group endpoints by method
                method_groups = {}
                for endpoint in endpoints:
                    method = endpoint["method"]
                    if method not in method_groups:
                        method_groups[method] = []
                    method_groups[method].append(endpoint)
                
                for method, method_endpoints in method_groups.items():
                    analysis_text += f"\n\n**{method} Operations ({len(method_endpoints)}):**"
                    
                    for endpoint in method_endpoints[:10]:  # Show first 10 per method
                        analysis_text += f"\n• **{endpoint['path']}**"
                        if endpoint.get('summary'):
                            analysis_text += f" - {endpoint['summary']}"
                        
                        features = []
                        if endpoint.get('has_parameters'):
                            features.append("params")
                        if endpoint.get('has_request_body'):
                            features.append("body")
                        if endpoint.get('requires_auth'):
                            features.append("auth")
                        
                        if features:
                            analysis_text += f" ({', '.join(features)})"
                        
                        response_codes = endpoint.get('response_codes', [])
                        if response_codes:
                            analysis_text += f" → {', '.join(response_codes)}"
                    
                    if len(method_endpoints) > 10:
                        analysis_text += f"\n• ... and {len(method_endpoints) - 10} more {method} operations"
                
                # Add servers information
                servers = analysis.get("servers", [])
                if servers:
                    analysis_text += f"\n\n🌐 **Available Servers:**"
                    for i, server in enumerate(servers, 1):
                        analysis_text += f"\n{i}. {server.get('url', 'Unknown')}"
                        if server.get('description'):
                            analysis_text += f" - {server['description']}"
                
                analysis_text += f"""

💡 **Test Generation Recommendations:**
• Use 'generate_tests_from_openapi' for comprehensive testing
• Consider grouping related endpoints into workflows
• Pay attention to authenticated endpoints for proper setup
• Test parameter variations for parameterized paths"""
                
                return self.create_success_response(analysis_text)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to analyze API endpoints: {str(e)}")
    
    async def _handle_validate_openapi_spec(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle OpenAPI specification validation."""
        spec_url = arguments.get("spec_url")
        if not spec_url:
            return self.create_error_response("spec_url is required")
        
        operation_id = self.log_operation_start("validate_openapi_spec", spec_url=spec_url)
        
        try:
            result = await self.openapi_service.validate_openapi_spec(spec_url)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                validation_errors = result.data
                
                if not validation_errors:
                    validation_text = f"""✅ **OpenAPI Specification Validation Successful**

🎯 **Validation Results:**
• Specification URL: {spec_url}
• Validation Status: PASSED
• No validation errors found

✅ **Specification Quality:**
• Structure is valid
• Required fields are present
• OpenAPI version is supported
• Paths are properly defined

🚀 **Ready for Use:**
• Specification can be safely used for test generation
• All endpoints are properly defined
• Ready for workflow creation"""
                else:
                    validation_text = f"""❌ **OpenAPI Specification Validation Failed**

🎯 **Validation Results:**
• Specification URL: {spec_url}
• Validation Status: FAILED
• Errors Found: {len(validation_errors)}

❌ **Validation Errors:**"""
                    
                    for i, error in enumerate(validation_errors, 1):
                        validation_text += f"\n{i}. {error}"
                    
                    validation_text += f"""

🔧 **Recommended Actions:**
• Fix the validation errors in your OpenAPI specification
• Ensure all required fields are present
• Verify proper structure and syntax
• Re-validate after making corrections"""
                
                return self.create_success_response(validation_text)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to validate OpenAPI specification: {str(e)}")