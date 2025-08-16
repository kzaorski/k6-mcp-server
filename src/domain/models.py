"""
Domain models for K6 MCP Server.

Contains the core data structures and business entities that represent
the fundamental concepts in the K6 testing domain.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator
from .validation import validate_identifier, validate_json_path


class HttpMethod(str, Enum):
    """HTTP methods supported by K6 tests."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class LoadPattern(str, Enum):
    """Load testing patterns."""
    CONSTANT = "constant"
    RAMP_UP = "ramp_up"
    SPIKE = "spike"
    CUSTOM_STAGES = "custom_stages"


class TestStatus(str, Enum):
    """Test execution status."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AuthConfig(BaseModel):
    """Authentication configuration for tests."""
    type: str = Field(..., description="Authentication type: bearer, basic, apikey")
    token: Optional[str] = Field(None, description="Bearer token or API key")
    username: Optional[str] = Field(None, description="Username for basic auth")
    password: Optional[str] = Field(None, description="Password for basic auth")
    header_name: Optional[str] = Field(None, description="Header name for API key auth")
    
    @field_validator('type')
    @classmethod
    def validate_auth_type(cls, v):
        if v not in ['bearer', 'basic', 'apikey']:
            raise ValueError('Auth type must be one of: bearer, basic, apikey')
        return v


class LoadStage(BaseModel):
    """Load testing stage configuration."""
    duration: str = Field(..., description="Stage duration (e.g., '30s', '5m')")
    target: int = Field(..., ge=0, le=10000, description="Target virtual users")
    
    @field_validator('duration')
    @classmethod
    def validate_duration(cls, v):
        import re
        if not re.match(r'^\d+[smh]$', v):
            raise ValueError('Duration must be in format: number + s/m/h (e.g., "30s", "5m")')
        return v


class ThresholdConfig(BaseModel):
    """Performance threshold configuration."""
    http_req_duration: Optional[str] = Field(None, description="Request duration threshold")
    http_req_failed: Optional[str] = Field(None, description="Failed requests threshold")
    http_reqs: Optional[str] = Field(None, description="Request rate threshold")
    vus: Optional[str] = Field(None, description="Virtual users threshold")
    vus_max: Optional[str] = Field(None, description="Max virtual users threshold")
    
    def to_k6_format(self) -> Dict[str, str]:
        """Convert to K6 threshold format."""
        thresholds = {}
        for field, value in self.__dict__.items():
            if value is not None:
                thresholds[field] = value
        return thresholds


class DataGenerator(BaseModel):
    """Data generator configuration."""
    type: str = Field(..., description="Generator type: uuid, timestamp, random_int, etc.")
    min_value: Optional[int] = Field(None, description="Minimum value for numeric generators")
    max_value: Optional[int] = Field(None, description="Maximum value for numeric generators")
    format: Optional[str] = Field(None, description="Format string for generated data")


class K6TestConfig(BaseModel):
    """
    Configuration for a K6 performance test.
    
    Represents all the parameters needed to execute a K6 test,
    including load patterns, authentication, and test data.
    """
    
    # Basic test configuration
    url: str = Field(..., description="Target URL for the test")
    method: HttpMethod = Field(default=HttpMethod.GET, description="HTTP method")
    
    # Load configuration
    load_pattern: LoadPattern = Field(default=LoadPattern.CONSTANT, description="Load testing pattern")
    virtual_users: int = Field(default=1, ge=1, le=10000, description="Number of virtual users")
    duration: Optional[str] = Field(None, description="Test duration (e.g., '30s', '5m')")
    iterations: Optional[int] = Field(None, ge=1, description="Number of iterations per VU")
    stages: Optional[List[LoadStage]] = Field(None, description="Custom load stages")
    
    # Request configuration
    headers: Optional[Dict[str, str]] = Field(None, description="HTTP headers")
    payload: Optional[Dict[str, Any]] = Field(None, description="Request payload")
    query_params: Optional[Dict[str, str]] = Field(None, description="URL query parameters")
    cookies: Optional[Dict[str, str]] = Field(None, description="HTTP cookies")
    
    # Authentication
    auth: Optional[AuthConfig] = Field(None, description="Authentication configuration")
    
    # Advanced configuration
    timeout: Optional[str] = Field(default="30s", description="Request timeout")
    retry_attempts: int = Field(default=0, ge=0, le=10, description="Number of retry attempts")
    think_time: float = Field(default=1.0, ge=0, description="Think time between requests")
    
    # Thresholds and validation
    thresholds: Optional[ThresholdConfig] = Field(None, description="Performance thresholds")
    
    # Data generation
    env_variables: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    data_generators: Optional[Dict[str, DataGenerator]] = Field(None, description="Data generators")
    data_file: Optional[str] = Field(None, description="Path to data file")
    payload_template: Optional[str] = Field(None, description="Payload template with variables")
    
    # Logging and debugging
    log_requests: bool = Field(default=False, description="Log detailed request information")
    
    @field_validator('duration')
    @classmethod
    def validate_duration(cls, v):
        if v is not None:
            import re
            if not re.match(r'^\d+[smh]$', v):
                raise ValueError('Duration must be in format: number + s/m/h')
        return v
    
    @field_validator('timeout')
    @classmethod
    def validate_timeout(cls, v):
        if v is not None:
            import re
            if not re.match(r'^\d+[smh]$', v):
                raise ValueError('Timeout must be in format: number + s/m/h')
        return v
    
    @field_validator('stages')
    @classmethod
    def validate_stages_with_pattern(cls, v, info):
        load_pattern = info.data.get('load_pattern')
        if load_pattern == LoadPattern.CUSTOM_STAGES and not v:
            raise ValueError('Stages are required for custom_stages load pattern')
        if load_pattern != LoadPattern.CUSTOM_STAGES and v:
            raise ValueError('Stages can only be used with custom_stages load pattern')
        return v
    
    @field_validator('iterations')
    @classmethod
    def validate_iterations_duration(cls, v, info):
        duration = info.data.get('duration')
        if v is not None and duration is not None:
            raise ValueError('Cannot specify both duration and iterations')
        return v


class TestMetrics(BaseModel):
    """Test execution metrics."""
    http_reqs: Optional[int] = Field(None, description="Total HTTP requests")
    http_req_duration: Optional[Dict[str, float]] = Field(None, description="Request duration statistics")
    http_req_failed: Optional[float] = Field(None, description="Failed request rate")
    iterations: Optional[int] = Field(None, description="Total iterations")
    vus: Optional[int] = Field(None, description="Virtual users")
    vus_max: Optional[int] = Field(None, description="Maximum virtual users")
    data_received: Optional[int] = Field(None, description="Data received in bytes")
    data_sent: Optional[int] = Field(None, description="Data sent in bytes")


class K6TestResult(BaseModel):
    """
    Result of a K6 test execution.
    
    Contains all information about test execution including metrics,
    success/failure status, and any error information.
    """
    
    test_id: str = Field(..., description="Unique test identifier")
    config: Dict[str, Any] = Field(..., description="Test configuration used")
    
    # Execution information
    start_time: datetime = Field(default_factory=datetime.utcnow, description="Test start time")
    end_time: Optional[datetime] = Field(None, description="Test end time")
    duration_seconds: Optional[float] = Field(None, description="Total execution time")
    
    # Results
    success: bool = Field(..., description="Overall test success")
    exit_code: int = Field(default=0, description="K6 process exit code")
    
    # Metrics and data
    metrics: Optional[TestMetrics] = Field(None, description="Test metrics")
    results: Optional[Dict[str, Any]] = Field(None, description="Raw K6 results")
    
    # Output and logs
    stdout: Optional[str] = Field(None, description="Standard output")
    stderr: Optional[str] = Field(None, description="Standard error")
    
    # File paths
    script_path: Optional[str] = Field(None, description="Path to generated K6 script")
    results_file: Optional[str] = Field(None, description="Path to results JSON file")
    html_report: Optional[str] = Field(None, description="Path to HTML report")
    csv_file: Optional[str] = Field(None, description="Path to CSV metrics file")
    
    # Error information
    error_message: Optional[str] = Field(None, description="Error message if test failed")
    error_details: Optional[Dict[str, Any]] = Field(None, description="Detailed error information")
    
    def get_duration(self) -> Optional[float]:
        """Calculate test duration if not already set."""
        if self.duration_seconds is not None:
            return self.duration_seconds
        
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            return delta.total_seconds()
        
        return None
    
    def is_successful(self) -> bool:
        """Check if test was successful based on multiple criteria."""
        if not self.success:
            return False
        
        if self.exit_code != 0:
            return False
        
        # Check if any critical metrics failed thresholds
        if self.metrics and self.metrics.http_req_failed:
            if self.metrics.http_req_failed > 0.1:  # More than 10% failure rate
                return False
        
        return True


class RequestStep(BaseModel):
    """
    A single request step in a workflow.
    """
    
    step_id: str = Field(..., description="Unique step identifier")
    name: str = Field(..., description="Human-readable step name")
    
    # Request configuration
    url: str = Field(..., description="Request URL (may contain template variables)")
    method: HttpMethod = Field(default=HttpMethod.GET, description="HTTP method")
    headers: Optional[Dict[str, str]] = Field(None, description="Request headers")
    payload: Optional[Dict[str, Any]] = Field(None, description="Request payload")
    
    # Response processing
    extract_variables: Optional[Dict[str, str]] = Field(None, description="Variables to extract from response")
    
    # Step control
    depends_on: Optional[List[str]] = Field(None, description="Step IDs this step depends on")
    condition: Optional[str] = Field(None, description="Condition for step execution")
    on_failure: str = Field(default="stop", description="Action on step failure")
    
    # Timing
    timeout: str = Field(default="30s", description="Step timeout")
    think_time: float = Field(default=1.0, description="Think time after step")
    
    @field_validator('step_id')
    @classmethod
    def validate_step_id(cls, v):
        return validate_identifier(v)
    
    @field_validator('on_failure')
    @classmethod
    def validate_on_failure(cls, v):
        if v not in ['stop', 'continue', 'retry']:
            raise ValueError('on_failure must be one of: stop, continue, retry')
        return v


class WorkflowConfig(BaseModel):
    """
    Configuration for a multi-request workflow.
    
    Represents a sequence of HTTP requests with dependencies,
    data extraction, and response chaining.
    """
    
    workflow_name: str = Field(..., description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    
    # Steps
    steps: List[RequestStep] = Field(..., min_items=1, description="Workflow steps")
    
    # Execution configuration
    virtual_users: int = Field(default=1, ge=1, le=10000, description="Number of virtual users")
    duration: Optional[str] = Field(None, description="Test duration")
    iterations: Optional[int] = Field(None, ge=1, description="Number of iterations")
    load_pattern: LoadPattern = Field(default=LoadPattern.CONSTANT, description="Load pattern")
    
    # Workflow control
    execution_mode: str = Field(default="sequential", description="Execution mode")
    stop_on_failure: bool = Field(default=True, description="Stop workflow on step failure")
    share_cookies: bool = Field(default=True, description="Share cookies between steps")
    
    # Global settings
    global_headers: Optional[Dict[str, str]] = Field(None, description="Headers for all requests")
    thresholds: Optional[ThresholdConfig] = Field(None, description="Performance thresholds")
    
    @field_validator('workflow_name')
    @classmethod
    def validate_workflow_name(cls, v):
        return validate_identifier(v)
    
    @field_validator('execution_mode')
    @classmethod
    def validate_execution_mode(cls, v):
        if v not in ['sequential', 'parallel']:
            raise ValueError('Execution mode must be sequential or parallel')
        return v
    
    def validate_dependency_cycles(self) -> List[str]:
        """Validate that there are no circular dependencies."""
        errors = []
        step_ids = {step.step_id for step in self.steps}
        
        # Check that all dependencies exist
        for step in self.steps:
            if step.depends_on:
                for dep in step.depends_on:
                    if dep not in step_ids:
                        errors.append(f"Step '{step.step_id}' depends on non-existent step '{dep}'")
        
        # Check for circular dependencies using DFS
        def has_cycle(step_id: str, visited: set, rec_stack: set) -> bool:
            visited.add(step_id)
            rec_stack.add(step_id)
            
            step = next((s for s in self.steps if s.step_id == step_id), None)
            if step and step.depends_on:
                for dep in step.depends_on:
                    if dep not in visited:
                        if has_cycle(dep, visited, rec_stack):
                            return True
                    elif dep in rec_stack:
                        return True
            
            rec_stack.remove(step_id)
            return False
        
        visited = set()
        for step in self.steps:
            if step.step_id not in visited:
                if has_cycle(step.step_id, visited, set()):
                    errors.append(f"Circular dependency detected involving step '{step.step_id}'")
        
        return errors


class StepResult(BaseModel):
    """Result of a single workflow step execution."""
    
    step_id: str = Field(..., description="Step identifier")
    success: bool = Field(..., description="Step success status")
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = Field(None)
    
    # Response data
    status_code: Optional[int] = Field(None, description="HTTP status code")
    response_body: Optional[str] = Field(None, description="Response body")
    response_headers: Optional[Dict[str, str]] = Field(None, description="Response headers")
    
    # Extracted variables
    extracted_variables: Optional[Dict[str, Any]] = Field(None, description="Variables extracted from response")
    
    # Error information
    error_message: Optional[str] = Field(None, description="Error message if step failed")
    
    def get_duration(self) -> Optional[float]:
        """Get step execution duration."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class WorkflowResult(BaseModel):
    """
    Result of a workflow execution.
    
    Contains results for all steps and overall workflow metrics.
    """
    
    workflow_id: str = Field(..., description="Workflow identifier")
    config: Dict[str, Any] = Field(..., description="Workflow configuration")
    
    # Execution information
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = Field(None)
    success: bool = Field(..., description="Overall workflow success")
    
    # Step results
    step_results: List[StepResult] = Field(default_factory=list, description="Results for each step")
    
    # Metrics
    total_requests: int = Field(default=0, description="Total HTTP requests made")
    successful_requests: int = Field(default=0, description="Successful HTTP requests")
    failed_requests: int = Field(default=0, description="Failed HTTP requests")
    
    # Variables context
    global_variables: Optional[Dict[str, Any]] = Field(None, description="Global variables extracted during execution")
    
    # Error information
    error_message: Optional[str] = Field(None, description="Error message if workflow failed")
    
    def get_duration(self) -> Optional[float]:
        """Get total workflow duration."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    def get_success_rate(self) -> float:
        """Get workflow success rate."""
        total = self.total_requests
        if total == 0:
            return 0.0
        return self.successful_requests / total
    
    def get_step_summary(self) -> Dict[str, Any]:
        """Get summary of step execution."""
        successful_steps = sum(1 for step in self.step_results if step.success)
        total_steps = len(self.step_results)
        
        return {
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "failed_steps": total_steps - successful_steps,
            "success_rate": successful_steps / total_steps if total_steps > 0 else 0.0
        }