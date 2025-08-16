"""
Workflow Service.

Business logic for multi-request workflow execution and management.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from core.config import AppConfig
from core.base import OperationResult
from core.events import EventType
from domain.models import WorkflowConfig, WorkflowResult, RequestStep, StepResult
from repositories.workflow_repository import WorkflowRepository
from utils.performance import performance_monitor, global_health
from .base_service import EnhancedBaseService

logger = logging.getLogger(__name__)


class WorkflowService(EnhancedBaseService):
    """
    Service for managing multi-request workflow execution.
    
    Provides workflow validation, execution orchestration,
    and result aggregation with proper dependency management.
    """
    
    def __init__(
        self,
        config: AppConfig,
        workflow_repository: WorkflowRepository
    ):
        super().__init__(config)
        self.workflow_repository = workflow_repository
        
        # Workflow execution state
        self.running_workflows: Dict[str, asyncio.Task] = {}
        self.workflow_contexts: Dict[str, Dict[str, Any]] = {}
    
    async def _initialize_impl(self) -> None:
        """Initialize the workflow service."""
        await super()._initialize_impl()
        
        # Register health check
        global_health.register_check("workflow_service", self.health_check_impl)
        
        self.logger.info("Workflow service initialized")
    
    @performance_monitor("workflow_service.validate_workflow")
    async def validate_workflow(self, config: WorkflowConfig) -> OperationResult[List[str]]:
        """
        Validate workflow configuration.
        
        Args:
            config: Workflow configuration to validate
            
        Returns:
            Operation result with validation errors (empty list if valid)
        """
        return await self.safe_execute(self._validate_workflow_internal, config)
    
    @performance_monitor("workflow_service.create_workflow")
    async def create_workflow(self, config: WorkflowConfig) -> OperationResult[str]:
        """
        Create and store workflow configuration.
        
        Args:
            config: Workflow configuration
            
        Returns:
            Operation result with workflow ID
        """
        return await self.execute_with_tracking(
            "create_workflow",
            lambda: self._create_workflow_internal(config),
            workflow_name=config.workflow_name
        )
    
    @performance_monitor("workflow_service.execute_workflow")
    async def execute_workflow(self, workflow_id: str) -> OperationResult[WorkflowResult]:
        """
        Execute a workflow.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Operation result with workflow execution results
        """
        if workflow_id in self.running_workflows:
            return self.create_error_result(
                f"Workflow {workflow_id} is already running",
                "WORKFLOW_ALREADY_RUNNING"
            )
        
        return await self.execute_with_tracking(
            "execute_workflow",
            lambda: self._execute_workflow_internal(workflow_id),
            workflow_id=workflow_id
        )
    
    async def get_workflow_status(self, workflow_id: str) -> OperationResult[str]:
        """Get workflow execution status."""
        if workflow_id in self.running_workflows:
            task = self.running_workflows[workflow_id]
            if task.done():
                return self.create_success_result("completed")
            else:
                return self.create_success_result("running")
        
        # Check if workflow exists in repository
        workflow = await self.workflow_repository.get_by_id(workflow_id)
        if workflow:
            return self.create_success_result("not_started")
        else:
            return self.create_error_result(f"Workflow {workflow_id} not found", "NOT_FOUND")
    
    async def cancel_workflow(self, workflow_id: str) -> OperationResult[str]:
        """Cancel a running workflow."""
        if workflow_id not in self.running_workflows:
            return self.create_error_result(
                f"No running workflow found with ID: {workflow_id}",
                "WORKFLOW_NOT_RUNNING"
            )
        
        task = self.running_workflows.pop(workflow_id)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Clean up context
        self.workflow_contexts.pop(workflow_id, None)
        
        await self.publish_event(EventType.WORKFLOW_FAILED, {
            "workflow_id": workflow_id,
            "cancelled": True
        })
        
        return self.create_success_result(f"Workflow {workflow_id} cancelled")
    
    async def list_active_workflows(self) -> OperationResult[List[Dict[str, Any]]]:
        """List all active workflows."""
        active_workflows = []
        
        for workflow_id, task in self.running_workflows.items():
            workflow = await self.workflow_repository.get_by_id(workflow_id)
            if workflow:
                active_workflows.append({
                    "workflow_id": workflow_id,
                    "workflow_name": workflow.workflow_name,
                    "status": "completed" if task.done() else "running",
                    "step_count": len(workflow.steps),
                    "virtual_users": workflow.virtual_users
                })
        
        return self.create_success_result(active_workflows)
    
    # Private methods
    
    async def _validate_workflow_internal(self, config: WorkflowConfig) -> List[str]:
        """Internal workflow validation logic."""
        errors = []
        
        # Basic validation
        if not config.workflow_name:
            errors.append("Workflow name is required")
        
        if not config.steps:
            errors.append("At least one step is required")
        
        # Step validation
        step_ids = set()
        for step in config.steps:
            # Check for duplicate step IDs
            if step.step_id in step_ids:
                errors.append(f"Duplicate step ID: {step.step_id}")
            step_ids.add(step.step_id)
            
            # Validate step configuration
            step_errors = self._validate_step(step)
            errors.extend(step_errors)
        
        # Dependency validation
        dependency_errors = config.validate_dependency_cycles()
        errors.extend(dependency_errors)
        
        # Check that all dependencies reference existing steps
        for step in config.steps:
            if step.depends_on:
                for dep in step.depends_on:
                    if dep not in step_ids:
                        errors.append(f"Step '{step.step_id}' depends on non-existent step '{dep}'")
        
        return errors
    
    def _validate_step(self, step: RequestStep) -> List[str]:
        """Validate individual step configuration."""
        errors = []
        
        if not step.step_id:
            errors.append("Step ID is required")
        
        if not step.url:
            errors.append(f"URL is required for step '{step.step_id}'")
        elif not step.url.startswith(("http://", "https://", "{{")):
            errors.append(f"Invalid URL format for step '{step.step_id}': {step.url}")
        
        if step.extract_variables:
            for var_name, json_path in step.extract_variables.items():
                if not json_path.startswith("$"):
                    errors.append(f"Invalid JSON path '{json_path}' for variable '{var_name}' in step '{step.step_id}'")
        
        return errors
    
    async def _create_workflow_internal(self, config: WorkflowConfig) -> str:
        """Internal workflow creation logic."""
        # Validate workflow first
        validation_errors = await self._validate_workflow_internal(config)
        if validation_errors:
            raise ValueError(f"Workflow validation failed: {'; '.join(validation_errors)}")
        
        # Generate workflow ID
        workflow_id = self._generate_workflow_id()
        
        # Store workflow
        result = await self.workflow_repository.create_with_id(workflow_id, config)
        if not result.success:
            raise Exception(f"Failed to store workflow: {result.error_message}")
        
        await self.publish_event(EventType.WORKFLOW_STARTED, {
            "workflow_id": workflow_id,
            "workflow_name": config.workflow_name,
            "step_count": len(config.steps)
        })
        
        return workflow_id
    
    async def _execute_workflow_internal(self, workflow_id: str) -> WorkflowResult:
        """Internal workflow execution logic."""
        # Load workflow configuration
        config = await self.workflow_repository.get_by_id(workflow_id)
        if not config:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        # Initialize workflow context
        self.workflow_contexts[workflow_id] = {
            "variables": {},
            "cookies": {},
            "current_step": 0
        }
        
        # Create workflow result
        workflow_result = WorkflowResult(
            workflow_id=workflow_id,
            config=config.model_dump(),
            start_time=datetime.utcnow(),
            success=True,
            step_results=[]
        )
        
        try:
            # Create execution task
            execution_task = asyncio.create_task(
                self._execute_workflow_steps(workflow_id, config, workflow_result)
            )
            self.running_workflows[workflow_id] = execution_task
            
            # Execute workflow
            await execution_task
            
            # Finalize result
            workflow_result.end_time = datetime.utcnow()
            workflow_result.success = all(step.success for step in workflow_result.step_results)
            
            # Calculate metrics
            workflow_result.total_requests = len(workflow_result.step_results)
            workflow_result.successful_requests = sum(1 for step in workflow_result.step_results if step.success)
            workflow_result.failed_requests = workflow_result.total_requests - workflow_result.successful_requests
            
            # Set global variables
            context = self.workflow_contexts.get(workflow_id, {})
            workflow_result.global_variables = context.get("variables", {})
            
            await self.publish_event(EventType.WORKFLOW_COMPLETED, {
                "workflow_id": workflow_id,
                "success": workflow_result.success,
                "duration_seconds": workflow_result.get_duration(),
                "total_requests": workflow_result.total_requests,
                "success_rate": workflow_result.get_success_rate()
            })
            
            return workflow_result
            
        except Exception as e:
            workflow_result.end_time = datetime.utcnow()
            workflow_result.success = False
            workflow_result.error_message = str(e)
            
            await self.publish_event(EventType.WORKFLOW_FAILED, {
                "workflow_id": workflow_id,
                "error": str(e),
                "duration_seconds": workflow_result.get_duration()
            })
            
            raise
        
        finally:
            # Clean up
            self.running_workflows.pop(workflow_id, None)
            self.workflow_contexts.pop(workflow_id, None)
    
    async def _execute_workflow_steps(
        self,
        workflow_id: str,
        config: WorkflowConfig,
        workflow_result: WorkflowResult
    ) -> None:
        """Execute all workflow steps in dependency order."""
        executed_steps = set()
        pending_steps = {step.step_id: step for step in config.steps}
        
        while pending_steps:
            # Find steps that can be executed (all dependencies satisfied)
            ready_steps = []
            for step_id, step in pending_steps.items():
                if not step.depends_on or all(dep in executed_steps for dep in step.depends_on):
                    ready_steps.append(step)
            
            if not ready_steps:
                raise Exception("Circular dependency detected or unresolvable dependencies")
            
            # Execute ready steps
            for step in ready_steps:
                try:
                    step_result = await self._execute_step(workflow_id, step, config)
                    workflow_result.step_results.append(step_result)
                    
                    if not step_result.success and config.stop_on_failure:
                        raise Exception(f"Step '{step.step_id}' failed: {step_result.error_message}")
                    
                    executed_steps.add(step.step_id)
                    pending_steps.pop(step.step_id)
                    
                except Exception as e:
                    step_result = StepResult(
                        step_id=step.step_id,
                        success=False,
                        start_time=datetime.utcnow(),
                        end_time=datetime.utcnow(),
                        error_message=str(e)
                    )
                    workflow_result.step_results.append(step_result)
                    
                    if config.stop_on_failure:
                        raise
                    
                    executed_steps.add(step.step_id)
                    pending_steps.pop(step.step_id)
    
    async def _execute_step(
        self,
        workflow_id: str,
        step: RequestStep,
        config: WorkflowConfig
    ) -> StepResult:
        """Execute a single workflow step."""
        step_result = StepResult(
            step_id=step.step_id,
            success=False,
            start_time=datetime.utcnow()
        )
        
        try:
            context = self.workflow_contexts[workflow_id]
            
            # Resolve template variables in URL and payload
            url = self._resolve_template_variables(step.url, context["variables"])
            
            # Prepare headers
            headers = {}
            if config.global_headers:
                headers.update(config.global_headers)
            if step.headers:
                resolved_headers = {
                    key: self._resolve_template_variables(value, context["variables"])
                    for key, value in step.headers.items()
                }
                headers.update(resolved_headers)
            
            # Prepare payload
            payload = None
            if step.payload:
                payload = self._resolve_template_payload(step.payload, context["variables"])
            
            # Execute HTTP request (simplified - would use aiohttp in real implementation)
            # For now, simulate request execution
            await asyncio.sleep(0.1)  # Simulate network delay
            
            # Simulate successful response
            step_result.status_code = 200
            step_result.response_body = json.dumps({"status": "success", "data": {"id": "123"}})
            step_result.response_headers = {"content-type": "application/json"}
            step_result.success = True
            
            # Extract variables from response
            if step.extract_variables and step_result.response_body:
                try:
                    response_data = json.loads(step_result.response_body)
                    extracted_vars = {}
                    
                    for var_name, json_path in step.extract_variables.items():
                        value = self._extract_json_path(response_data, json_path)
                        if value is not None:
                            extracted_vars[var_name] = value
                            context["variables"][var_name] = value
                    
                    step_result.extracted_variables = extracted_vars
                    
                except Exception as e:
                    self.logger.warning(f"Failed to extract variables from step {step.step_id}: {e}")
            
        except Exception as e:
            step_result.success = False
            step_result.error_message = str(e)
        
        finally:
            step_result.end_time = datetime.utcnow()
        
        return step_result
    
    def _resolve_template_variables(self, template: str, variables: Dict[str, Any]) -> str:
        """Resolve template variables in a string."""
        result = template
        for var_name, value in variables.items():
            placeholder = f"{{{{{var_name}}}}}"
            result = result.replace(placeholder, str(value))
        return result
    
    def _resolve_template_payload(self, payload: Dict[str, Any], variables: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve template variables in payload."""
        if isinstance(payload, dict):
            return {
                key: self._resolve_template_payload(value, variables)
                for key, value in payload.items()
            }
        elif isinstance(payload, list):
            return [self._resolve_template_payload(item, variables) for item in payload]
        elif isinstance(payload, str):
            return self._resolve_template_variables(payload, variables)
        else:
            return payload
    
    def _extract_json_path(self, data: Any, json_path: str) -> Any:
        """Extract value from JSON data using JSON path."""
        # Simplified JSON path extraction - would use jsonpath library in real implementation
        if json_path.startswith("$."):
            path_parts = json_path[2:].split(".")
            current = data
            
            for part in path_parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            
            return current
        
        return None
    
    def _generate_workflow_id(self) -> str:
        """Generate unique workflow ID."""
        import uuid
        timestamp = int(datetime.utcnow().timestamp())
        return f"workflow_{timestamp}_{uuid.uuid4().hex[:8]}"
    
    async def health_check_impl(self) -> Dict[str, Any]:
        """Implementation-specific health check."""
        active_workflows = len(self.running_workflows)
        
        healthy = active_workflows <= 5
        status = "healthy" if healthy else "degraded"
        message = f"Active workflows: {active_workflows}"
        
        if not healthy:
            message += " (high load)"
        
        return {
            "healthy": healthy,
            "component": "workflow_service",
            "status": status,
            "message": message,
            "active_workflows": active_workflows,
            "workflow_contexts": len(self.workflow_contexts),
            "warning": "High workflow load" if not healthy else None
        }