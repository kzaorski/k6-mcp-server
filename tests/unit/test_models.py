"""
Unit tests for domain models.

Tests validation, serialization, and business logic of domain models.
"""

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any

from domain.models import (
    K6TestConfig, K6TestResult, WorkflowConfig, WorkflowResult,
    RequestStep, StepResult, TestMetrics, LoadPattern, HttpMethod
)


class TestK6TestConfig:
    """Test cases for K6TestConfig model."""
    
    def test_valid_config_creation(self):
        """Test creating a valid K6 test configuration."""
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
            virtual_users=10,
            duration="30s"
        )
        
        assert config.url == "https://api.example.com/test"
        assert config.method == HttpMethod.GET
        assert config.virtual_users == 10
        assert config.duration == "30s"
        assert config.load_pattern == LoadPattern.CONSTANT  # Default
    
    def test_config_with_iterations(self):
        """Test config with iterations instead of duration."""
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.POST,
            virtual_users=5,
            iterations=100
        )
        
        assert config.iterations == 100
        assert config.duration is None
    
    def test_config_validation_invalid_url(self):
        """Test config validation with invalid URL."""
        with pytest.raises(ValueError, match="URL must start with http"):
            K6TestConfig(
                url="invalid-url",
                method=HttpMethod.GET,
                virtual_users=1,
                duration="10s"
            )
    
    def test_config_validation_invalid_virtual_users(self):
        """Test config validation with invalid virtual users."""
        with pytest.raises(ValueError, match="Virtual users must be at least 1"):
            K6TestConfig(
                url="https://api.example.com/test",
                method=HttpMethod.GET,
                virtual_users=0,
                duration="10s"
            )
    
    def test_config_with_headers_and_payload(self):
        """Test config with headers and payload."""
        headers = {"Authorization": "Bearer token", "Content-Type": "application/json"}
        payload = {"name": "test", "email": "test@example.com"}
        
        config = K6TestConfig(
            url="https://api.example.com/users",
            method=HttpMethod.POST,
            virtual_users=1,
            duration="10s",
            headers=headers,
            payload=payload
        )
        
        assert config.headers == headers
        assert config.payload == payload


class TestK6TestResult:
    """Test cases for K6TestResult model."""
    
    def test_result_creation(self):
        """Test creating a test result."""
        config = {
            "url": "https://api.example.com/test",
            "method": "GET",
            "virtual_users": 1
        }
        
        result = K6TestResult(
            test_id="test_123",
            config=config,
            success=True,
            start_time=datetime.utcnow(),
            stdout="Test completed successfully"
        )
        
        assert result.test_id == "test_123"
        assert result.config == config
        assert result.success is True
        assert result.stdout == "Test completed successfully"
    
    def test_result_duration_calculation(self):
        """Test duration calculation."""
        start = datetime.utcnow()
        end = start + timedelta(seconds=30)
        
        result = K6TestResult(
            test_id="test_123",
            config={},
            success=True,
            start_time=start,
            end_time=end
        )
        
        duration = result.get_duration()
        assert duration == 30.0
    
    def test_result_duration_no_end_time(self):
        """Test duration when end_time is None."""
        result = K6TestResult(
            test_id="test_123",
            config={},
            success=True,
            start_time=datetime.utcnow()
        )
        
        duration = result.get_duration()
        assert duration is None


class TestWorkflowConfig:
    """Test cases for WorkflowConfig model."""
    
    def test_workflow_creation(self):
        """Test creating a workflow configuration."""
        steps = [
            RequestStep(
                step_id="step1",
                name="Get users",
                url="https://api.example.com/users",
                method=HttpMethod.GET
            ),
            RequestStep(
                step_id="step2",
                name="Create user",
                url="https://api.example.com/users",
                method=HttpMethod.POST,
                payload={"name": "test", "email": "test@example.com"},
                depends_on=["step1"]
            )
        ]
        
        workflow = WorkflowConfig(
            workflow_name="user_workflow",
            description="Test user operations",
            steps=steps,
            virtual_users=5,
            duration="60s"
        )
        
        assert workflow.workflow_name == "user_workflow"
        assert len(workflow.steps) == 2
        assert workflow.virtual_users == 5
        assert workflow.duration == "60s"
    
    def test_workflow_validation_circular_dependency(self):
        """Test workflow validation with circular dependencies."""
        steps = [
            RequestStep(
                step_id="step1",
                name="Step 1",
                url="https://api.example.com/step1",
                method=HttpMethod.GET,
                depends_on=["step2"]
            ),
            RequestStep(
                step_id="step2",
                name="Step 2", 
                url="https://api.example.com/step2",
                method=HttpMethod.GET,
                depends_on=["step1"]
            )
        ]
        
        workflow = WorkflowConfig(
            workflow_name="circular_workflow",
            steps=steps,
            virtual_users=1,
            duration="10s"
        )
        
        errors = workflow.validate_dependency_cycles()
        assert len(errors) > 0
        assert "Circular dependency detected" in errors[0]
    
    def test_workflow_validation_valid_dependencies(self):
        """Test workflow validation with valid dependencies."""
        steps = [
            RequestStep(
                step_id="step1",
                name="Step 1",
                url="https://api.example.com/step1",
                method=HttpMethod.GET
            ),
            RequestStep(
                step_id="step2",
                name="Step 2",
                url="https://api.example.com/step2", 
                method=HttpMethod.GET,
                depends_on=["step1"]
            ),
            RequestStep(
                step_id="step3",
                name="Step 3",
                url="https://api.example.com/step3",
                method=HttpMethod.GET,
                depends_on=["step1", "step2"]
            )
        ]
        
        workflow = WorkflowConfig(
            workflow_name="valid_workflow",
            steps=steps,
            virtual_users=1,
            duration="10s"
        )
        
        errors = workflow.validate_dependency_cycles()
        assert len(errors) == 0


class TestRequestStep:
    """Test cases for RequestStep model."""
    
    def test_step_creation(self):
        """Test creating a request step."""
        step = RequestStep(
            step_id="test_step",
            name="Test API Call",
            url="https://api.example.com/test",
            method=HttpMethod.POST,
            headers={"Content-Type": "application/json"},
            payload={"test": "data"}
        )
        
        assert step.step_id == "test_step"
        assert step.name == "Test API Call"
        assert step.url == "https://api.example.com/test"
        assert step.method == HttpMethod.POST
        assert step.headers["Content-Type"] == "application/json"
        assert step.payload["test"] == "data"
    
    def test_step_with_variable_extraction(self):
        """Test step with variable extraction configuration."""
        extract_vars = {
            "user_id": "$.id",
            "access_token": "$.token"
        }
        
        step = RequestStep(
            step_id="login_step",
            name="User Login",
            url="https://api.example.com/login",
            method=HttpMethod.POST,
            extract_variables=extract_vars
        )
        
        assert step.extract_variables == extract_vars
    
    def test_step_validation_invalid_url(self):
        """Test step validation with invalid URL."""
        with pytest.raises(ValueError, match="URL must start with http"):
            RequestStep(
                step_id="invalid_step",
                name="Invalid Step",
                url="invalid-url",
                method=HttpMethod.GET
            )


class TestStepResult:
    """Test cases for StepResult model."""
    
    def test_step_result_creation(self):
        """Test creating a step result."""
        start = datetime.utcnow()
        end = start + timedelta(seconds=5)
        
        result = StepResult(
            step_id="test_step",
            success=True,
            start_time=start,
            end_time=end,
            status_code=200,
            response_body='{"status": "success"}',
            extracted_variables={"user_id": "123"}
        )
        
        assert result.step_id == "test_step"
        assert result.success is True
        assert result.status_code == 200
        assert result.extracted_variables["user_id"] == "123"
    
    def test_step_result_duration(self):
        """Test step result duration calculation."""
        start = datetime.utcnow()
        end = start + timedelta(seconds=2.5)
        
        result = StepResult(
            step_id="test_step",
            success=True,
            start_time=start,
            end_time=end
        )
        
        duration = result.get_duration()
        assert duration == 2.5


class TestWorkflowResult:
    """Test cases for WorkflowResult model."""
    
    def test_workflow_result_creation(self):
        """Test creating a workflow result."""
        step_results = [
            StepResult(
                step_id="step1",
                success=True,
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow() + timedelta(seconds=1)
            ),
            StepResult(
                step_id="step2", 
                success=True,
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow() + timedelta(seconds=2)
            )
        ]
        
        result = WorkflowResult(
            workflow_id="workflow_123",
            config={"workflow_name": "test_workflow"},
            success=True,
            start_time=datetime.utcnow(),
            step_results=step_results,
            total_requests=2,
            successful_requests=2,
            failed_requests=0
        )
        
        assert result.workflow_id == "workflow_123"
        assert result.success is True
        assert len(result.step_results) == 2
        assert result.total_requests == 2
    
    def test_workflow_result_metrics(self):
        """Test workflow result metrics calculation."""
        step_results = [
            StepResult(step_id="step1", success=True, start_time=datetime.utcnow()),
            StepResult(step_id="step2", success=False, start_time=datetime.utcnow()),
            StepResult(step_id="step3", success=True, start_time=datetime.utcnow())
        ]
        
        result = WorkflowResult(
            workflow_id="workflow_123",
            config={},
            success=False,
            start_time=datetime.utcnow(),
            step_results=step_results,
            total_requests=3,
            successful_requests=2,
            failed_requests=1
        )
        
        success_rate = result.get_success_rate()
        assert success_rate == 2/3
        
        step_summary = result.get_step_summary()
        assert step_summary["total"] == 3
        assert step_summary["successful"] == 2
        assert step_summary["failed"] == 1


class TestTestMetrics:
    """Test cases for TestMetrics model."""
    
    def test_metrics_creation(self):
        """Test creating test metrics."""
        metrics = TestMetrics(
            http_reqs=1000,
            http_req_failed=0.02,  # 2% failure rate
            http_req_duration={
                "avg": 150.5,
                "p(95)": 250.0
            },
            vus=10,
            data_received=1048576,  # 1 MB
            data_sent=524288  # 512 KB
        )
        
        assert metrics.http_reqs == 1000
        assert metrics.http_req_failed == 0.02
        assert metrics.http_req_duration["avg"] == 150.5
        assert metrics.vus == 10
        assert metrics.data_received == 1048576
    
    def test_metrics_serialization(self):
        """Test metrics model serialization."""
        metrics = TestMetrics(
            http_reqs=500,
            http_req_failed=0.01,
            http_req_duration={"avg": 100.0, "p(95)": 200.0},
            vus=5
        )
        
        data = metrics.model_dump()
        assert data["http_reqs"] == 500
        assert data["http_req_failed"] == 0.01
        assert data["http_req_duration"]["avg"] == 100.0
        assert data["vus"] == 5


class TestEnumValues:
    """Test cases for enum values."""
    
    def test_http_method_enum(self):
        """Test HttpMethod enum values."""
        assert HttpMethod.GET.value == "GET"
        assert HttpMethod.POST.value == "POST"
        assert HttpMethod.PUT.value == "PUT"
        assert HttpMethod.DELETE.value == "DELETE"
        assert HttpMethod.PATCH.value == "PATCH"
    
    def test_load_pattern_enum(self):
        """Test LoadPattern enum values."""
        assert LoadPattern.CONSTANT.value == "constant_load"
        assert LoadPattern.RAMP_UP.value == "ramp_up"
        assert LoadPattern.SPIKE.value == "spike"
        assert LoadPattern.CUSTOM_STAGES.value == "custom_stages"


# Fixtures for common test data
@pytest.fixture
def sample_k6_config():
    """Sample K6 test configuration for testing."""
    return K6TestConfig(
        url="https://api.example.com/test",
        method=HttpMethod.GET,
        virtual_users=10,
        duration="30s",
        load_pattern=LoadPattern.CONSTANT
    )


@pytest.fixture
def sample_workflow_config():
    """Sample workflow configuration for testing."""
    steps = [
        RequestStep(
            step_id="step1",
            name="List users",
            url="https://api.example.com/users",
            method=HttpMethod.GET
        ),
        RequestStep(
            step_id="step2",
            name="Create user",
            url="https://api.example.com/users", 
            method=HttpMethod.POST,
            payload={"name": "test", "email": "test@example.com"},
            depends_on=["step1"]
        )
    ]
    
    return WorkflowConfig(
        workflow_name="test_workflow",
        description="Test workflow",
        steps=steps,
        virtual_users=5,
        duration="60s"
    )


@pytest.fixture
def sample_test_result():
    """Sample test result for testing."""
    return K6TestResult(
        test_id="test_123",
        config={"url": "https://api.example.com/test"},
        success=True,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() + timedelta(seconds=30),
        metrics=TestMetrics(
            http_reqs=100,
            http_req_failed=0.01,
            http_req_duration={"avg": 150.0},
            vus=10
        )
    )