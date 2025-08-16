"""
Workflow Handler.

Handles MCP tool calls for workflow operations including creation,
execution, and result retrieval.
"""

import logging
from typing import Any, Dict

from core.base import BaseHandler, OperationResult
from core.config import AppConfig
from services.workflow_service import WorkflowService
from domain.models import WorkflowConfig

logger = logging.getLogger(__name__)


class WorkflowHandler(BaseHandler):
    """
    Handler for workflow-related MCP tool calls.
    
    Processes requests for workflow creation, execution, validation,
    and status management with proper validation and error handling.
    """
    
    def __init__(self, config: AppConfig, workflow_service: WorkflowService):
        super().__init__(config)
        self.workflow_service = workflow_service
    
    async def handle(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow tool calls."""
        
        try:
            if name == "run_k6_workflow_test":
                return await self._handle_execute_workflow(arguments)
            
            elif name == "create_test_workflow":
                return await self._handle_create_workflow(arguments)
            
            elif name == "validate_request_chain":
                return await self._handle_validate_workflow(arguments)
            
            elif name == "get_workflow_results":
                return await self._handle_get_workflow_results(arguments)
            
            elif name == "list_workflow_templates":
                return await self._handle_list_workflow_templates(arguments)
            
            elif name == "get_workflow_status":
                return await self._handle_get_workflow_status(arguments)
            
            elif name == "cancel_workflow":
                return await self._handle_cancel_workflow(arguments)
            
            elif name == "list_active_workflows":
                return await self._handle_list_active_workflows(arguments)
            
            else:
                return self.create_error_response(f"Unknown workflow tool: {name}")
                
        except Exception as e:
            self.logger.error(f"Error handling workflow {name}: {e}", exc_info=True)
            return self.create_error_response(f"Workflow handler error: {str(e)}")
    
    async def _handle_execute_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow execution."""
        operation_id = self.log_operation_start("execute_workflow")
        
        # 🚨 SAFETY LOG - This should only happen on explicit user request
        self.logger.warning("🚨 SAFETY ALERT: run_k6_workflow_test tool was called - this should ONLY happen on explicit user request")
        self.logger.warning("🚨 If this was called autonomously by AI, this is a SAFETY VIOLATION")
        
        try:
            # Parse workflow configuration
            workflow_config = WorkflowConfig(**arguments)
            
            # Create and execute workflow
            create_result = await self.workflow_service.create_workflow(workflow_config)
            if not create_result.success:
                return self.create_error_response(f"Failed to create workflow: {create_result.error_message}")
            
            workflow_id = create_result.data
            
            # Execute workflow
            result = await self.workflow_service.execute_workflow(workflow_id)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                formatted_result = self._format_workflow_result(result.data)
                return self.create_success_response(formatted_result)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Workflow execution failed: {str(e)}")
    
    async def _handle_create_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow creation."""
        operation_id = self.log_operation_start("create_workflow")
        
        try:
            workflow_name = arguments.get("workflow_name")
            template_type = arguments.get("template_type", "custom")
            
            if not workflow_name:
                return self.create_error_response("workflow_name is required")
            
            # Generate workflow based on template type
            if template_type == "auth":
                workflow_config = self._create_auth_workflow_template(workflow_name, arguments)
            elif template_type == "crud":
                workflow_config = self._create_crud_workflow_template(workflow_name, arguments)
            elif template_type == "custom":
                workflow_config = WorkflowConfig(**arguments)
            else:
                return self.create_error_response(f"Unknown template type: {template_type}")
            
            # Create workflow
            result = await self.workflow_service.create_workflow(workflow_config)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                workflow_summary = f"""✅ **Workflow Created Successfully**

🎯 **Workflow Information:**
• Workflow ID: {result.data}
• Name: {workflow_config.workflow_name}
• Template Type: {template_type}
• Steps: {len(workflow_config.steps)}
• Virtual Users: {workflow_config.virtual_users}
• Duration: {workflow_config.duration or 'Not specified'}

📋 **Workflow Steps:**"""
                
                for i, step in enumerate(workflow_config.steps, 1):
                    workflow_summary += f"\n{i}. **{step.name}** ({step.method} {step.url})"
                    if step.depends_on:
                        workflow_summary += f" - Depends on: {', '.join(step.depends_on)}"
                
                workflow_summary += f"""

⚠️ **Ready for Execution:**
Use 'run_k6_workflow_test' with the workflow configuration to execute this workflow."""
                
                return self.create_success_response(workflow_summary)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Workflow creation failed: {str(e)}")
    
    async def _handle_validate_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow validation."""
        try:
            # Parse workflow configuration
            workflow_config = WorkflowConfig(**arguments)
            
            # Validate workflow
            result = await self.workflow_service.validate_workflow(workflow_config)
            
            if result.success:
                validation_errors = result.data
                
                if not validation_errors:
                    return self.create_success_response("""✅ **Workflow Validation Successful**

🎯 **Validation Results:**
• No validation errors found
• Workflow structure is valid
• All dependencies are properly defined
• No circular dependencies detected

✅ **Ready for Execution:**
This workflow is ready to be executed.""")
                else:
                    error_summary = "❌ **Workflow Validation Failed**\n\n**Validation Errors:**\n"
                    for i, error in enumerate(validation_errors, 1):
                        error_summary += f"{i}. {error}\n"
                    
                    error_summary += "\n⚠️ **Please fix these errors before executing the workflow.**"
                    return self.create_error_response(error_summary)
            else:
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            return self.create_error_response(f"Workflow validation failed: {str(e)}")
    
    async def _handle_get_workflow_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow results retrieval."""
        workflow_id = arguments.get("workflow_id")
        if not workflow_id:
            return self.create_error_response("workflow_id is required")
        
        try:
            # Get results from result service (assuming it handles workflow results)
            # This would need to be implemented in result service
            return self.create_success_response(f"Workflow results for {workflow_id} (implementation pending)")
            
        except Exception as e:
            return self.create_error_response(f"Failed to get workflow results: {str(e)}")
    
    async def _handle_list_workflow_templates(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow template listing."""
        templates_info = """📋 **Available Workflow Templates**

🔐 **Authentication Workflow (auth)**
• OAuth token acquisition
• API authentication flow
• Token refresh handling
• Perfect for testing auth endpoints

🔄 **CRUD Operations Workflow (crud)**
• Create, Read, Update, Delete sequence
• User management operations
• Resource lifecycle testing
• Data consistency validation

🛠️ **Custom Workflow (custom)**
• Define your own step sequence
• Custom request chains
• Variable extraction and chaining
• Conditional execution

**Usage Examples:**

```json
{
  "workflow_name": "user_auth_flow",
  "template_type": "auth",
  "base_url": "https://api.example.com",
  "auth_endpoint": "/oauth/token",
  "protected_endpoint": "/protected/resource"
}
```

```json
{
  "workflow_name": "user_crud_test",
  "template_type": "crud",
  "base_url": "https://api.example.com",
  "resource_name": "users"
}
```"""
        
        return self.create_success_response(templates_info)
    
    async def _handle_get_workflow_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow status retrieval."""
        workflow_id = arguments.get("workflow_id")
        if not workflow_id:
            return self.create_error_response("workflow_id is required")
        
        result = await self.workflow_service.get_workflow_status(workflow_id)
        
        if result.success:
            status = result.data
            status_message = f"🔍 **Workflow Status**\n\nWorkflow ID: {workflow_id}\nStatus: {status}"
            return self.create_success_response(status_message)
        else:
            return self.create_error_response(result.error_message)
    
    async def _handle_cancel_workflow(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow cancellation."""
        workflow_id = arguments.get("workflow_id")
        if not workflow_id:
            return self.create_error_response("workflow_id is required")
        
        result = await self.workflow_service.cancel_workflow(workflow_id)
        
        if result.success:
            return self.create_success_response(result.data)
        else:
            return self.create_error_response(result.error_message)
    
    async def _handle_list_active_workflows(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle listing active workflows."""
        result = await self.workflow_service.list_active_workflows()
        
        if result.success:
            if not result.data:
                return self.create_success_response("No active workflows found.")
            
            # Format active workflows list
            formatted_list = "📋 **Active Workflows:**\n\n"
            for workflow in result.data:
                status_icon = {
                    "not_started": "⏸️",
                    "running": "🏃",
                    "completed": "✅"
                }.get(workflow["status"], "❓")
                
                formatted_list += f"{status_icon} **{workflow['workflow_name']}** ({workflow['status']})\n"
                formatted_list += f"  • Workflow ID: {workflow['workflow_id']}\n"
                formatted_list += f"  • Steps: {workflow['step_count']}\n"
                formatted_list += f"  • Virtual Users: {workflow['virtual_users']}\n\n"
            
            return self.create_success_response(formatted_list)
        else:
            return self.create_error_response(result.error_message)
    
    def _create_auth_workflow_template(self, workflow_name: str, arguments: Dict[str, Any]) -> WorkflowConfig:
        """Create authentication workflow template."""
        from domain.models import RequestStep, HttpMethod
        
        base_url = arguments.get("base_url", "https://api.example.com")
        auth_endpoint = arguments.get("auth_endpoint", "/oauth/token")
        protected_endpoint = arguments.get("protected_endpoint", "/protected/resource")
        
        steps = [
            RequestStep(
                step_id="authenticate",
                name="Authenticate User",
                url=f"{base_url}{auth_endpoint}",
                method=HttpMethod.POST,
                payload={
                    "grant_type": "password",
                    "username": arguments.get("username", "test@example.com"),
                    "password": arguments.get("password", "password123"),
                    "client_id": arguments.get("client_id", "test_client")
                },
                extract_variables={
                    "access_token": "$.access_token",
                    "refresh_token": "$.refresh_token"
                }
            ),
            RequestStep(
                step_id="access_protected",
                name="Access Protected Resource",
                url=f"{base_url}{protected_endpoint}",
                method=HttpMethod.GET,
                headers={
                    "Authorization": "Bearer {{access_token}}"
                },
                depends_on=["authenticate"],
                condition="{{response.authenticate.status}} == 200"
            )
        ]
        
        return WorkflowConfig(
            workflow_name=workflow_name,
            description="OAuth authentication workflow",
            steps=steps,
            virtual_users=arguments.get("virtual_users", 1),
            duration=arguments.get("duration", "60s")
        )
    
    def _create_crud_workflow_template(self, workflow_name: str, arguments: Dict[str, Any]) -> WorkflowConfig:
        """Create CRUD workflow template."""
        from domain.models import RequestStep, HttpMethod
        
        base_url = arguments.get("base_url", "https://api.example.com")
        resource_name = arguments.get("resource_name", "users")
        
        steps = [
            RequestStep(
                step_id="create_resource",
                name=f"Create {resource_name}",
                url=f"{base_url}/{resource_name}",
                method=HttpMethod.POST,
                payload={
                    "name": f"Test {resource_name} {{{{random_int}}}}",
                    "email": f"test{{{{random_int}}}}@example.com"
                },
                extract_variables={
                    "resource_id": "$.id"
                }
            ),
            RequestStep(
                step_id="read_resource",
                name=f"Read {resource_name}",
                url=f"{base_url}/{resource_name}/{{{{resource_id}}}}",
                method=HttpMethod.GET,
                depends_on=["create_resource"],
                condition="{{response.create_resource.status}} == 201"
            ),
            RequestStep(
                step_id="update_resource",
                name=f"Update {resource_name}",
                url=f"{base_url}/{resource_name}/{{{{resource_id}}}}",
                method=HttpMethod.PUT,
                payload={
                    "name": f"Updated {resource_name} {{{{random_int}}}}"
                },
                depends_on=["read_resource"],
                condition="{{response.read_resource.status}} == 200"
            ),
            RequestStep(
                step_id="delete_resource",
                name=f"Delete {resource_name}",
                url=f"{base_url}/{resource_name}/{{{{resource_id}}}}",
                method=HttpMethod.DELETE,
                depends_on=["update_resource"],
                condition="{{response.update_resource.status}} == 200"
            )
        ]
        
        return WorkflowConfig(
            workflow_name=workflow_name,
            description=f"CRUD operations workflow for {resource_name}",
            steps=steps,
            virtual_users=arguments.get("virtual_users", 1),
            duration=arguments.get("duration", "60s")
        )
    
    def _format_workflow_result(self, workflow_result) -> str:
        """Format workflow result for display."""
        if not workflow_result:
            return "No workflow result available"
        
        # Determine overall success
        success_icon = "✅" if workflow_result.success else "❌"
        duration = workflow_result.get_duration()
        step_summary = workflow_result.get_step_summary()
        
        result_text = f"""{success_icon} **Workflow Execution Completed**

🎯 **Workflow Information:**
• Workflow ID: {workflow_result.workflow_id}
• Duration: {duration:.2f}s
• Overall Success: {'Yes' if workflow_result.success else 'No'}
• Success Rate: {workflow_result.get_success_rate():.1%}

📊 **Execution Summary:**
• Total Steps: {step_summary['total_steps']}
• Successful Steps: {step_summary['successful_steps']}
• Failed Steps: {step_summary['failed_steps']}
• Total Requests: {workflow_result.total_requests}
• Successful Requests: {workflow_result.successful_requests}
• Failed Requests: {workflow_result.failed_requests}

🔗 **Step Results:**"""
        
        for step in workflow_result.step_results:
            step_icon = "✅" if step.success else "❌"
            step_duration = step.get_duration() or 0
            
            result_text += f"\n{step_icon} **{step.step_id}** ({step_duration:.2f}s)"
            if step.status_code:
                result_text += f" - HTTP {step.status_code}"
            if not step.success and step.error_message:
                result_text += f"\n   Error: {step.error_message}"
            if step.extracted_variables:
                result_text += f"\n   Variables: {list(step.extracted_variables.keys())}"
        
        # Add global variables if any
        if workflow_result.global_variables:
            result_text += f"\n\n🔧 **Global Variables:**"
            for var_name, var_value in workflow_result.global_variables.items():
                result_text += f"\n• {var_name}: {var_value}"
        
        # Add error information if workflow failed
        if not workflow_result.success and workflow_result.error_message:
            result_text += f"\n\n❌ **Error Information:**\n• {workflow_result.error_message}"
        
        return result_text