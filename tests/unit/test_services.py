"""
Unit tests for service layer.

Tests business logic, error handling, and service interactions.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from core.config import AppConfig
from core.base import OperationResult
from services.k6_service import K6TestService
from services.workflow_service import WorkflowService
from services.result_service import ResultService
from services.openapi_service import OpenAPIService
from domain.models import (
    K6TestConfig, WorkflowConfig, RequestStep, K6TestResult,
    HttpMethod, LoadPattern, TestMetrics
)


class TestK6Service:
    """Test cases for K6TestService."""
    
    @pytest.fixture
    async def k6_service(self):
        """Create K6TestService for testing."""
        config = Mock(spec=AppConfig)
        config.reports_dir = Mock()
        config.reports_dir.mkdir = Mock()
        config.csv_data_dir = Mock()
        config.csv_data_dir.mkdir = Mock()
        config.k6 = Mock()
        config.k6.max_virtual_users = 1000
        config.k6.default_timeout = "30s"
        config.k6.enable_html_reports = True
        config.k6.k6_binary_path = "k6"
        
        test_repo = AsyncMock()
        result_repo = AsyncMock()
        
        service = K6TestService(config, test_repo, result_repo)
        await service._initialize_impl()
        return service
    
    @pytest.mark.asyncio
    async def test_prepare_test_success(self, k6_service):
        """Test successful test preparation."""
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
            virtual_users=10,
            duration="30s"
        )
        
        # Mock repository response
        k6_service.test_repository.create_test.return_value = OperationResult.success_result("saved")
        
        with patch.object(k6_service, '_generate_test_script') as mock_script:
            mock_script.return_value = OperationResult.success_result("/path/to/script.js")
            
            result = await k6_service.prepare_test(config)
            
            assert result.success is True
            assert "Test Prepared Successfully" in result.data
            assert result.metadata["script_path"] == "/path/to/script.js"
    
    @pytest.mark.asyncio
    async def test_prepare_test_invalid_config(self, k6_service):
        """Test test preparation with invalid configuration."""
        config = K6TestConfig(
            url="invalid-url",  # Invalid URL
            method=HttpMethod.GET,
            virtual_users=10,
            duration="30s"
        )
        
        result = await k6_service.prepare_test(config)
        
        assert result.success is False
        assert "URL must start with http" in result.error_message
    
    @pytest.mark.asyncio
    async def test_confirm_test_success(self, k6_service):
        """Test successful test confirmation."""
        test_id = "test_123"
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
            virtual_users=1,
            duration="10s"
        )
        
        # Add test to pending
        k6_service.pending_tests[test_id] = config
        
        result = await k6_service.confirm_test(test_id, "y")
        
        assert result.success is True
        assert "confirmed and ready for execution" in result.data
        assert test_id in k6_service.confirmed_tests
        assert test_id not in k6_service.pending_tests
    
    @pytest.mark.asyncio
    async def test_confirm_test_cancel(self, k6_service):
        """Test test cancellation."""
        test_id = "test_123"
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
            virtual_users=1,
            duration="10s"
        )
        
        # Add test to pending
        k6_service.pending_tests[test_id] = config
        
        result = await k6_service.confirm_test(test_id, "n")
        
        assert result.success is True
        assert "cancelled" in result.data
        assert test_id not in k6_service.pending_tests
        assert test_id not in k6_service.confirmed_tests
    
    @pytest.mark.asyncio
    async def test_execute_confirmed_test(self, k6_service):
        """Test executing a confirmed test."""
        test_id = "test_123"
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
            virtual_users=1,
            iterations=1
        )
        
        # Add test to confirmed
        k6_service.confirmed_tests[test_id] = config
        
        # Mock internal execution
        expected_result = K6TestResult(
            test_id=test_id,
            config=config.model_dump(),
            success=True,
            start_time=datetime.utcnow()
        )
        
        with patch.object(k6_service, '_execute_test_internal') as mock_execute:
            mock_execute.return_value = OperationResult.success_result(expected_result)
            
            result = await k6_service.execute_confirmed_test(test_id)
            
            assert result.success is True
            assert result.data.test_id == test_id
            assert test_id not in k6_service.confirmed_tests


class TestWorkflowService:
    """Test cases for WorkflowService."""
    
    @pytest.fixture
    async def workflow_service(self):
        """Create WorkflowService for testing."""
        config = Mock(spec=AppConfig)
        workflow_repo = AsyncMock()
        
        service = WorkflowService(config, workflow_repo)
        await service._initialize_impl()
        return service
    
    @pytest.mark.asyncio
    async def test_validate_workflow_success(self, workflow_service):
        """Test successful workflow validation."""
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
                payload={"name": "test"},
                depends_on=["step1"]
            )
        ]
        
        config = WorkflowConfig(
            workflow_name="test_workflow",
            steps=steps,
            virtual_users=1,
            duration="30s"
        )
        
        result = await workflow_service.validate_workflow(config)
        
        assert result.success is True
        assert len(result.data) == 0  # No validation errors
    
    @pytest.mark.asyncio
    async def test_validate_workflow_circular_dependency(self, workflow_service):
        """Test workflow validation with circular dependency."""
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
        
        config = WorkflowConfig(
            workflow_name="circular_workflow",
            steps=steps,
            virtual_users=1,
            duration="30s"
        )
        
        result = await workflow_service.validate_workflow(config)
        
        assert result.success is True
        assert len(result.data) > 0  # Should have validation errors
        assert any("Circular dependency" in error for error in result.data)
    
    @pytest.mark.asyncio
    async def test_create_workflow_success(self, workflow_service):
        """Test successful workflow creation."""
        steps = [
            RequestStep(
                step_id="step1",
                name="Test step",
                url="https://api.example.com/test",
                method=HttpMethod.GET
            )
        ]
        
        config = WorkflowConfig(
            workflow_name="test_workflow",
            steps=steps,
            virtual_users=1,
            duration="30s"
        )
        
        # Mock repository response
        workflow_service.workflow_repository.create_with_id.return_value = OperationResult.success_result("created")
        
        result = await workflow_service.create_workflow(config)
        
        assert result.success is True
        assert result.data.startswith("workflow_")


class TestResultService:
    """Test cases for ResultService."""
    
    @pytest.fixture
    async def result_service(self):
        """Create ResultService for testing."""
        config = Mock(spec=AppConfig)
        config.reports_dir = Mock()
        config.reports_dir.mkdir = Mock()
        config.reports_dir.rglob = Mock(return_value=[])
        config.reports_dir.exists.return_value = True
        config.reports_dir.is_dir.return_value = True
        
        result_repo = AsyncMock()
        
        service = ResultService(config, result_repo)
        await service._initialize_impl()
        return service
    
    @pytest.mark.asyncio
    async def test_get_test_results_success(self, result_service):
        """Test successful test result retrieval."""
        test_id = "test_123"
        
        # Mock test result
        test_result = K6TestResult(
            test_id=test_id,
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
        
        result_service.result_repository.get_result.return_value = test_result
        
        with patch.object(result_service, '_get_result_file_paths') as mock_files:
            mock_files.return_value = {"html_report": "/path/to/report.html"}
            
            result = await result_service.get_test_results(test_id)
            
            assert result.success is True
            assert result.data["test_id"] == test_id
            assert result.data["success"] is True
            assert "files" in result.data
    
    @pytest.mark.asyncio
    async def test_get_test_results_not_found(self, result_service):
        """Test test result retrieval when result not found."""
        test_id = "nonexistent_test"
        
        result_service.result_repository.get_result.return_value = None
        
        result = await result_service.get_test_results(test_id)
        
        assert result.success is False
        assert "not found" in result.error_message
    
    @pytest.mark.asyncio
    async def test_generate_summary_report(self, result_service):
        """Test summary report generation."""
        test_ids = ["test_1", "test_2", "test_3"]
        
        # Mock test results
        test_results = []
        for i, test_id in enumerate(test_ids):
            result = K6TestResult(
                test_id=test_id,
                config={"url": f"https://api.example.com/test{i}"},
                success=i < 2,  # First two are successful
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow() + timedelta(seconds=30),
                metrics=TestMetrics(
                    http_reqs=100,
                    http_req_failed=0.01 if i < 2 else 0.1,
                    http_req_duration={"avg": 150.0},
                    vus=10
                )
            )
            test_results.append(result)
        
        def mock_get_result(test_id):
            for result in test_results:
                if result.test_id == test_id:
                    return result
            return None
        
        result_service.result_repository.get_result.side_effect = mock_get_result
        
        result = await result_service.generate_summary_report(test_ids)
        
        assert result.success is True
        summary = result.data
        assert summary["total_tests"] == 3
        assert summary["successful_tests"] == 2
        assert summary["failed_tests"] == 1
        assert summary["success_rate"] == 2/3


class TestOpenAPIService:
    """Test cases for OpenAPIService."""
    
    @pytest.fixture
    async def openapi_service(self):
        """Create OpenAPIService for testing."""
        config = Mock(spec=AppConfig)
        
        service = OpenAPIService(config)
        await service._initialize_impl()
        return service
    
    @pytest.mark.asyncio
    async def test_load_openapi_spec_success(self, openapi_service):
        """Test successful OpenAPI spec loading."""
        spec_url = "https://api.example.com/openapi.json"
        
        result = await openapi_service.load_openapi_spec(spec_url)
        
        assert result.success is True
        assert "openapi" in result.data
        assert "info" in result.data
        assert "paths" in result.data
    
    @pytest.mark.asyncio
    async def test_validate_openapi_spec_valid(self, openapi_service):
        """Test OpenAPI spec validation with valid spec."""
        spec_url = "https://api.example.com/openapi.json"
        
        result = await openapi_service.validate_openapi_spec(spec_url)
        
        assert result.success is True
        assert len(result.data) == 0  # No validation errors
    
    @pytest.mark.asyncio
    async def test_generate_tests_from_spec(self, openapi_service):
        """Test test generation from OpenAPI spec."""
        spec_url = "https://api.example.com/openapi.json"
        base_url = "https://api.example.com/v1"
        
        result = await openapi_service.generate_tests_from_spec(spec_url, base_url)
        
        assert result.success is True
        test_configs = result.data
        assert len(test_configs) > 0
        
        # Check first test config
        first_test = test_configs[0]
        assert isinstance(first_test, K6TestConfig)
        assert first_test.url.startswith(base_url)
    
    @pytest.mark.asyncio
    async def test_generate_workflow_from_spec(self, openapi_service):
        """Test workflow generation from OpenAPI spec."""
        spec_url = "https://api.example.com/openapi.json"
        workflow_name = "api_workflow"
        base_url = "https://api.example.com/v1"
        
        result = await openapi_service.generate_workflow_from_spec(
            spec_url, workflow_name, base_url
        )
        
        assert result.success is True
        workflow_config = result.data
        assert isinstance(workflow_config, WorkflowConfig)
        assert workflow_config.workflow_name == workflow_name
        assert len(workflow_config.steps) > 0
    
    @pytest.mark.asyncio
    async def test_analyze_api_endpoints(self, openapi_service):
        """Test API endpoint analysis."""
        spec_url = "https://api.example.com/openapi.json"
        
        result = await openapi_service.analyze_api_endpoints(spec_url)
        
        assert result.success is True
        analysis = result.data
        assert "api_info" in analysis
        assert "endpoint_summary" in analysis
        assert "endpoints" in analysis
        
        summary = analysis["endpoint_summary"]
        assert "total_paths" in summary
        assert "total_operations" in summary
        assert "methods" in summary


# Integration test helpers
class TestServiceIntegration:
    """Integration tests between services."""
    
    @pytest.mark.asyncio
    async def test_k6_to_result_service_flow(self):
        """Test flow from K6 service to result service."""
        # This would test the complete flow from test execution
        # to result storage and retrieval
        pass
    
    @pytest.mark.asyncio
    async def test_openapi_to_k6_service_flow(self):
        """Test flow from OpenAPI service to K6 test execution."""
        # This would test generating tests from OpenAPI specs
        # and executing them through K6 service
        pass


# Mock fixtures for common objects
@pytest.fixture
def mock_app_config():
    """Mock application configuration."""
    config = Mock(spec=AppConfig)
    config.reports_dir = Mock()
    config.csv_data_dir = Mock()
    config.k6 = Mock()
    config.k6.max_virtual_users = 1000
    config.k6.default_timeout = "30s"
    config.k6.enable_html_reports = True
    config.k6.k6_binary_path = "k6"
    config.k6.results_retention_days = 30
    return config


@pytest.fixture
def mock_test_repository():
    """Mock test repository."""
    repo = AsyncMock()
    repo.create_test.return_value = OperationResult.success_result("saved")
    repo.get_test.return_value = None
    return repo


@pytest.fixture
def mock_result_repository():
    """Mock result repository."""
    repo = AsyncMock()
    repo.save_result.return_value = OperationResult.success_result("saved")
    repo.get_result.return_value = None
    repo.list_recent_results.return_value = []
    repo.cleanup_old_results.return_value = 0
    return repo


@pytest.fixture
def mock_workflow_repository():
    """Mock workflow repository."""
    repo = AsyncMock()
    repo.create_with_id.return_value = OperationResult.success_result("created")
    repo.get_by_id.return_value = None
    return repo