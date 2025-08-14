"""
Multi-request models for K6 MCP Server.

This module defines data models for multi-request workflow configurations,
enabling complex request sequences with response chaining and variable extraction.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, validator
import re


class RequestStep(BaseModel):
    """
    Configuration for a single step in a multi-request workflow.
    
    Each step represents one HTTP request that can reference data from
    previous steps and extract variables for subsequent steps.
    """
    step_id: str                           # Unikalny identyfikator kroku
    name: str                              # Czytelna nazwa kroku
    url: str                              # URL (może zawierać template variables)
    method: str = "GET"                   # HTTP method
    payload: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None
    auth: Optional[Dict[str, Any]] = None
    cookies: Optional[Dict[str, str]] = None
    query_params: Optional[Dict[str, str]] = None
    
    # Response extraction configuration
    extract_variables: Optional[Dict[str, str]] = None  # {"sessionId": "$.data.sessionId"}
    extract_cookies: bool = True           # Automatyczne przekazywanie cookies
    extract_headers: Optional[List[str]] = None  # ["Authorization", "X-Request-ID"]
    
    # Execution options
    depends_on: Optional[List[str]] = None # Lista step_id, od których zależy ten krok
    condition: Optional[str] = None        # Warunek wykonania: "{{response.step1.status}} == 200"
    on_failure: str = "stop"              # "stop", "continue", "retry"
    retry_attempts: int = 0
    timeout: Optional[str] = "30s"
    think_time: float = 1.0
    
    @validator('method')
    def validate_method(cls, v):
        allowed_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']
        if v.upper() not in allowed_methods:
            raise ValueError(f'Method must be one of {allowed_methods}')
        return v.upper()
    
    @validator('step_id')
    def validate_step_id(cls, v):
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', v):
            raise ValueError('step_id must be a valid identifier (letters, numbers, underscore)')
        return v
    
    @validator('on_failure')
    def validate_on_failure(cls, v):
        allowed_values = ['stop', 'continue', 'retry']
        if v not in allowed_values:
            raise ValueError(f'on_failure must be one of {allowed_values}')
        return v
    
    @validator('extract_variables')
    def validate_extract_variables(cls, v):
        if v is None:
            return v
        
        for key, path in v.items():
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
                raise ValueError(f'Variable name "{key}" must be a valid identifier')
            
            # Validate JSON path format (basic validation)
            if path.startswith('$.') or path.startswith('headers.') or path.startswith('cookies.'):
                continue
            else:
                raise ValueError(f'Extraction path "{path}" must start with $. (JSON path), headers., or cookies.')
        
        return v


class WorkflowResult(BaseModel):
    """Results from executing a multi-request workflow."""
    workflow_name: str
    test_id: str
    timestamp: str
    overall_success: bool
    total_duration: float
    virtual_users: int
    iterations_completed: int
    
    step_results: List[Dict[str, Any]]
    extracted_variables: Dict[str, Any]
    workflow_metrics: Dict[str, Any]
    error_summary: Optional[str] = None


class StepResult(BaseModel):
    """Result from executing a single request step."""
    step_id: str
    step_name: str
    success: bool
    status_code: int
    duration: float
    error_message: Optional[str] = None
    
    # Response data (limited for security)
    response_size: int
    response_headers: Dict[str, str]
    
    # Extracted data
    extracted_variables: Dict[str, Any] = {}
    extracted_cookies: Dict[str, str] = {}
    extracted_headers: Dict[str, str] = {}
    
    # Dependencies
    dependencies_met: bool = True
    condition_result: Optional[bool] = None


class K6MultiRequestConfig(BaseModel):
    """
    Configuration for a multi-request K6 workflow test.
    
    Defines a sequence of HTTP requests with response chaining capabilities,
    allowing data from one request to be used in subsequent requests.
    """
    workflow_name: str
    description: Optional[str] = None
    
    # Global settings
    virtual_users: int = 1
    iterations: Optional[int] = None
    duration: Optional[str] = None
    
    # Request sequence
    steps: List[RequestStep]
    
    # Global configuration
    global_headers: Optional[Dict[str, str]] = None
    global_auth: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = None
    
    # Execution options
    execution_mode: str = "sequential"     # "sequential", "parallel", "mixed"
    stop_on_failure: bool = True
    share_cookies: bool = True            # Automatyczne przekazywanie cookies między krokami
    
    # Reporting
    detailed_per_step_metrics: bool = True
    log_requests: bool = False
    
    # Load testing patterns
    load_pattern: str = "constant"        # "constant", "ramp_up", "spike"
    thresholds: Optional[Dict[str, str]] = None
    
    @validator('workflow_name')
    def validate_workflow_name(cls, v):
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', v):
            raise ValueError('workflow_name must start with letter and contain only letters, numbers, underscore, hyphen')
        return v
    
    @validator('virtual_users')
    def validate_virtual_users(cls, v):
        if v < 1 or v > 10000:
            raise ValueError('virtual_users must be between 1 and 10000')
        return v
    
    @validator('execution_mode')
    def validate_execution_mode(cls, v):
        allowed_modes = ['sequential', 'parallel', 'mixed']
        if v not in allowed_modes:
            raise ValueError(f'execution_mode must be one of {allowed_modes}')
        return v
    
    @validator('load_pattern')
    def validate_load_pattern(cls, v):
        allowed_patterns = ['constant', 'ramp_up', 'spike']
        if v not in allowed_patterns:
            raise ValueError(f'load_pattern must be one of {allowed_patterns}')
        return v
    
    @validator('steps')
    def validate_steps(cls, v):
        if not v:
            raise ValueError('At least one step is required')
        
        if len(v) > 50:
            raise ValueError('Maximum 50 steps allowed per workflow')
        
        # Check for duplicate step IDs
        step_ids = [step.step_id for step in v]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError('All step_id values must be unique')
        
        # Validate dependencies exist
        for step in v:
            if step.depends_on:
                for dependency in step.depends_on:
                    if dependency not in step_ids:
                        raise ValueError(f'Step "{step.step_id}" depends on non-existent step "{dependency}"')
        
        return v
    
    def validate_dependency_cycles(self) -> List[str]:
        """
        Validate that there are no circular dependencies in the workflow.
        Returns list of validation errors.
        """
        errors = []
        
        def has_cycle(step_id: str, visited: set, rec_stack: set) -> bool:
            visited.add(step_id)
            rec_stack.add(step_id)
            
            # Find the step
            step = next((s for s in self.steps if s.step_id == step_id), None)
            if not step or not step.depends_on:
                rec_stack.remove(step_id)
                return False
            
            for dependency in step.depends_on:
                if dependency in rec_stack:
                    return True
                elif dependency not in visited:
                    if has_cycle(dependency, visited, rec_stack):
                        return True
            
            rec_stack.remove(step_id)
            return False
        
        visited = set()
        for step in self.steps:
            if step.step_id not in visited:
                if has_cycle(step.step_id, visited, set()):
                    errors.append(f'Circular dependency detected involving step "{step.step_id}"')
        
        return errors
    
    def get_execution_order(self) -> List[List[str]]:
        """
        Get the execution order of steps, grouped by dependency level.
        Returns list of lists, where each inner list contains step IDs that can be executed in parallel.
        """
        step_map = {step.step_id: step for step in self.steps}
        resolved = set()
        execution_levels = []
        
        while len(resolved) < len(self.steps):
            current_level = []
            
            for step in self.steps:
                if step.step_id in resolved:
                    continue
                
                # Check if all dependencies are resolved
                if not step.depends_on or all(dep in resolved for dep in step.depends_on):
                    current_level.append(step.step_id)
            
            if not current_level:
                # This shouldn't happen if dependency validation passed
                raise ValueError("Cannot resolve step dependencies - possible circular reference")
            
            execution_levels.append(current_level)
            resolved.update(current_level)
        
        return execution_levels


class WorkflowTemplate(BaseModel):
    """
    Template for common workflow patterns.
    Can be used to quickly create standard workflows like auth flows, CRUD operations, etc.
    """
    template_name: str
    description: str
    category: str  # "auth", "crud", "ecommerce", "custom"
    
    # Template configuration with placeholders
    base_config: K6MultiRequestConfig
    
    # Configuration parameters that can be customized
    parameters: Dict[str, Dict[str, Any]]  # {"base_url": {"type": "string", "required": True}}
    
    @validator('category')
    def validate_category(cls, v):
        allowed_categories = ['auth', 'crud', 'ecommerce', 'api_testing', 'load_testing', 'custom']
        if v not in allowed_categories:
            raise ValueError(f'category must be one of {allowed_categories}')
        return v


# Predefined workflow templates
WORKFLOW_TEMPLATES = {
    "oauth_login_flow": WorkflowTemplate(
        template_name="OAuth Login Flow",
        description="Standard OAuth login with token extraction and protected resource access",
        category="auth",
        base_config=K6MultiRequestConfig(
            workflow_name="oauth_login_flow",
            description="OAuth authentication flow with token extraction",
            virtual_users=1,
            iterations=1,
            steps=[
                RequestStep(
                    step_id="login",
                    name="OAuth Login",
                    url="{{base_url}}/auth/login",
                    method="POST",
                    payload={
                        "email": "{{user_email}}",
                        "password": "{{user_password}}"
                    },
                    extract_variables={
                        "access_token": "$.access_token",
                        "refresh_token": "$.refresh_token",
                        "user_id": "$.user.id"
                    }
                ),
                RequestStep(
                    step_id="get_profile",
                    name="Get User Profile",
                    url="{{base_url}}/users/{{user_id}}",
                    method="GET",
                    headers={
                        "Authorization": "Bearer {{access_token}}"
                    },
                    depends_on=["login"],
                    condition="{{response.login.status}} == 200"
                )
            ]
        ),
        parameters={
            "base_url": {"type": "string", "required": True, "description": "Base API URL"},
            "user_email": {"type": "string", "required": True, "description": "Test user email"},
            "user_password": {"type": "string", "required": True, "description": "Test user password"}
        }
    ),
    
    "crud_operations": WorkflowTemplate(
        template_name="CRUD Operations",
        description="Complete Create, Read, Update, Delete operation sequence",
        category="crud",
        base_config=K6MultiRequestConfig(
            workflow_name="crud_operations",
            description="Full CRUD operations test",
            virtual_users=1,
            iterations=1,
            steps=[
                RequestStep(
                    step_id="create",
                    name="Create Resource",
                    url="{{base_url}}/{{resource_path}}",
                    method="POST",
                    payload={
                        "name": "Test Resource {{timestamp}}",
                        "description": "Created by K6 test"
                    },
                    extract_variables={
                        "resource_id": "$.id",
                        "resource_name": "$.name"
                    }
                ),
                RequestStep(
                    step_id="read",
                    name="Read Created Resource",
                    url="{{base_url}}/{{resource_path}}/{{resource_id}}",
                    method="GET",
                    depends_on=["create"]
                ),
                RequestStep(
                    step_id="update",
                    name="Update Resource",
                    url="{{base_url}}/{{resource_path}}/{{resource_id}}",
                    method="PUT",
                    payload={
                        "name": "{{resource_name}} - Updated",
                        "description": "Updated by K6 test"
                    },
                    depends_on=["read"]
                ),
                RequestStep(
                    step_id="delete",
                    name="Delete Resource",
                    url="{{base_url}}/{{resource_path}}/{{resource_id}}",
                    method="DELETE",
                    depends_on=["update"]
                )
            ]
        ),
        parameters={
            "base_url": {"type": "string", "required": True, "description": "Base API URL"},
            "resource_path": {"type": "string", "required": True, "description": "Resource endpoint path"}
        }
    )
}


def get_workflow_template(template_name: str) -> Optional[WorkflowTemplate]:
    """Get a predefined workflow template by name."""
    return WORKFLOW_TEMPLATES.get(template_name)


def list_workflow_templates() -> List[str]:
    """Get list of available workflow template names."""
    return list(WORKFLOW_TEMPLATES.keys())


def create_workflow_from_template(
    template_name: str, 
    parameters: Dict[str, Any]
) -> K6MultiRequestConfig:
    """
    Create a workflow configuration from a template with provided parameters.
    
    Args:
        template_name: Name of the template to use
        parameters: Parameter values to substitute in the template
        
    Returns:
        Configured K6MultiRequestConfig instance
        
    Raises:
        ValueError: If template not found or required parameters missing
    """
    template = get_workflow_template(template_name)
    if not template:
        raise ValueError(f"Template '{template_name}' not found")
    
    # Validate required parameters
    for param_name, param_config in template.parameters.items():
        if param_config.get("required", False) and param_name not in parameters:
            raise ValueError(f"Required parameter '{param_name}' not provided")
    
    # Create a copy of the base config
    config_dict = template.base_config.dict()
    
    # TODO: Implement template parameter substitution
    # This would involve recursively walking the config and replacing template variables
    # For now, return the base config (implementation would be added in template_engine.py)
    
    return K6MultiRequestConfig(**config_dict)