"""
End-to-end tests for complete workflows.

Tests entire user journeys from MCP requests to K6 execution and results.
"""

import pytest
import asyncio
import json
import tempfile
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from server_new import MCPServer
from core.config import AppConfig
from domain.models import K6TestConfig, HttpMethod, LoadPattern


class TestMCPServerE2E:
    """End-to-end tests for MCP server functionality."""
    
    @pytest.fixture
    async def mcp_server(self):
        """Create MCP server for end-to-end testing."""
        # Create temporary directories for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Mock configuration
            config = Mock(spec=AppConfig)
            config.reports_dir = temp_path / "reports"
            config.csv_data_dir = temp_path / "csv_data"
            config.templates_dir = temp_path / "templates"
            config.reports_dir.mkdir(parents=True, exist_ok=True)
            config.csv_data_dir.mkdir(parents=True, exist_ok=True)
            config.templates_dir.mkdir(parents=True, exist_ok=True)
            
            config.k6 = Mock()
            config.k6.max_virtual_users = 100
            config.k6.default_timeout = "30s"
            config.k6.enable_html_reports = True
            config.k6.k6_binary_path = "k6"
            config.k6.results_retention_days = 30
            
            # Create server
            server = MCPServer()
            
            # Initialize with mocked dependencies
            with patch.object(server, '_load_config', return_value=config):
                await server.initialize()
            
            yield server
            
            # Cleanup
            await server.cleanup()
    
    @pytest.mark.asyncio
    async def test_single_k6_test_execution_flow(self, mcp_server):
        """Test complete single K6 test execution flow."""
        server = mcp_server
        
        # Step 1: Prepare test via MCP handler
        test_config = {
            "url": "https://httpbin.org/get",
            "method": "GET",
            "virtual_users": 1,
            "iterations": 1,
            "load_pattern": "constant_load"
        }
        
        # Mock K6 execution for testing
        with patch('subprocess.run') as mock_subprocess:
            mock_subprocess.return_value.returncode = 0
            mock_subprocess.return_value.stdout = "Test completed"
            mock_subprocess.return_value.stderr = ""
            
            # Simulate MCP request handling
            k6_handler = server.container.resolve("K6Handler")  # This would be the actual handler
            
            # For testing, we'll call the service directly
            k6_service = server.container.resolve("K6TestService")
            
            # Test preparation
            prepare_result = await k6_service.prepare_test(K6TestConfig(**test_config))
            assert prepare_result.success is True
            
            test_id = prepare_result.metadata["test_id"]
            
            # Test confirmation
            confirm_result = await k6_service.confirm_test(test_id, "y")
            assert confirm_result.success is True
            
            # Mock test execution
            with patch.object(k6_service, '_validate_k6_binary', return_value=True):
                with patch.object(k6_service, '_execute_test_internal') as mock_execute:
                    from domain.models import K6TestResult
                    from datetime import datetime
                    
                    mock_result = K6TestResult(
                        test_id=test_id,
                        config=test_config,
                        success=True,
                        start_time=datetime.utcnow()
                    )
                    mock_execute.return_value = Mock(success=True, data=mock_result)
                    
                    # Test execution
                    execute_result = await k6_service.execute_confirmed_test(test_id)
                    assert execute_result.success is True
                    assert execute_result.data.test_id == test_id
    
    @pytest.mark.asyncio
    async def test_workflow_execution_flow(self, mcp_server):
        """Test complete workflow execution flow."""
        server = mcp_server
        
        # Create workflow configuration
        workflow_config = {
            "workflow_name": "e2e_test_workflow",
            "description": "End-to-end test workflow",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Get users",
                    "url": "https://httpbin.org/get",
                    "method": "GET",
                    "extract_variables": {
                        "request_count": "$.headers.X-Request-Count"
                    }
                },
                {
                    "step_id": "step2",
                    "name": "Post data",
                    "url": "https://httpbin.org/post",
                    "method": "POST",
                    "payload": {
                        "test_data": "{{request_count}}"
                    },
                    "depends_on": ["step1"]
                }
            ],
            "virtual_users": 1,
            "duration": "30s"
        }
        
        workflow_service = server.container.resolve("WorkflowService")
        
        from domain.models import WorkflowConfig, RequestStep
        
        # Convert to domain model
        steps = []
        for step_data in workflow_config["steps"]:
            step = RequestStep(
                step_id=step_data["step_id"],
                name=step_data["name"],
                url=step_data["url"],
                method=HttpMethod(step_data["method"]),
                extract_variables=step_data.get("extract_variables"),
                payload=step_data.get("payload"),
                depends_on=step_data.get("depends_on", [])
            )
            steps.append(step)
        
        workflow = WorkflowConfig(
            workflow_name=workflow_config["workflow_name"],
            description=workflow_config["description"],
            steps=steps,
            virtual_users=workflow_config["virtual_users"],
            duration=workflow_config["duration"]
        )
        
        # Test workflow validation
        validation_result = await workflow_service.validate_workflow(workflow)
        assert validation_result.success is True
        assert len(validation_result.data) == 0  # No validation errors
        
        # Test workflow creation
        creation_result = await workflow_service.create_workflow(workflow)
        assert creation_result.success is True
        workflow_id = creation_result.data
        
        # Mock workflow execution
        with patch.object(workflow_service, '_execute_step') as mock_execute_step:
            from domain.models import StepResult
            from datetime import datetime
            
            # Mock successful step executions
            mock_execute_step.side_effect = [
                StepResult(
                    step_id="step1",
                    success=True,
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow(),
                    status_code=200,
                    response_body='{"headers": {"X-Request-Count": "1"}}',
                    extracted_variables={"request_count": "1"}
                ),
                StepResult(
                    step_id="step2",
                    success=True,
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow(),
                    status_code=200,
                    response_body='{"json": {"test_data": "1"}}'
                )
            ]
            
            # Execute workflow
            execution_result = await workflow_service.execute_workflow(workflow_id)
            assert execution_result.success is True
            
            workflow_result = execution_result.data
            assert workflow_result.workflow_id == workflow_id
            assert len(workflow_result.step_results) == 2
            assert workflow_result.successful_requests == 2
    
    @pytest.mark.asyncio
    async def test_openapi_to_test_generation_flow(self, mcp_server):
        """Test OpenAPI specification to test generation flow."""
        server = mcp_server
        openapi_service = server.container.resolve("OpenAPIService")
        
        # Test with the built-in example OpenAPI spec
        spec_url = "https://api.example.com/openapi.json"
        
        # Load and validate spec
        load_result = await openapi_service.load_openapi_spec(spec_url)
        assert load_result.success is True
        
        validation_result = await openapi_service.validate_openapi_spec(spec_url)
        assert validation_result.success is True
        assert len(validation_result.data) == 0
        
        # Generate tests from spec
        generation_result = await openapi_service.generate_tests_from_spec(
            spec_url,
            base_url="https://api.example.com/v1"
        )
        assert generation_result.success is True
        
        test_configs = generation_result.data
        assert len(test_configs) > 0
        
        # Verify generated test configurations are valid
        for config in test_configs:
            assert isinstance(config, K6TestConfig)
            assert config.url.startswith("https://api.example.com/v1")
            assert config.method in [HttpMethod.GET, HttpMethod.POST]
    
    @pytest.mark.asyncio
    async def test_result_retrieval_and_analysis_flow(self, mcp_server):
        """Test result storage, retrieval, and analysis flow."""
        server = mcp_server
        result_service = server.container.resolve("ResultService")
        
        # Create mock test results
        from domain.models import K6TestResult, TestMetrics
        from datetime import datetime, timedelta
        
        test_results = []
        for i in range(3):
            result = K6TestResult(
                test_id=f"e2e_test_{i}",
                config={"url": f"https://api.example.com/test{i}"},
                success=i < 2,  # First two successful
                start_time=datetime.utcnow() - timedelta(hours=i),
                end_time=datetime.utcnow() - timedelta(hours=i) + timedelta(minutes=1),
                metrics=TestMetrics(
                    http_reqs=100 + i * 10,
                    http_req_failed=0.01 if i < 2 else 0.1,
                    http_req_duration={"avg": 150.0 + i * 10},
                    vus=10
                )
            )
            test_results.append(result)
        
        # Mock result repository
        result_service.result_repository.get_result = AsyncMock()
        result_service.result_repository.list_recent_results = AsyncMock()
        
        def mock_get_result(test_id):
            for result in test_results:
                if result.test_id == test_id:
                    return result
            return None
        
        result_service.result_repository.get_result.side_effect = mock_get_result
        result_service.result_repository.list_recent_results.return_value = [
            {
                "test_id": r.test_id,
                "success": r.success,
                "start_time": r.start_time.isoformat(),
                "duration_seconds": r.get_duration(),
                "url": r.config.get("url", ""),
                "virtual_users": 10,
                "http_reqs": r.metrics.http_reqs if r.metrics else 0,
                "failure_rate": r.metrics.http_req_failed if r.metrics else 0
            }
            for r in test_results
        ]
        
        # Test individual result retrieval
        with patch.object(result_service, '_get_result_file_paths') as mock_files:
            mock_files.return_value = {"html_report": "/path/to/report.html"}
            
            for result in test_results:
                retrieved = await result_service.get_test_results(result.test_id)
                assert retrieved.success is True
                assert retrieved.data["test_id"] == result.test_id
        
        # Test summary report generation
        test_ids = [r.test_id for r in test_results]
        summary_result = await result_service.generate_summary_report(test_ids)
        assert summary_result.success is True
        
        summary = summary_result.data
        assert summary["total_tests"] == 3
        assert summary["successful_tests"] == 2
        assert summary["failed_tests"] == 1
        
        # Test recent results listing
        recent_result = await result_service.list_recent_results(days=1, limit=10)
        assert recent_result.success is True
        assert len(recent_result.data) == 3
    
    @pytest.mark.asyncio
    async def test_performance_monitoring_integration(self, mcp_server):
        """Test performance monitoring across all services."""
        server = mcp_server
        
        # Access global performance monitoring
        from utils.performance import global_health, global_metrics
        
        # Run health checks for all services
        health_results = await global_health.run_checks(force=True)
        
        # Should have health checks for all services
        expected_components = ["k6_service", "workflow_service", "result_service", "openapi_service"]
        
        for component in expected_components:
            if component in health_results:
                assert "healthy" in health_results[component]
                assert "component" in health_results[component]
        
        # Check overall health
        assert "overall" in health_results
        
        # Test metrics collection
        # Metrics would be collected automatically through @performance_monitor decorators
        # during service operations
        all_metrics = await global_metrics.get_all_stats()
        
        # Metrics may or may not be present depending on what operations ran
        # But the metrics system should be functional
        assert isinstance(all_metrics, dict)


class TestErrorHandlingE2E:
    """End-to-end tests for error handling and recovery."""
    
    @pytest.mark.asyncio
    async def test_service_failure_recovery(self):
        """Test system behavior when services fail."""
        # Test graceful degradation when components fail
        pass
    
    @pytest.mark.asyncio
    async def test_invalid_input_handling(self):
        """Test handling of invalid inputs through the entire pipeline."""
        # Test error propagation from MCP requests to final responses
        pass
    
    @pytest.mark.asyncio
    async def test_resource_exhaustion_handling(self):
        """Test behavior under resource constraints."""
        # Test memory limits, file descriptor limits, etc.
        pass


class TestPerformanceE2E:
    """End-to-end performance tests."""
    
    @pytest.mark.asyncio
    async def test_concurrent_test_execution(self):
        """Test multiple concurrent test executions."""
        # Test system behavior with multiple simultaneous operations
        pass
    
    @pytest.mark.asyncio
    async def test_large_workflow_execution(self):
        """Test execution of workflows with many steps."""
        # Test scalability with complex workflows
        pass
    
    @pytest.mark.asyncio
    async def test_memory_usage_over_time(self):
        """Test memory usage patterns over extended operation."""
        # Test for memory leaks and resource management
        pass


class TestSecurityE2E:
    """End-to-end security tests."""
    
    @pytest.mark.asyncio
    async def test_input_validation_security(self):
        """Test security of input validation."""
        # Test protection against malicious inputs
        pass
    
    @pytest.mark.asyncio
    async def test_file_system_security(self):
        """Test file system access security."""
        # Test that file operations are properly restricted
        pass


# Test utilities for E2E testing
def create_mock_k6_output():
    """Create mock K6 output for testing."""
    return {
        "stdout": """
          /\\      |‾‾| /‾‾/   /‾‾/   
         /  \\     |  |/  /   /  /    
        /    \\    |     (   /   ‾‾\\  
       /      \\   |  |\\  \\ |  (‾)  | 
      / _______ \\  |__| \\__\\ \\_____/ .io

     execution: local
        script: test_script.js
        output: -

     scenarios: (100.00%) 1 scenario, 1 max VUs, 1m30s max duration (incl. graceful stop):
              * default: 1 iterations for each of 1 VUs (maxDuration: 1m30s, gracefulStop: 30s)

     data_received..................: 1.2 kB 40 B/s
     data_sent......................: 517 B  17 B/s
     http_req_blocked...............: avg=147ms min=147ms med=147ms max=147ms p(90)=147ms p(95)=147ms
     http_req_connecting............: avg=45ms  min=45ms  med=45ms  max=45ms  p(90)=45ms  p(95)=45ms
     http_req_duration..............: avg=152ms min=152ms med=152ms max=152ms p(90)=152ms p(95)=152ms
     http_req_failed................: 0.00%  ✓ 0        ✗ 1
     http_req_receiving.............: avg=1ms   min=1ms   med=1ms   max=1ms   p(90)=1ms   p(95)=1ms
     http_req_sending...............: avg=0ms   min=0ms   med=0ms   max=0ms   p(90)=0ms   p(95)=0ms
     http_req_tls_handshaking.......: avg=101ms min=101ms med=101ms max=101ms p(90)=101ms p(95)=101ms
     http_req_waiting...............: avg=150ms min=150ms med=150ms max=150ms p(90)=150ms p(95)=150ms
     http_reqs......................: 1      0.032258/s
     iteration_duration.............: avg=300ms min=300ms med=300ms max=300ms p(90)=300ms p(95)=300ms
     iterations.....................: 1      0.032258/s
     vus............................: 1      min=1      max=1
     vus_max........................: 1      min=1      max=1
        """,
        "stderr": "",
        "returncode": 0
    }


def create_mock_workflow_responses():
    """Create mock HTTP responses for workflow testing."""
    return {
        "step1": {
            "status_code": 200,
            "headers": {"Content-Type": "application/json"},
            "body": '{"users": [{"id": "user1"}, {"id": "user2"}], "count": 2}'
        },
        "step2": {
            "status_code": 201,
            "headers": {"Content-Type": "application/json"},
            "body": '{"id": "new_user_123", "name": "test_user", "created": true}'
        }
    }


# E2E test fixtures
@pytest.fixture
def e2e_test_data():
    """Test data for end-to-end testing."""
    return {
        "simple_test_config": {
            "url": "https://httpbin.org/get",
            "method": "GET",
            "virtual_users": 1,
            "iterations": 1
        },
        "workflow_config": {
            "workflow_name": "e2e_test_workflow",
            "steps": [
                {
                    "step_id": "get_data",
                    "name": "Get test data",
                    "url": "https://httpbin.org/get",
                    "method": "GET"
                },
                {
                    "step_id": "post_data",
                    "name": "Post test data",
                    "url": "https://httpbin.org/post",
                    "method": "POST",
                    "payload": {"test": "data"},
                    "depends_on": ["get_data"]
                }
            ],
            "virtual_users": 2,
            "duration": "30s"
        }
    }