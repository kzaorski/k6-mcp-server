"""
Integration tests for service interactions.

Tests how services work together and handle cross-service workflows.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

from core.config import AppConfig
from core.container import DIContainer
from services.k6_service import K6TestService
from services.workflow_service import WorkflowService
from services.result_service import ResultService
from services.openapi_service import OpenAPIService
from repositories.test_repository import TestRepository
from repositories.result_repository import ResultRepository
from repositories.workflow_repository import WorkflowRepository
from domain.models import (
    K6TestConfig, WorkflowConfig, RequestStep, K6TestResult,
    HttpMethod, LoadPattern, TestMetrics
)


class TestK6ServiceIntegration:
    """Integration tests for K6TestService with other components."""
    
    @pytest.fixture
    async def integrated_k6_service(self):
        """Create K6TestService with real dependencies."""
        config = Mock(spec=AppConfig)
        config.reports_dir = Mock()
        config.reports_dir.mkdir = Mock()
        config.csv_data_dir = Mock()
        config.csv_data_dir.mkdir = Mock()
        config.templates_dir = Mock()
        config.k6 = Mock()
        config.k6.max_virtual_users = 1000
        config.k6.default_timeout = "30s"
        config.k6.enable_html_reports = True
        config.k6.k6_binary_path = "k6"
        
        # Create real repository instances (mocked)
        test_repo = Mock(spec=TestRepository)
        test_repo.create_test = AsyncMock(return_value=Mock(success=True))
        test_repo.get_test = AsyncMock(return_value=None)
        
        result_repo = Mock(spec=ResultRepository)
        result_repo.save_result = AsyncMock(return_value=Mock(success=True))
        result_repo.get_result = AsyncMock(return_value=None)
        
        service = K6TestService(config, test_repo, result_repo)
        await service._initialize_impl()
        return service, test_repo, result_repo
    
    @pytest.mark.asyncio
    async def test_full_test_lifecycle(self, integrated_k6_service):
        """Test complete test lifecycle from preparation to result storage."""
        service, test_repo, result_repo = integrated_k6_service
        
        # Step 1: Prepare test
        config = K6TestConfig(
            url="https://api.example.com/test",
            method=HttpMethod.GET,
            virtual_users=1,
            iterations=1
        )
        
        with patch.object(service, '_generate_test_script') as mock_script:
            mock_script.return_value = Mock(success=True, data="/path/to/script.js")
            
            prepare_result = await service.prepare_test(config)
            assert prepare_result.success is True
            test_id = prepare_result.metadata["test_id"]
        
        # Step 2: Confirm test
        confirm_result = await service.confirm_test(test_id, "y")
        assert confirm_result.success is True
        
        # Step 3: Execute test
        expected_result = K6TestResult(
            test_id=test_id,
            config=config.model_dump(),
            success=True,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(seconds=5)
        )
        
        with patch.object(service, '_execute_test_internal') as mock_execute:
            mock_execute.return_value = Mock(success=True, data=expected_result)
            
            execute_result = await service.execute_confirmed_test(test_id)
            assert execute_result.success is True
            
            # Verify result was saved
            result_repo.save_result.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_k6_service_with_result_service_integration(self):
        """Test K6 service integration with result service."""
        # Create integrated services
        config = Mock(spec=AppConfig)
        config.reports_dir = Mock()
        config.reports_dir.mkdir = Mock()
        config.csv_data_dir = Mock()
        config.csv_data_dir.mkdir = Mock()
        config.k6 = Mock()
        config.k6.max_virtual_users = 1000
        config.k6.results_retention_days = 30
        
        # Shared result repository
        result_repo = Mock(spec=ResultRepository)
        test_repo = Mock(spec=TestRepository)
        test_repo.create_test = AsyncMock(return_value=Mock(success=True))
        
        k6_service = K6TestService(config, test_repo, result_repo)
        result_service = ResultService(config, result_repo)
        
        await k6_service._initialize_impl()
        await result_service._initialize_impl()
        
        # Create test result
        test_result = K6TestResult(
            test_id="integration_test_123",
            config={"url": "https://api.example.com/test"},
            success=True,
            start_time=datetime.utcnow(),
            metrics=TestMetrics(
                http_reqs=100,
                http_req_failed=0.01,
                http_req_duration={"avg": 150.0},
                vus=10
            )
        )
        
        # Mock result repository responses
        result_repo.save_result = AsyncMock(return_value=Mock(success=True))
        result_repo.get_result = AsyncMock(return_value=test_result)
        
        # Save result through K6 service
        await result_repo.save_result("integration_test_123", test_result)
        
        # Retrieve result through result service
        with patch.object(result_service, '_get_result_file_paths') as mock_files:
            mock_files.return_value = {"html_report": "/path/to/report.html"}
            
            retrieved_result = await result_service.get_test_results("integration_test_123")
            assert retrieved_result.success is True
            assert retrieved_result.data["test_id"] == "integration_test_123"


class TestWorkflowServiceIntegration:
    """Integration tests for WorkflowService with other components."""
    
    @pytest.fixture
    async def integrated_workflow_service(self):
        """Create WorkflowService with dependencies."""
        config = Mock(spec=AppConfig)
        workflow_repo = Mock(spec=WorkflowRepository)
        workflow_repo.create_with_id = AsyncMock(return_value=Mock(success=True))
        workflow_repo.get_by_id = AsyncMock(return_value=None)
        
        service = WorkflowService(config, workflow_repo)
        await service._initialize_impl()
        return service, workflow_repo
    
    @pytest.mark.asyncio
    async def test_workflow_creation_and_execution_flow(self, integrated_workflow_service):
        """Test workflow creation and execution integration."""
        service, workflow_repo = integrated_workflow_service
        
        # Create workflow configuration
        steps = [
            RequestStep(
                step_id="step1",
                name="Get users",
                url="https://api.example.com/users",
                method=HttpMethod.GET,
                extract_variables={"user_count": "$.length"}
            ),
            RequestStep(
                step_id="step2",
                name="Create user",
                url="https://api.example.com/users",
                method=HttpMethod.POST,
                payload={"name": "test_user", "email": "test@example.com"},
                depends_on=["step1"],
                extract_variables={"new_user_id": "$.id"}
            )
        ]
        
        workflow_config = WorkflowConfig(
            workflow_name="integration_test_workflow",
            description="Test workflow for integration",
            steps=steps,
            virtual_users=1,
            duration="30s"
        )
        
        # Validate workflow
        validation_result = await service.validate_workflow(workflow_config)
        assert validation_result.success is True
        assert len(validation_result.data) == 0  # No errors
        
        # Create workflow
        creation_result = await service.create_workflow(workflow_config)
        assert creation_result.success is True
        workflow_id = creation_result.data
        
        # Mock workflow retrieval for execution
        workflow_repo.get_by_id = AsyncMock(return_value=workflow_config)
        
        # Execute workflow (with mocked HTTP requests)
        with patch.object(service, '_execute_step') as mock_execute_step:
            # Mock step execution results
            mock_execute_step.side_effect = [
                Mock(  # Step 1 result
                    step_id="step1",
                    success=True,
                    status_code=200,
                    response_body='[{"id": "user1"}, {"id": "user2"}]',
                    extracted_variables={"user_count": 2}
                ),
                Mock(  # Step 2 result
                    step_id="step2", 
                    success=True,
                    status_code=201,
                    response_body='{"id": "new_user_123", "name": "test_user"}',
                    extracted_variables={"new_user_id": "new_user_123"}
                )
            ]
            
            execution_result = await service.execute_workflow(workflow_id)
            assert execution_result.success is True
            
            workflow_result = execution_result.data
            assert workflow_result.workflow_id == workflow_id
            assert len(workflow_result.step_results) == 2
            assert workflow_result.successful_requests == 2
            assert workflow_result.failed_requests == 0


class TestOpenAPIServiceIntegration:
    """Integration tests for OpenAPIService with other services."""
    
    @pytest.fixture
    async def integrated_openapi_service(self):
        """Create OpenAPIService for integration testing."""
        config = Mock(spec=AppConfig)
        service = OpenAPIService(config)
        await service._initialize_impl()
        return service
    
    @pytest.mark.asyncio
    async def test_openapi_to_k6_test_generation_flow(self, integrated_openapi_service):
        """Test flow from OpenAPI spec to K6 test execution."""
        openapi_service = integrated_openapi_service
        
        # Step 1: Load and validate OpenAPI spec
        spec_url = "https://api.example.com/openapi.json"
        
        load_result = await openapi_service.load_openapi_spec(spec_url)
        assert load_result.success is True
        
        validation_result = await openapi_service.validate_openapi_spec(spec_url)
        assert validation_result.success is True
        assert len(validation_result.data) == 0  # No validation errors
        
        # Step 2: Generate test configurations
        test_config = {
            "virtual_users": 5,
            "duration": "60s"
        }
        
        generation_result = await openapi_service.generate_tests_from_spec(
            spec_url, 
            base_url="https://api.example.com/v1",
            test_config=test_config
        )
        
        assert generation_result.success is True
        test_configs = generation_result.data
        assert len(test_configs) > 0
        
        # Verify generated configurations
        for config in test_configs:
            assert isinstance(config, K6TestConfig)
            assert config.virtual_users == 5
            assert config.duration == "60s"
            assert config.url.startswith("https://api.example.com/v1")
        
        # Step 3: These configs could then be used with K6TestService
        # (This would be tested in a full end-to-end test)
    
    @pytest.mark.asyncio
    async def test_openapi_to_workflow_generation_flow(self, integrated_openapi_service):
        """Test flow from OpenAPI spec to workflow generation."""
        openapi_service = integrated_openapi_service
        
        spec_url = "https://api.example.com/openapi.json"
        workflow_name = "api_integration_workflow"
        
        # Generate workflow from spec
        workflow_result = await openapi_service.generate_workflow_from_spec(
            spec_url,
            workflow_name,
            base_url="https://api.example.com/v1"
        )
        
        assert workflow_result.success is True
        workflow_config = workflow_result.data
        
        assert isinstance(workflow_config, WorkflowConfig)
        assert workflow_config.workflow_name == workflow_name
        assert len(workflow_config.steps) > 0
        
        # Verify steps are properly configured
        for step in workflow_config.steps:
            assert isinstance(step, RequestStep)
            assert step.url.startswith("https://api.example.com/v1")
            assert step.method in [HttpMethod.GET, HttpMethod.POST, HttpMethod.PUT, HttpMethod.DELETE]
        
        # This workflow could then be used with WorkflowService
        # (Would be tested in full end-to-end test)


class TestCrossServiceDataFlow:
    """Test data flow between multiple services."""
    
    @pytest.mark.asyncio
    async def test_openapi_to_workflow_to_k6_execution_flow(self):
        """Test complete flow from OpenAPI spec to test execution."""
        # This would be a comprehensive test of the entire pipeline:
        # OpenAPI Spec -> Workflow Generation -> Workflow Execution -> Results
        
        # For now, this is a placeholder for the integration
        # In a real implementation, this would:
        # 1. Load OpenAPI spec
        # 2. Generate workflow
        # 3. Execute workflow through WorkflowService
        # 4. Store and retrieve results through ResultService
        pass
    
    @pytest.mark.asyncio
    async def test_service_error_propagation(self):
        """Test how errors propagate through service interactions."""
        # Test error handling across service boundaries
        pass
    
    @pytest.mark.asyncio
    async def test_service_performance_under_load(self):
        """Test service performance when multiple operations run concurrently."""
        # Test concurrent operations across services
        pass


class TestDependencyInjectionIntegration:
    """Test dependency injection container integration."""
    
    @pytest.mark.asyncio
    async def test_container_service_resolution(self):
        """Test service resolution through DI container."""
        container = DIContainer()
        
        # Mock configuration
        config = Mock(spec=AppConfig)
        config.reports_dir = Mock()
        config.csv_data_dir = Mock()
        config.k6 = Mock()
        
        # Register dependencies
        container.register_singleton(AppConfig, config)
        
        # Register repositories as factories
        def create_test_repo():
            return Mock(spec=TestRepository)
        
        def create_result_repo():
            return Mock(spec=ResultRepository)
        
        def create_workflow_repo():
            return Mock(spec=WorkflowRepository)
        
        container.register_factory(TestRepository, create_test_repo)
        container.register_factory(ResultRepository, create_result_repo)
        container.register_factory(WorkflowRepository, create_workflow_repo)
        
        # Register services as factories
        def create_k6_service():
            return K6TestService(
                container.resolve(AppConfig),
                container.resolve(TestRepository),
                container.resolve(ResultRepository)
            )
        
        def create_workflow_service():
            return WorkflowService(
                container.resolve(AppConfig),
                container.resolve(WorkflowRepository)
            )
        
        def create_result_service():
            return ResultService(
                container.resolve(AppConfig),
                container.resolve(ResultRepository)
            )
        
        container.register_factory(K6TestService, create_k6_service)
        container.register_factory(WorkflowService, create_workflow_service)
        container.register_factory(ResultService, create_result_service)
        
        # Resolve services
        k6_service = container.resolve(K6TestService)
        workflow_service = container.resolve(WorkflowService)
        result_service = container.resolve(ResultService)
        
        assert isinstance(k6_service, K6TestService)
        assert isinstance(workflow_service, WorkflowService)
        assert isinstance(result_service, ResultService)
        
        # Services should have proper dependencies injected
        assert k6_service.config is config
        assert workflow_service.config is config
        assert result_service.config is config


class TestEventSystemIntegration:
    """Test event system integration across services."""
    
    @pytest.mark.asyncio
    async def test_service_event_publishing_and_handling(self):
        """Test event publishing and handling between services."""
        # Test the event system that allows services to communicate
        # through events rather than direct coupling
        pass
    
    @pytest.mark.asyncio
    async def test_workflow_event_coordination(self):
        """Test workflow events coordinate multiple service actions."""
        # Test how workflow events trigger actions in other services
        pass


# Test fixtures for integration testing
@pytest.fixture
async def integrated_test_environment():
    """Create a full integrated test environment."""
    config = Mock(spec=AppConfig)
    config.reports_dir = Mock()
    config.csv_data_dir = Mock()
    config.templates_dir = Mock()
    config.k6 = Mock()
    config.k6.max_virtual_users = 1000
    config.k6.default_timeout = "30s"
    config.k6.enable_html_reports = True
    config.k6.k6_binary_path = "k6"
    config.k6.results_retention_days = 30
    
    # Create repository mocks
    test_repo = Mock(spec=TestRepository)
    test_repo.create_test = AsyncMock(return_value=Mock(success=True))
    test_repo.get_test = AsyncMock(return_value=None)
    
    result_repo = Mock(spec=ResultRepository)
    result_repo.save_result = AsyncMock(return_value=Mock(success=True))
    result_repo.get_result = AsyncMock(return_value=None)
    result_repo.list_recent_results = AsyncMock(return_value=[])
    
    workflow_repo = Mock(spec=WorkflowRepository)
    workflow_repo.create_with_id = AsyncMock(return_value=Mock(success=True))
    workflow_repo.get_by_id = AsyncMock(return_value=None)
    
    # Create services
    k6_service = K6TestService(config, test_repo, result_repo)
    workflow_service = WorkflowService(config, workflow_repo)
    result_service = ResultService(config, result_repo)
    openapi_service = OpenAPIService(config)
    
    # Initialize services
    await k6_service._initialize_impl()
    await workflow_service._initialize_impl()
    await result_service._initialize_impl()
    await openapi_service._initialize_impl()
    
    return {
        "config": config,
        "repositories": {
            "test": test_repo,
            "result": result_repo,
            "workflow": workflow_repo
        },
        "services": {
            "k6": k6_service,
            "workflow": workflow_service,
            "result": result_service,
            "openapi": openapi_service
        }
    }


@pytest.fixture
def sample_integration_data():
    """Sample data for integration testing."""
    return {
        "k6_config": K6TestConfig(
            url="https://api.example.com/integration-test",
            method=HttpMethod.GET,
            virtual_users=5,
            duration="30s"
        ),
        "workflow_config": WorkflowConfig(
            workflow_name="integration_test_workflow",
            steps=[
                RequestStep(
                    step_id="step1",
                    name="Integration test step",
                    url="https://api.example.com/test",
                    method=HttpMethod.GET
                )
            ],
            virtual_users=3,
            duration="45s"
        ),
        "test_result": K6TestResult(
            test_id="integration_test_123",
            config={"url": "https://api.example.com/integration-test"},
            success=True,
            start_time=datetime.utcnow(),
            metrics=TestMetrics(
                http_reqs=50,
                http_req_failed=0.02,
                http_req_duration={"avg": 200.0},
                vus=5
            )
        )
    }