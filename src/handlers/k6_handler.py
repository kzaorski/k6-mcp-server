"""
K6 Test Handler.

Handles MCP tool calls for K6 test operations including preparation,
execution, and result retrieval.
"""

import logging
from typing import Any, Dict

from core.base import BaseHandler
from core.config import AppConfig
from services.k6_service import K6TestService
from domain.models import K6TestConfig

logger = logging.getLogger(__name__)


class K6TestHandler(BaseHandler):
    """
    Handler for K6 test-related MCP tool calls.
    
    Processes requests for test preparation, execution, confirmation,
    and status management with proper validation and error handling.
    """
    
    def __init__(self, config: AppConfig, k6_service: K6TestService):
        super().__init__(config)
        self.k6_service = k6_service
    
    async def handle(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle K6 test tool calls."""
        
        try:
            if name in ("run_k6_single_test", "run_k6_test"):
                return await self._handle_prepare_test(arguments)
            
            elif name == "run_k6_custom_stages_test":
                return await self._handle_prepare_custom_stages_test(arguments)
            
            elif name == "confirm_test":
                return await self._handle_confirm_test(arguments)
            
            elif name == "execute_confirmed_test":
                return await self._handle_execute_confirmed_test(arguments)
            
            elif name == "confirm_test_interactive":
                return await self._handle_interactive_confirmation(arguments)
            
            elif name == "check_confirmation_state":
                return await self._handle_check_confirmation_state(arguments)
            
            elif name == "get_test_status":
                return await self._handle_get_test_status(arguments)
            
            elif name == "cancel_test":
                return await self._handle_cancel_test(arguments)
            
            elif name == "list_active_tests":
                return await self._handle_list_active_tests(arguments)
            
            else:
                return self.create_error_response(f"Unknown tool: {name}")
                
        except Exception as e:
            self.logger.error(f"Error handling {name}: {e}", exc_info=True)
            return self.create_error_response(f"Handler error: {str(e)}")
    
    async def _handle_prepare_test(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test preparation."""
        operation_id = self.log_operation_start("prepare_test")
        
        # 🚨 SAFETY LOG - This should only happen on explicit user request
        self.logger.warning("🚨 SAFETY ALERT: run_k6_test tool was called - this should ONLY happen on explicit user request")
        self.logger.warning("🚨 If this was called autonomously by AI, this is a SAFETY VIOLATION")
        
        try:
            # Parse and validate configuration
            config = K6TestConfig(**arguments)
            
            # Prepare test
            result = await self.k6_service.prepare_test(config)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                return self.create_success_response(result.data)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Test preparation failed: {str(e)}")
    
    async def _handle_prepare_custom_stages_test(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle custom stages test preparation."""
        operation_id = self.log_operation_start("prepare_custom_stages_test")
        
        # 🚨 SAFETY LOG
        self.logger.warning("🚨 SAFETY ALERT: run_k6_custom_stages_test tool was called - this should ONLY happen on explicit user request")
        
        try:
            # Set load pattern and prepare config
            arguments['load_pattern'] = 'custom_stages'
            config = K6TestConfig(**arguments)
            
            # Validate stages
            if not config.stages:
                return self.create_error_response("Stages configuration is required for custom stages test")
            
            # Prepare test
            result = await self.k6_service.prepare_test(config)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                return self.create_success_response(result.data)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Custom stages test preparation failed: {str(e)}")
    
    async def _handle_confirm_test(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test confirmation."""
        response = arguments.get("response", "n").lower().strip()
        
        # Get the most recent test ID from active tests
        active_tests_result = await self.k6_service.list_active_tests()
        if not active_tests_result.success or not active_tests_result.data:
            return self.create_error_response("No pending tests to confirm")
        
        # Find pending test
        pending_test = next((t for t in active_tests_result.data if t["status"] == "pending"), None)
        if not pending_test:
            return self.create_error_response("No pending tests found")
        
        test_id = pending_test["test_id"]
        
        # Confirm test
        result = await self.k6_service.confirm_test(test_id, response)
        
        if result.success:
            return self.create_success_response(result.data)
        else:
            return self.create_error_response(result.error_message)
    
    async def _handle_execute_confirmed_test(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle execution of confirmed test."""
        operation_id = self.log_operation_start("execute_confirmed_test")
        
        try:
            # Get confirmed test
            active_tests_result = await self.k6_service.list_active_tests()
            if not active_tests_result.success:
                return self.create_error_response("Failed to get active tests")
            
            confirmed_test = next((t for t in active_tests_result.data if t["status"] == "confirmed"), None)
            if not confirmed_test:
                return self.create_error_response("No confirmed test ready for execution. Use confirm_test first.")
            
            test_id = confirmed_test["test_id"]
            
            # Execute test
            result = await self.k6_service.execute_confirmed_test(test_id)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                # Format result
                test_result = result.data
                formatted_result = self._format_test_result(test_result)
                
                return self.create_success_response(formatted_result)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Test execution failed: {str(e)}")
    
    async def _handle_interactive_confirmation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle interactive test confirmation."""
        confirmation_message = arguments.get("confirmation_message", "Do you want to run this test? (y/n)")
        
        # Get pending test information
        active_tests_result = await self.k6_service.list_active_tests()
        if not active_tests_result.success or not active_tests_result.data:
            return self.create_error_response("No pending test or workflow to confirm. Please run a test preparation tool first.")
        
        pending_test = next((t for t in active_tests_result.data if t["status"] == "pending"), None)
        if not pending_test:
            return self.create_error_response("No pending tests found")
        
        # Format interactive confirmation message
        interactive_message = f"""🎯 **Test Ready for Confirmation**

**Pending test for {pending_test['url']}**

{confirmation_message}

**Instructions:**
1. Type "y" or "yes" to confirm and proceed
2. Type "n" or "no" to cancel the test
3. Use `confirm_test` tool with your response

⚠️ **This requires your explicit response - the test will NOT run automatically**"""
        
        return self.create_success_response(interactive_message)
    
    async def _handle_check_confirmation_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle confirmation state check."""
        # Get active tests
        active_tests_result = await self.k6_service.list_active_tests()
        if not active_tests_result.success:
            return self.create_error_response("Failed to get active tests")
        
        active_tests = active_tests_result.data
        pending_tests = [t for t in active_tests if t["status"] == "pending"]
        confirmed_tests = [t for t in active_tests if t["status"] == "confirmed"]
        running_tests = [t for t in active_tests if t["status"] == "running"]
        
        state_report = f"""🔍 **Confirmation State Debug Report**

**Active Tests:**
• Pending Tests: {len(pending_tests)}
• Confirmed Tests: {len(confirmed_tests)}
• Running Tests: {len(running_tests)}

**Ready for Execution:**
• Ready: {'Yes' if confirmed_tests else 'No'}

**Next Steps:**
{f'• Use execute_confirmed_test to run the confirmed test' if confirmed_tests else '• No confirmed tests - use confirm_test first'}"""
        
        return self.create_success_response(state_report)
    
    async def _handle_get_test_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test status retrieval."""
        test_id = arguments.get("test_id")
        if not test_id:
            return self.create_error_response("test_id is required")
        
        result = await self.k6_service.get_test_status(test_id)
        
        if result.success:
            status_message = f"Test {test_id} status: {result.data.value}"
            return self.create_success_response(status_message)
        else:
            return self.create_error_response(result.error_message)
    
    async def _handle_cancel_test(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test cancellation."""
        test_id = arguments.get("test_id")
        if not test_id:
            return self.create_error_response("test_id is required")
        
        result = await self.k6_service.cancel_test(test_id)
        
        if result.success:
            return self.create_success_response(result.data)
        else:
            return self.create_error_response(result.error_message)
    
    async def _handle_list_active_tests(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle listing active tests."""
        result = await self.k6_service.list_active_tests()
        
        if result.success:
            if not result.data:
                return self.create_success_response("No active tests found.")
            
            # Format active tests list
            formatted_list = "📋 **Active Tests:**\n\n"
            for test in result.data:
                status_icon = {
                    "pending": "⏳",
                    "confirmed": "✅", 
                    "running": "🏃"
                }.get(test["status"], "❓")
                
                formatted_list += f"{status_icon} **{test['test_id']}** ({test['status']})\n"
                formatted_list += f"  • URL: {test['url']}\n"
                formatted_list += f"  • Method: {test['method']}\n"
                formatted_list += f"  • Virtual Users: {test['virtual_users']}\n\n"
            
            return self.create_success_response(formatted_list)
        else:
            return self.create_error_response(result.error_message)
    
    def _format_test_result(self, test_result) -> str:
        """Format test result for display."""
        if not test_result:
            return "No test result available"
        
        # Determine overall success
        success_icon = "✅" if test_result.is_successful() else "❌"
        duration = test_result.get_duration()
        
        result_text = f"""{success_icon} **K6 Test Execution Completed**

🎯 **Test Information:**
• Test ID: {test_result.test_id}
• Duration: {duration:.2f}s
• Exit Code: {test_result.exit_code}
• Overall Success: {'Yes' if test_result.success else 'No'}

📊 **Performance Metrics:**"""
        
        if test_result.metrics:
            metrics = test_result.metrics
            if metrics.http_reqs:
                result_text += f"\n• Total Requests: {metrics.http_reqs}"
            if metrics.http_req_failed is not None:
                result_text += f"\n• Failed Requests: {metrics.http_req_failed:.2%}"
            if metrics.http_req_duration:
                if 'avg' in metrics.http_req_duration:
                    result_text += f"\n• Average Response Time: {metrics.http_req_duration['avg']:.2f}ms"
                if 'p95' in metrics.http_req_duration:
                    result_text += f"\n• 95th Percentile: {metrics.http_req_duration['p95']:.2f}ms"
        
        # Add error information if test failed
        if not test_result.is_successful():
            result_text += f"\n\n❌ **Error Information:**"
            if test_result.error_message:
                result_text += f"\n• Error: {test_result.error_message}"
            if test_result.stderr:
                result_text += f"\n• Details: {test_result.stderr[:500]}"
        
        # Add file locations
        result_text += f"\n\n📁 **Generated Files:**"
        if test_result.html_report:
            result_text += f"\n• HTML Report: {test_result.html_report}"
        if test_result.results_file:
            result_text += f"\n• Results JSON: {test_result.results_file}"
        if test_result.csv_file:
            result_text += f"\n• CSV Metrics: {test_result.csv_file}"
        
        return result_text