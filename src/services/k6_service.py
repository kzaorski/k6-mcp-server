"""
K6 Test Service.

Business logic for K6 test execution, configuration, and result processing.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List
from pathlib import Path

from core.base import BaseService, OperationResult
from core.config import AppConfig
from repositories.test_repository import TestRepository
from repositories.result_repository import ResultRepository
from domain.models import K6TestConfig, K6TestResult, TestStatus
from utils.performance import performance_monitor, global_metrics, global_health

logger = logging.getLogger(__name__)


class K6TestService(BaseService):
    """
    Service for managing K6 test execution and lifecycle.
    
    Provides high-level operations for test preparation, execution,
    and result management with proper error handling and validation.
    """
    
    def __init__(
        self,
        config: AppConfig,
        test_repository: TestRepository,
        result_repository: ResultRepository
    ):
        super().__init__(config)
        self.test_repository = test_repository
        self.result_repository = result_repository
        
        # Test execution state
        self.pending_tests: Dict[str, K6TestConfig] = {}
        self.confirmed_tests: Dict[str, K6TestConfig] = {}
        self.running_tests: Dict[str, asyncio.Task] = {}
    
    async def _initialize_impl(self) -> None:
        """Initialize the K6 test service."""
        # Ensure required directories exist
        self.config.reports_dir.mkdir(parents=True, exist_ok=True)
        self.config.csv_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate K6 binary availability
        if not await self._validate_k6_binary():
            self.logger.warning("K6 binary not found or not executable")
        
        # Register health check
        global_health.register_check("k6_service", self._health_check)
    
    @performance_monitor("k6_service.prepare_test")
    async def prepare_test(self, config: K6TestConfig) -> OperationResult[str]:
        """
        Prepare a K6 test for execution.
        
        Args:
            config: Test configuration
            
        Returns:
            Operation result with test preparation details
        """
        operation_id = self.log_operation_start("prepare_test", url=config.url)
        
        try:
            # Validate configuration
            validation_result = await self._validate_test_config(config)
            if not validation_result.success:
                return validation_result
            
            # Generate test ID
            test_id = self._generate_test_id()
            
            # Store test configuration
            save_result = await self.test_repository.create_test(test_id, config)
            if not save_result.success:
                return OperationResult.error_result(
                    f"Failed to save test configuration: {save_result.error_message}"
                )
            
            # Store in pending tests
            self.pending_tests[test_id] = config
            
            # Generate test script
            script_result = await self._generate_test_script(test_id, config)
            if not script_result.success:
                return script_result
            
            self.log_operation_end(operation_id, True)
            
            return OperationResult.success_result(
                data=f"""✅ K6 Test Prepared Successfully

🎯 **Test Configuration**
• Test ID: {test_id}
• URL: {config.url}
• Method: {config.method}
• Virtual Users: {config.virtual_users}
• {'Duration: ' + config.duration if config.duration else 'Iterations: ' + str(config.iterations)}

🔧 **Test Script Generated**
• Script Path: {script_result.data}
• Load Pattern: {config.load_pattern}
• {'HTML Dashboard: Enabled' if self.config.k6.enable_html_reports else ''}

⚠️ **Confirmation Required**
This test is prepared but NOT executed. Use 'confirm_test' to proceed.

📋 **Next Steps:**
1. Review the test configuration above
2. Use 'confirm_test' with response 'y' to confirm execution
3. Use 'execute_confirmed_test' to run the test""",
                metadata={"test_id": test_id, "script_path": script_result.data}
            )
            
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return OperationResult.error_result(f"Test preparation failed: {str(e)}")
    
    async def confirm_test(self, test_id: str, response: str) -> OperationResult[str]:
        """
        Confirm test execution.
        
        Args:
            test_id: Test identifier
            response: User confirmation response
            
        Returns:
            Operation result with confirmation status
        """
        response = response.lower().strip()
        
        if response in ("y", "yes"):
            if test_id in self.pending_tests:
                config = self.pending_tests.pop(test_id)
                self.confirmed_tests[test_id] = config
                
                return OperationResult.success_result(
                    f"✅ Test {test_id} confirmed and ready for execution. Use 'execute_confirmed_test' to run it."
                )
            else:
                return OperationResult.error_result(f"No pending test found with ID: {test_id}")
        
        elif response in ("n", "no"):
            if test_id in self.pending_tests:
                self.pending_tests.pop(test_id)
                return OperationResult.success_result(f"❌ Test {test_id} cancelled.")
            else:
                return OperationResult.error_result(f"No pending test found with ID: {test_id}")
        
        else:
            return OperationResult.error_result(
                f"Invalid response '{response}'. Please use 'y'/'yes' to confirm or 'n'/'no' to cancel."
            )
    
    @performance_monitor("k6_service.execute_test")
    async def execute_confirmed_test(self, test_id: str) -> OperationResult[K6TestResult]:
        """
        Execute a confirmed test.
        
        Args:
            test_id: Test identifier
            
        Returns:
            Operation result with test execution results
        """
        if test_id not in self.confirmed_tests:
            return OperationResult.error_result(f"No confirmed test found with ID: {test_id}")
        
        config = self.confirmed_tests.pop(test_id)
        operation_id = self.log_operation_start("execute_test", test_id=test_id)
        
        try:
            # Create execution task
            execution_task = asyncio.create_task(self._execute_test_internal(test_id, config))
            self.running_tests[test_id] = execution_task
            
            # Wait for completion
            result = await execution_task
            
            # Clean up
            self.running_tests.pop(test_id, None)
            
            # Store result
            if result.success:
                await self.result_repository.save_result(test_id, result.data)
            
            self.log_operation_end(operation_id, result.success)
            return result
            
        except Exception as e:
            self.log_operation_error(operation_id, e)
            self.running_tests.pop(test_id, None)
            return OperationResult.error_result(f"Test execution failed: {str(e)}")
    
    async def get_test_status(self, test_id: str) -> OperationResult[TestStatus]:
        """Get the current status of a test."""
        if test_id in self.pending_tests:
            return OperationResult.success_result(TestStatus.PENDING)
        elif test_id in self.confirmed_tests:
            return OperationResult.success_result(TestStatus.CONFIRMED)
        elif test_id in self.running_tests:
            return OperationResult.success_result(TestStatus.RUNNING)
        else:
            # Check if completed
            result = await self.result_repository.get_result(test_id)
            if result:
                return OperationResult.success_result(TestStatus.COMPLETED)
            else:
                return OperationResult.error_result(f"Test not found: {test_id}")
    
    async def cancel_test(self, test_id: str) -> OperationResult[str]:
        """Cancel a running test."""
        if test_id in self.running_tests:
            task = self.running_tests.pop(test_id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            return OperationResult.success_result(f"Test {test_id} cancelled")
        else:
            return OperationResult.error_result(f"No running test found with ID: {test_id}")
    
    async def list_active_tests(self) -> OperationResult[List[Dict[str, Any]]]:
        """List all active tests."""
        active_tests = []
        
        for test_id, config in self.pending_tests.items():
            active_tests.append({
                "test_id": test_id,
                "status": "pending",
                "url": config.url,
                "method": config.method,
                "virtual_users": config.virtual_users
            })
        
        for test_id, config in self.confirmed_tests.items():
            active_tests.append({
                "test_id": test_id,
                "status": "confirmed",
                "url": config.url,
                "method": config.method,
                "virtual_users": config.virtual_users
            })
        
        for test_id in self.running_tests.keys():
            # Get config from repository
            config = await self.test_repository.get_test(test_id)
            if config:
                active_tests.append({
                    "test_id": test_id,
                    "status": "running",
                    "url": config.url,
                    "method": config.method,
                    "virtual_users": config.virtual_users
                })
        
        return OperationResult.success_result(active_tests)
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check for K6 service."""
        start_time = time.time()
        
        try:
            # Check K6 binary
            k6_available = await self._validate_k6_binary()
            if not k6_available:
                return {
                    "component": "k6_service",
                    "status": "unhealthy",
                    "message": "K6 binary not available",
                    "duration_ms": (time.time() - start_time) * 1000
                }
            
            # Check filesystem access
            if not self.config.reports_dir.exists():
                return {
                    "component": "k6_service",
                    "status": "unhealthy",
                    "message": "Reports directory not accessible",
                    "duration_ms": (time.time() - start_time) * 1000
                }
            
            # Check running tests
            active_count = len(self.pending_tests) + len(self.confirmed_tests) + len(self.running_tests)
            status = "healthy"
            message = f"Service operational. Active tests: {active_count}"
            
            if active_count > 10:  # Arbitrary threshold
                status = "degraded" 
                message = f"High test load. Active tests: {active_count}"
            
            return {
                "component": "k6_service",
                "status": status,
                "message": message,
                "duration_ms": (time.time() - start_time) * 1000
            }
            
        except Exception as e:
            return {
                "component": "k6_service",
                "status": "unhealthy",
                "message": f"Health check failed: {str(e)}",
                "duration_ms": (time.time() - start_time) * 1000
            }
    
    # Private methods
    
    async def _validate_test_config(self, config: K6TestConfig) -> OperationResult[None]:
        """Validate test configuration."""
        errors = []
        
        # URL validation
        if not config.url:
            errors.append("URL is required")
        elif not config.url.startswith(("http://", "https://")):
            errors.append("URL must start with http:// or https://")
        
        # Virtual users validation
        if config.virtual_users < 1 or config.virtual_users > self.config.k6.max_virtual_users:
            errors.append(f"Virtual users must be between 1 and {self.config.k6.max_virtual_users}")
        
        # Duration/iterations validation
        if config.duration and config.iterations:
            errors.append("Cannot specify both duration and iterations")
        elif not config.duration and not config.iterations:
            errors.append("Must specify either duration or iterations")
        
        if errors:
            return OperationResult.error_result("Configuration validation failed: " + "; ".join(errors))
        
        return OperationResult.success_result()
    
    async def _validate_k6_binary(self) -> bool:
        """Validate that K6 binary is available."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.k6.k6_binary_path, "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            return process.returncode == 0
        except Exception:
            return False
    
    def _generate_test_id(self) -> str:
        """Generate unique test ID."""
        import uuid
        timestamp = int(time.time())
        return f"test_{timestamp}_{uuid.uuid4().hex[:8]}"
    
    async def _generate_test_script(self, test_id: str, config: K6TestConfig) -> OperationResult[str]:
        """Generate K6 test script."""
        try:
            # Load template based on load pattern
            template_file = self.config.templates_dir / f"{config.load_pattern}.js"
            if not template_file.exists():
                template_file = self.config.templates_dir / "constant_load.js"
            
            with open(template_file, 'r') as f:
                template = f.read()
            
            # Replace template variables
            script_content = self._substitute_template_variables(template, config)
            
            # Save script
            script_path = self.config.reports_dir / f"k6_test_{test_id}.js"
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            return OperationResult.success_result(str(script_path))
            
        except Exception as e:
            return OperationResult.error_result(f"Script generation failed: {str(e)}")
    
    def _substitute_template_variables(self, template: str, config: K6TestConfig) -> str:
        """Substitute template variables with config values."""
        replacements = {
            "{{URL}}": config.url,
            "{{METHOD}}": config.method,
            "{{VIRTUAL_USERS}}": str(config.virtual_users),
            "{{DURATION}}": config.duration or "undefined",
            "{{ITERATIONS}}": str(config.iterations) if config.iterations else "undefined",
            "{{HEADERS}}": json.dumps(config.headers or {}),
            "{{PAYLOAD}}": json.dumps(config.payload or {}),
            "{{TIMEOUT}}": config.timeout or self.config.k6.default_timeout,
            "{{THINK_TIME}}": str(config.think_time or 1.0)
        }
        
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        
        return result
    
    async def _execute_test_internal(self, test_id: str, config: K6TestConfig) -> OperationResult[K6TestResult]:
        """Internal test execution logic."""
        script_path = self.config.reports_dir / f"k6_test_{test_id}.js"
        
        # Ensure subdirectories exist
        (self.config.reports_dir / "csv").mkdir(exist_ok=True)
        (self.config.reports_dir / "html").mkdir(exist_ok=True)
        
        # Build K6 command with absolute paths
        results_path = self.config.reports_dir / f"test_{test_id}_results.json"
        csv_path = self.config.reports_dir / "csv" / f"test_{test_id}_metrics.csv"
        summary_path = self.config.reports_dir / f"test_{test_id}_summary.json"
        
        cmd = [
            self.config.k6.k6_binary_path,
            "run",
            "--out", f"json={results_path}",
            "--out", f"csv={csv_path}",
            "--summary-export", str(summary_path),
            str(script_path)
        ]
        
        # Add HTML dashboard if enabled
        if self.config.k6.enable_html_reports:
            html_path = self.config.reports_dir / "html" / f"html-report_{test_id}.html"
            cmd.extend([
                "--out", f"json={html_path}"
            ])
        
        try:
            # Execute K6
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            # Parse results
            if results_path.exists():
                with open(results_path, 'r') as f:
                    results_data = json.load(f)
                
                test_result = K6TestResult(
                    test_id=test_id,
                    config=config.model_dump(),
                    results=results_data,
                    success=process.returncode == 0,
                    stdout=stdout.decode() if stdout else "",
                    stderr=stderr.decode() if stderr else ""
                )
                
                return OperationResult.success_result(test_result)
            else:
                return OperationResult.error_result("No results file generated")
                
        except Exception as e:
            return OperationResult.error_result(f"Test execution failed: {str(e)}")
    
    def _health_check(self) -> Dict[str, Any]:
        """Health check for K6 service."""
        try:
            # Check if reports directory exists and is writable
            reports_accessible = self.config.reports_dir.exists() and self.config.reports_dir.is_dir()
            
            # Check pending tests count
            pending_count = len(self._pending_tests)
            
            # Check if too many pending tests
            healthy = reports_accessible and pending_count < 10
            
            return {
                "healthy": healthy,
                "reports_directory_accessible": reports_accessible,
                "pending_tests_count": pending_count,
                "k6_binary_path": self.config.k6.k6_binary_path,
                "warning": "Too many pending tests" if pending_count >= 10 else None
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e)
            }