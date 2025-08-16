"""
Workflow Manager for K6 Multi-Request Testing.

This module manages the execution of multi-step K6 workflows, handling
dependencies, validation, and script generation for complex request sequences.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from error_handler import (
    ErrorHandler, ErrorContext, ErrorCategory, ErrorSeverity,
    EnhancedError, ValidationError, with_error_handling, 
    graceful_degradation, RetryConfig
)
from multi_request_models import (
    K6WorkflowConfig, 
    RequestStep, 
    K6WorkflowResult, 
    StepResult,
    WorkflowTemplate,
    get_workflow_template,
    create_workflow_from_template,
    # Backward compatibility
    K6MultiRequestConfig,
    WorkflowResult
)
from template_engine import TemplateEngine
from chain_processor import ChainProcessor
from security_utils import run_sandboxed_command

logger = logging.getLogger(__name__)


class WorkflowValidationError(Exception):
    """Exception raised when workflow validation fails."""
    pass


class WorkflowExecutionError(Exception):
    """Exception raised when workflow execution fails."""
    pass


class WorkflowManager:
    """
    Manages multi-request K6 workflows including validation, dependency resolution,
    and script generation with enhanced error handling.
    """
    
    def __init__(self, results_dir: Path, templates_dir: Path):
        self.results_dir = results_dir
        self.templates_dir = templates_dir
        self.template_engine = TemplateEngine()
        self.chain_processor = ChainProcessor()
        self.error_handler = ErrorHandler()
        
        # Workflow execution state
        self.pending_workflow = None
        self.confirmed_workflow = None
        self.workflow_results = {}
    
    async def validate_workflow(self, config: K6WorkflowConfig) -> List[str]:
        """
        Comprehensive validation of workflow configuration with enhanced error handling.
        
        Returns:
            List of validation errors (empty list if valid)
        """
        errors = []
        
        context = ErrorContext(
            operation="validate_workflow",
            component="workflow_manager",
            user_request=f"workflow: {config.workflow_name}"
        )
        
        async def validation_operation():
            nonlocal errors
            
            try:
                # Basic model validation is handled by Pydantic
                # Check for circular dependencies
                cycle_errors = config.validate_dependency_cycles()
                errors.extend(cycle_errors)
                
                # Validate step configurations
                step_errors = await self._validate_steps(config.steps)
                errors.extend(step_errors)
                
                # Validate template variables in URLs and payloads
                template_errors = await self._validate_templates(config)
                errors.extend(template_errors)
                
                # Validate execution parameters
                execution_errors = self._validate_execution_parameters(config)
                errors.extend(execution_errors)
                
                return errors
                
            except Exception as e:
                logger.error(f"Unexpected error during workflow validation: {str(e)}")
                raise ValidationError(
                    f"Workflow validation failed: {str(e)}",
                    context=context,
                    recovery_suggestions=[
                        "Check workflow configuration format",
                        "Verify all required fields are present",
                        "Review step dependencies and structure"
                    ],
                    original_error=e
                )
        
        try:
            result = await self.error_handler.handle_with_retry(
                validation_operation, context, RetryConfig(max_attempts=1)
            )
            
            if result.success:
                return errors
            else:
                # If validation operation failed, return error list
                return [f"Validation failed: {result.message}"]
                
        except Exception as e:
            logger.error(f"Error in workflow validation: {str(e)}")
            return [f"Validation error: {str(e)}"]
    
    async def _validate_steps(self, steps: List[RequestStep]) -> List[str]:
        """Validate individual step configurations."""
        errors = []
        
        for step in steps:
            # Validate URL format
            if not self._is_valid_url_template(step.url):
                errors.append(f"Step '{step.step_id}': Invalid URL format '{step.url}'")
            
            # Validate extraction paths
            if step.extract_variables:
                for var_name, path in step.extract_variables.items():
                    if not self._is_valid_extraction_path(path):
                        errors.append(f"Step '{step.step_id}': Invalid extraction path '{path}' for variable '{var_name}'")
            
            # Validate condition syntax
            if step.condition:
                if not self._is_valid_condition(step.condition):
                    errors.append(f"Step '{step.step_id}': Invalid condition syntax '{step.condition}'")
            
            # Validate payload structure
            if step.payload and step.method in ['GET', 'HEAD', 'OPTIONS']:
                errors.append(f"Step '{step.step_id}': {step.method} requests should not have payload")
        
        return errors
    
    async def _validate_templates(self, config: K6WorkflowConfig) -> List[str]:
        """Validate template variable references."""
        errors = []
        
        # Collect all template variables used across steps
        used_variables = set()
        defined_variables = set()
        
        # Add built-in variables
        defined_variables.update(['timestamp', 'current_timestamp', 'random_int', 'uuid'])
        
        for i, step in enumerate(config.steps):
            # Collect variables defined by this step
            if step.extract_variables:
                for var_name in step.extract_variables.keys():
                    defined_variables.add(var_name)
                    defined_variables.add(f"response.{step.step_id}.extracted.{var_name}")
            
            # Add response variables for this step
            defined_variables.add(f"response.{step.step_id}.status")
            defined_variables.add(f"response.{step.step_id}.body")
            defined_variables.add(f"response.{step.step_id}.headers")
            
            # Collect variables used by this step
            step_vars = self.template_engine.extract_template_variables(step.url)
            used_variables.update(step_vars)
            
            if step.payload:
                payload_str = json.dumps(step.payload) if isinstance(step.payload, dict) else str(step.payload)
                payload_vars = self.template_engine.extract_template_variables(payload_str)
                used_variables.update(payload_vars)
            
            if step.headers:
                for header_value in step.headers.values():
                    header_vars = self.template_engine.extract_template_variables(header_value)
                    used_variables.update(header_vars)
            
            if step.condition:
                condition_vars = self.template_engine.extract_template_variables(step.condition)
                used_variables.update(condition_vars)
        
        # Check for undefined variables
        undefined_vars = used_variables - defined_variables
        for var in undefined_vars:
            # Skip variables that might be defined by global config or environment
            if not var.startswith('response.') and var not in ['base_url', 'user_email', 'user_password']:
                errors.append(f"Undefined template variable: {{{{ {var} }}}}")
        
        return errors
    
    def _validate_execution_parameters(self, config: K6WorkflowConfig) -> List[str]:
        """Validate execution parameters."""
        errors = []
        
        # Validate duration vs iterations
        if config.iterations is not None and config.duration is not None:
            errors.append("Cannot specify both iterations and duration - choose one")
        
        if config.iterations is None and config.duration is None:
            errors.append("Must specify either iterations or duration")
        
        # Validate load pattern compatibility
        if config.load_pattern in ['ramp_up', 'spike'] and config.iterations is not None:
            errors.append(f"Load pattern '{config.load_pattern}' requires duration, not iterations")
        
        # Validate thresholds format
        if config.thresholds:
            for metric, threshold in config.thresholds.items():
                if not self._is_valid_threshold(threshold):
                    errors.append(f"Invalid threshold format: {metric} = {threshold}")
        
        return errors
    
    def _is_valid_url_template(self, url: str) -> bool:
        """Check if URL template is valid."""
        # Basic URL validation - should start with http/https or be a template
        if url.startswith('{{') or url.startswith('http://') or url.startswith('https://'):
            return True
        return False
    
    def _is_valid_extraction_path(self, path: str) -> bool:
        """Validate JSON path or header extraction syntax."""
        if path.startswith('$.') or path.startswith('headers.') or path.startswith('cookies.'):
            return True
        return False
    
    def _is_valid_condition(self, condition: str) -> bool:
        """Basic validation of condition syntax."""
        # Should contain template variables and comparison operators
        return '{{' in condition and '}}' in condition
    
    def _is_valid_threshold(self, threshold: str) -> bool:
        """Validate K6 threshold syntax."""
        # Basic validation for K6 threshold format
        valid_patterns = ['p(', 'rate<', 'avg<', 'max<', 'min<']
        return any(pattern in threshold for pattern in valid_patterns)
    
    async def preview_workflow_config(self, config: K6WorkflowConfig) -> str:
        """
        Preview what a K6 workflow configuration will look like without preparing it for execution.
        Shows detailed information about the workflow steps, dependencies, and execution plan.
        """
        try:
            # Generate preview information
            preview = f"""🔍 K6 Workflow Test Preview
{'='*60}

📋 Workflow Configuration:
• Name: {config.workflow_name}
• Description: {config.description or 'No description provided'}
• Virtual Users: {config.virtual_users}"""

            # Add execution mode details
            if config.iterations:
                preview += f"\n• Execution Mode: Iterations ({config.iterations} per user)"
                total_requests = len(config.steps) * config.iterations * config.virtual_users
                preview += f"\n• Total Requests: {total_requests} (estimated)"
            else:
                preview += f"\n• Execution Mode: Duration ({config.duration})"
                preview += f"\n• Total Requests: Depends on response times and think time"

            preview += f"\n• Execution Strategy: {config.execution_mode}"
            preview += f"\n• Stop on Failure: {'Yes' if config.stop_on_failure else 'No'}"
            preview += f"\n• Share Cookies: {'Yes' if config.share_cookies else 'No'}"

            # Show workflow steps
            preview += f"\n\n🔗 Workflow Steps ({len(config.steps)} steps):"
            for i, step in enumerate(config.steps, 1):
                preview += f"\n\n  {i}. 📋 {step.name} ({step.step_id})"
                preview += f"\n     • URL: {step.url}"
                preview += f"\n     • Method: {step.method}"
                
                if step.depends_on:
                    preview += f"\n     • Depends on: {', '.join(step.depends_on)}"
                
                if step.condition:
                    preview += f"\n     • Condition: {step.condition}"
                
                if step.extract_variables:
                    var_count = len(step.extract_variables)
                    preview += f"\n     • Extracts: {var_count} variable{'s' if var_count != 1 else ''}"
                    for var_name, path in step.extract_variables.items():
                        preview += f"\n       - {var_name}: {path}"
                
                if step.payload:
                    preview += f"\n     • Payload: {len(str(step.payload))} characters"
                
                if step.on_failure != "stop":
                    preview += f"\n     • On Failure: {step.on_failure}"

            # Show execution order
            try:
                execution_order = config.get_execution_order()
                preview += f"\n\n🚀 Execution Plan:"
                for round_num, step_ids in enumerate(execution_order, 1):
                    if len(step_ids) == 1:
                        step_name = next(s.name for s in config.steps if s.step_id == step_ids[0])
                        preview += f"\n  Round {round_num}: {step_name}"
                    else:
                        step_names = [next(s.name for s in config.steps if s.step_id == sid) for sid in step_ids]
                        preview += f"\n  Round {round_num}: {len(step_ids)} parallel steps"
                        for name in step_names:
                            preview += f"\n    • {name}"
            except Exception as e:
                preview += f"\n\n🚀 Execution Plan: Could not determine order ({str(e)})"

            # Show variable flow
            all_extracts = {}
            all_uses = set()
            for step in config.steps:
                if step.extract_variables:
                    all_extracts[step.step_id] = list(step.extract_variables.keys())
                
                # Look for variable usage in URL, payload, headers
                step_content = f"{step.url} {step.payload} {step.headers} {step.condition}"
                import re
                uses = re.findall(r'\{\{(\w+)\}\}', str(step_content))
                all_uses.update(uses)

            if all_extracts or all_uses:
                preview += f"\n\n🔄 Variable Flow:"
                if all_extracts:
                    preview += f"\n• Variables Extracted:"
                    for step_id, vars in all_extracts.items():
                        step_name = next(s.name for s in config.steps if s.step_id == step_id)
                        preview += f"\n  {step_name}: {', '.join(vars)}"
                
                if all_uses:
                    preview += f"\n• Variables Used: {', '.join(sorted(all_uses))}"

            # Show global configuration
            if config.global_headers or config.global_auth or config.base_url:
                preview += f"\n\n🌐 Global Configuration:"
                if config.base_url:
                    preview += f"\n• Base URL: {config.base_url}"
                if config.global_headers:
                    preview += f"\n• Global Headers: {len(config.global_headers)} headers"
                if config.global_auth:
                    preview += f"\n• Global Auth: {config.global_auth.get('type', 'Configured')}"

            # Add output information
            preview += f"\n\n📊 Expected Output:"
            preview += f"\n• JSON Results: Detailed workflow metrics and step results"
            preview += f"\n• Step-by-step Results: Individual step success/failure status"
            preview += f"\n• Variable Extraction Log: All extracted variables and values"
            preview += f"\n• Test ID Format: k6_workflow_<timestamp>"

            preview += f"\n\n🎯 Next Steps:"
            preview += f"\n• Use 'run_k6_workflow_test' to prepare this workflow for execution"
            preview += f"\n• The workflow will require confirmation before running"
            preview += f"\n• Results will be saved to the reports/ directory"
            preview += f"\n• Failed steps will be clearly marked in the results"

            return preview

        except Exception as e:
            logger.error(f"Error generating workflow preview: {str(e)}")
            return f"Error generating workflow preview: {str(e)}"

    async def preview_template(self, template_name: str, parameters: Dict[str, Any]) -> str:
        """Preview what a workflow template will look like when instantiated with given parameters."""
        try:
            from multi_request_models import get_workflow_template
            
            template = get_workflow_template(template_name)
            if not template:
                return f"❌ Template '{template_name}' not found. Available templates: {', '.join(self.list_available_templates())}"

            preview = f"""🔍 Workflow Template Preview
{'='*50}

📋 Template Information:
• Name: {template.template_name}
• Category: {template.category}
• Description: {template.description}

🔧 Required Parameters:"""
            
            for param_name, param_config in template.parameters.items():
                required = "Required" if param_config.get("required", False) else "Optional"
                param_type = param_config.get("type", "string")
                description = param_config.get("description", "No description")
                provided = "✅ Provided" if param_name in parameters else "❌ Missing"
                
                preview += f"\n• {param_name} ({param_type}, {required}): {description} - {provided}"
                if param_name in parameters:
                    preview += f"\n  Value: {parameters[param_name]}"

            # Show what the generated workflow would look like
            try:
                base_config = template.base_config
                preview += f"\n\n🚀 Generated Workflow Preview:"
                preview += f"\n• Workflow Name: {base_config.workflow_name}"
                preview += f"\n• Steps: {len(base_config.steps)}"
                preview += f"\n• Virtual Users: {base_config.virtual_users}"
                
                if base_config.iterations:
                    preview += f"\n• Iterations: {base_config.iterations}"
                else:
                    preview += f"\n• Duration: {base_config.duration}"

                preview += f"\n\n📋 Template Steps:"
                for i, step in enumerate(base_config.steps, 1):
                    preview += f"\n  {i}. {step.name} ({step.method} {step.url})"
                    if step.extract_variables:
                        preview += f"\n     Extracts: {', '.join(step.extract_variables.keys())}"

                # Check for missing required parameters
                missing_required = []
                for param_name, param_config in template.parameters.items():
                    if param_config.get("required", False) and param_name not in parameters:
                        missing_required.append(param_name)

                if missing_required:
                    preview += f"\n\n⚠️  Missing Required Parameters: {', '.join(missing_required)}"
                    preview += f"\n   Please provide these parameters to use this template."
                else:
                    preview += f"\n\n✅ All required parameters provided. Template is ready to use."

            except Exception as e:
                preview += f"\n\n❌ Error generating template preview: {str(e)}"

            preview += f"\n\n🎯 Next Steps:"
            preview += f"\n• Use 'create_test_workflow' with template_name='{template_name}' to create this workflow"
            preview += f"\n• Provide all required parameters"
            preview += f"\n• The workflow can then be executed with 'run_k6_workflow_test'"

            return preview

        except Exception as e:
            logger.error(f"Error generating template preview: {str(e)}")
            return f"Error generating template preview: {str(e)}"

    def list_available_templates(self) -> List[str]:
        """Get list of available workflow template names."""
        from multi_request_models import list_workflow_templates
        return list_workflow_templates()
    
    async def prepare_workflow(self, config: K6WorkflowConfig) -> str:
        """
        Prepare workflow for execution and return confirmation prompt.
        Similar to prepare_test but for multi-request workflows.
        """
        test_id = f"k6_workflow_{int(time.time())}"
        timestamp = datetime.now().isoformat()
        
        try:
            # Validate workflow
            validation_errors = await self.validate_workflow(config)
            if validation_errors:
                error_msg = "Workflow validation failed:\n" + "\n".join(f"• {error}" for error in validation_errors)
                return error_msg
            
            # Generate execution plan
            execution_order = config.get_execution_order()
            
            # Store pending workflow
            self.pending_workflow = {
                'config': config,
                'test_id': test_id,
                'timestamp': timestamp,
                'execution_order': execution_order
            }
            
            # Generate confirmation prompt
            confirmation_prompt = self._format_workflow_parameters(config, test_id, execution_order)
            return confirmation_prompt
            
        except Exception as e:
            logger.error(f"Error preparing workflow: {str(e)}")
            return f"Error preparing workflow: {str(e)}"
    
    def _format_workflow_parameters(self, config: K6WorkflowConfig, test_id: str, execution_order: List[List[str]]) -> str:
        """Format workflow parameters for user confirmation."""
        params = f"""
=== K6 MULTI-REQUEST WORKFLOW CONFIGURATION ===
Workflow: {config.workflow_name}
Test ID: {test_id}
Description: {config.description or 'No description provided'}

Execution Settings:
• Virtual Users: {config.virtual_users}
• Mode: {config.execution_mode}
• Load Pattern: {config.load_pattern}"""
        
        if config.iterations:
            params += f"""
• Iterations: {config.iterations}
• Total Requests: {len(config.steps) * config.iterations * config.virtual_users}"""
        else:
            params += f"""
• Duration: {config.duration}"""
        
        params += f"""

Request Sequence ({len(config.steps)} steps):"""
        
        for level, step_ids in enumerate(execution_order):
            params += f"""
Level {level + 1} (parallel execution):"""
            for step_id in step_ids:
                step = next(s for s in config.steps if s.step_id == step_id)
                params += f"""
  • {step.name} ({step_id})
    {step.method} {step.url}"""
                
                if step.depends_on:
                    params += f"""
    Depends on: {', '.join(step.depends_on)}"""
                
                if step.condition:
                    params += f"""
    Condition: {step.condition}"""
                
                if step.extract_variables:
                    vars_list = ', '.join(step.extract_variables.keys())
                    params += f"""
    Extracts: {vars_list}"""
        
        if config.global_headers:
            params += f"""

Global Headers:"""
            for key, value in config.global_headers.items():
                # Mask potential tokens
                if any(secret in key.lower() for secret in ['token', 'auth', 'key']):
                    masked_value = value[:8] + '*' * max(0, len(value) - 8) if len(value) > 8 else '*' * len(value)
                    params += f"""
• {key}: {masked_value}"""
                else:
                    params += f"""
• {key}: {value}"""
        
        if config.thresholds:
            params += f"""

Performance Thresholds:"""
            for metric, threshold in config.thresholds.items():
                params += f"""
• {metric}: {threshold}"""
        
        params += f"""

Options:
• Stop on Failure: {config.stop_on_failure}
• Share Cookies: {config.share_cookies}
• Per-Step Metrics: {config.detailed_per_step_metrics}
• Request Logging: {config.log_requests}
===============================================

🚨 WORKFLOW NOT EXECUTED YET - CONFIRMATION REQUIRED 🚨

PLEASE CONFIRM: Do you want to run this multi-request workflow?
Use confirm_test tool with response: "y" or "n", then execute_confirmed_test

⚠️  The workflow will NOT run until you confirm with "y"
🔒 Default response is "n" (cancel) for safety
"""
        return params
    
    async def confirm_workflow(self, response: str = "n") -> str:
        """Handle workflow confirmation response - ONLY confirms, does not execute."""
        if not self.pending_workflow:
            return "No pending workflow to confirm. Please run run_k6_multi_request_test first."
        
        # Default to "n" for safety if no response provided
        response = response or "n"
        response_lower = response.lower()
        if response_lower in ['y', 'yes']:
            # Move to confirmed state, but don't execute yet
            self.confirmed_workflow = self.pending_workflow
            self.pending_workflow = None
            
            return f"✅ Workflow confirmed and ready for execution.\n\nUse execute_confirmed_test tool to run the workflow:\n• Workflow: {self.confirmed_workflow['config'].workflow_name}\n• Steps: {len(self.confirmed_workflow['config'].steps)}\n• Test ID: {self.confirmed_workflow['test_id']}"
        
        elif response_lower in ['n', 'no']:
            # Cancel workflow
            self.pending_workflow = None
            return "❌ Workflow execution cancelled by user. (Default: cancel for safety)"
        
        else:
            return f"Invalid response '{response}'. Please respond with 'y' (yes) or 'n' (no)."
    
    def is_confirmed(self) -> bool:
        """Check if there's a confirmed workflow ready for execution."""
        return self.confirmed_workflow is not None
    
    async def execute_confirmed_workflow(self) -> str:
        """Execute the previously confirmed workflow."""
        if not self.confirmed_workflow:
            return "No confirmed workflow ready for execution. Use confirm_test first."
        
        # Execute the confirmed workflow
        config = self.confirmed_workflow['config']
        test_id = self.confirmed_workflow['test_id']
        
        # Clear confirmed workflow
        self.confirmed_workflow = None
        
        # Execute workflow
        return await self._execute_workflow(config, test_id)
    
    async def _execute_workflow(self, config: K6WorkflowConfig, test_id: str) -> str:
        """Execute the multi-request workflow."""
        timestamp = datetime.now().isoformat()
        
        try:
            # Generate K6 script for the workflow
            script_content = await self._generate_workflow_script(config, test_id)
            
            # Write script to file
            script_path = self.results_dir / f"k6_workflow_{test_id}.js"
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            # Execute K6 test (similar to existing K6Runner logic)
            result = await self._run_k6_workflow(config, test_id, script_path)
            
            # Store result
            self.workflow_results[test_id] = result
            
            return self._format_workflow_report(result)
            
        except Exception as e:
            logger.error(f"Error executing workflow: {str(e)}")
            return f"Error executing workflow: {str(e)}"
    
    async def _generate_workflow_script(self, config: K6WorkflowConfig, test_id: str) -> str:
        """Generate K6 JavaScript for multi-request workflow."""
        # Load multi-request template
        template_path = self.templates_dir / "multi_request_workflow.js"
        if not template_path.exists():
            raise FileNotFoundError("Multi-request workflow template not found")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        # Prepare workflow steps as JSON for the K6 script
        workflow_steps = []
        for step in config.steps:
            step_config = {
                'step_id': step.step_id,
                'name': step.name,
                'url': step.url,
                'method': step.method,
                'payload': step.payload,
                'headers': step.headers or {},
                'depends_on': step.depends_on or [],
                'condition': step.condition,
                'extract_variables': step.extract_variables or {},
                'extract_cookies': step.extract_cookies,
                'extract_headers': step.extract_headers or [],
                'on_failure': step.on_failure,
                'retry_attempts': step.retry_attempts,
                'timeout': step.timeout,
                'think_time': step.think_time
            }
            workflow_steps.append(step_config)
        
        # Template substitutions
        substitutions = {
            'test_id': test_id,
            'workflow_name': config.workflow_name,
            'virtual_users': str(config.virtual_users),
            'workflow_steps_json': json.dumps(workflow_steps, indent=2),
            'execution_mode': config.execution_mode,
            'stop_on_failure': 'true' if config.stop_on_failure else 'false',
            'share_cookies': 'true' if config.share_cookies else 'false',
            'detailed_per_step_metrics': 'true' if config.detailed_per_step_metrics else 'false',
            'log_requests': 'true' if config.log_requests else 'false'
        }
        
        # Handle execution mode (iterations vs duration)
        if config.iterations is not None:
            substitutions['execution_mode_block'] = f"iterations: {config.iterations},"
        else:
            duration = config.duration or "30s"
            substitutions['execution_mode_block'] = f"duration: '{duration}',"
        
        # Handle thresholds with defaults for reliability
        thresholds_js = []
        if config.thresholds:
            for key, value in config.thresholds.items():
                thresholds_js.append(f"    '{key}': ['{value}']")
        else:
            # Set conservative default thresholds for workflow stability
            thresholds_js = [
                "    'http_req_failed': ['rate<0.1']",
                "    'http_req_duration': ['p(95)<30000']"  # 30 second timeout
            ]
        thresholds_str = ',\n'.join(thresholds_js)
        substitutions['thresholds_block'] = f"thresholds: {{\n{thresholds_str}\n  }},"
        
        # Handle global headers
        if config.global_headers:
            headers_js = []
            for key, value in config.global_headers.items():
                headers_js.append(f"      '{key}': '{value}'")
            substitutions['global_headers_block'] = ',\n'.join(headers_js) + ','
        else:
            substitutions['global_headers_block'] = ''
        
        # Apply substitutions to template
        script = template
        for key, value in substitutions.items():
            script = script.replace('{{' + key + '}}', str(value))
        
        return script
    
    async def _run_k6_workflow(self, config: K6WorkflowConfig, test_id: str, script_path: Path) -> K6WorkflowResult:
        """Execute K6 workflow and parse results."""
        # Ensure subdirectories exist
        import os
        os.makedirs("csv", exist_ok=True)
        os.makedirs("html", exist_ok=True)
        
        # Prepare K6 command
        results_filename = f"test_{test_id}_workflow_results.json"
        csv_filename = f"csv/test_{test_id}_workflow_metrics.csv"
        k6_summary_filename = f"{test_id}_k6_summary.json"  # K6's built-in summary
        
        cmd = [
            "k6", "run",
            "--out", f"json={results_filename}",
            "--out", f"csv={csv_filename}",
            "--summary-export", k6_summary_filename,
            str(script_path.name)
        ]
        
        # Add K6 Web Dashboard environment variables
        env = {
            **os.environ,
            "K6_WEB_DASHBOARD": "true",
            "K6_WEB_DASHBOARD_EXPORT": f"html/html-report_{test_id}.html",
            "K6_WEB_DASHBOARD_PERIOD": "1s"
        }
        
        logger.info(f"Running K6 workflow command: {' '.join(cmd)}")
        
        # Execute K6 using sandboxed command
        try:
            result = run_sandboxed_command(
                cmd,
                timeout=3600,  # 1 hour timeout
                max_memory_mb=2048,  # 2GB memory limit
                max_cpu_seconds=1800,  # 30 minutes CPU time
                working_dir=self.results_dir,
                env=env
            )
            stdout_text = result.stdout
            stderr_text = result.stderr
            returncode = result.returncode
        except Exception as e:
            logger.error(f"Error executing K6 workflow: {str(e)}")
            returncode = 1
            stdout_text = ""
            stderr_text = str(e)
        
        # Parse results
        if returncode == 0:
            result = await self._parse_workflow_results(test_id, config)
            logger.info(f"Workflow executed successfully: {result.workflow_name}")
            return result
        else:
            error_msg = stderr_text or "Unknown error"
            logger.error(f"K6 workflow failed: {error_msg}")
            
            # Return failed result
            return K6WorkflowResult(
                workflow_name=config.workflow_name,
                test_id=test_id,
                timestamp=datetime.now().isoformat(),
                overall_success=False,
                total_duration=0,
                virtual_users=config.virtual_users,
                iterations_completed=0,
                step_results=[],
                extracted_variables={},
                workflow_metrics={},
                error_summary=error_msg
            )
    
    async def _parse_workflow_results(self, test_id: str, config: K6WorkflowConfig) -> K6WorkflowResult:
        """Parse K6 workflow results from JSON files."""
        # First try our custom workflow summary generated by handleSummary
        workflow_summary_file = self.results_dir / f"test_{test_id}_workflow_summary.json"
        # Fallback to K6's built-in summary
        k6_summary_file = self.results_dir / f"{test_id}_k6_summary.json"
        results_file = self.results_dir / f"test_{test_id}_workflow_results.json"
        
        # Prefer custom workflow summary if it exists
        if workflow_summary_file.exists():
            summary_file = workflow_summary_file
        elif k6_summary_file.exists():
            summary_file = k6_summary_file
        else:
            raise FileNotFoundError(f"No summary file found. Expected: {workflow_summary_file} or {k6_summary_file}")
        
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            
            # Extract workflow metrics and step results
            workflow_metrics = {}
            step_results = []
            extracted_variables = {}
            
            # Check if this is our custom workflow summary or K6's built-in summary
            is_custom_summary = 'workflow_name' in summary and 'step_results' in summary
            
            if is_custom_summary:
                # Parse our custom workflow summary
                step_results = summary.get('step_results', [])
                workflow_metrics = summary.get('overall_metrics', {})
                # Convert step results to expected format
                for step in step_results:
                    if 'extracted_variables' in step:
                        extracted_variables.update(step['extracted_variables'])
            else:
                # Parse metrics from K6's built-in summary
                if 'metrics' in summary:
                    metrics_data = summary['metrics']
                
                # Overall workflow metrics
                if 'http_reqs' in metrics_data:
                    reqs = metrics_data['http_reqs']
                    workflow_metrics['total_requests'] = reqs.get('count', 0)
                    workflow_metrics['requests_per_second'] = reqs.get('rate', 0)
                
                if 'http_req_duration' in metrics_data:
                    duration = metrics_data['http_req_duration']
                    workflow_metrics['avg_response_time'] = duration.get('avg', 0)
                    workflow_metrics['p95_response_time'] = duration.get('p(95)', 0)
                
                    if 'http_req_failed' in metrics_data:
                        failed = metrics_data['http_req_failed']
                        error_rate_fraction = failed.get('value', 0)  # Already a fraction (0-1)
                        error_rate_percent = error_rate_fraction * 100
                        workflow_metrics['error_rate'] = error_rate_percent
            
            # Determine overall success based on error rate and thresholds
            overall_success = True
            if 'error_rate' in workflow_metrics:
                # Consider workflow successful if error rate is below 10%
                if workflow_metrics['error_rate'] >= 10.0:
                    overall_success = False
            
            # Also check if any thresholds failed (only for K6 built-in summary)
            if not is_custom_summary and 'metrics' in summary:
                metrics_data = summary['metrics']
                if 'http_req_failed' in metrics_data:
                    thresholds = metrics_data['http_req_failed'].get('thresholds', {})
                    for threshold_name, threshold_passed in thresholds.items():
                        if not threshold_passed:
                            overall_success = False
            
            # Get test duration
            total_duration = 0
            if 'state' in summary:
                total_duration = summary['state'].get('testRunDurationMs', 0) / 1000
            
            # TODO: Parse per-step results from detailed results file
            # This would require parsing the raw K6 JSON output to extract
            # individual step metrics and extracted variables
            
            iterations_completed = workflow_metrics.get('total_requests', 0) // len(config.steps) if config.steps else 0
            
            return K6WorkflowResult(
                workflow_name=config.workflow_name,
                test_id=test_id,
                timestamp=datetime.now().isoformat(),
                overall_success=overall_success,
                total_duration=total_duration,
                virtual_users=config.virtual_users,
                iterations_completed=iterations_completed,
                step_results=step_results,
                extracted_variables=extracted_variables,
                workflow_metrics=workflow_metrics,
                error_summary=None if overall_success else "Workflow completed with errors"
            )
            
        except Exception as e:
            logger.error(f"Error parsing workflow results: {str(e)}")
            raise
    
    def _format_workflow_report(self, result: K6WorkflowResult) -> str:
        """Format workflow execution results into readable report."""
        status_icon = "✅" if result.overall_success else "❌"
        status_text = "SUCCESS" if result.overall_success else "FAILED"
        
        report = f"""
{status_icon} K6 Multi-Request Workflow Report - {status_text}
═════════════════════════════════════════════════

📊 Workflow: {result.workflow_name}
🆔 Test ID: {result.test_id}
⏱️ Duration: {result.total_duration:.2f}s
👥 Virtual Users: {result.virtual_users}
🔄 Iterations: {result.iterations_completed}

📈 Overall Metrics:"""
        
        if result.workflow_metrics:
            metrics = result.workflow_metrics
            if 'total_requests' in metrics:
                report += f"""
🚀 Total Requests: {metrics['total_requests']}
📊 Requests/sec: {metrics.get('requests_per_second', 0):.2f}"""
            
            if 'avg_response_time' in metrics:
                report += f"""
⏱️ Avg Response Time: {metrics['avg_response_time']:.2f}ms
📈 95th Percentile: {metrics.get('p95_response_time', 0):.2f}ms"""
            
            if 'error_rate' in metrics:
                error_icon = '✅' if metrics['error_rate'] == 0 else '⚠️' if metrics['error_rate'] < 5 else '🚨'
                report += f"""
{error_icon} Error Rate: {metrics['error_rate']:.2f}%"""
        
        if result.step_results:
            report += f"""

📋 Step Results:"""
            for step in result.step_results:
                step_status = '✅' if step.get('success', False) else '❌'
                report += f"""
{step_status} {step.get('step_name', 'Unknown')} ({step.get('step_id', 'unknown')})
   Duration: {step.get('duration', 0):.2f}ms
   Status: {step.get('status_code', 'N/A')}"""
        
        if result.extracted_variables:
            report += f"""

🔧 Extracted Variables:"""
            for var_name, value in result.extracted_variables.items():
                # Mask sensitive data
                if any(secret in var_name.lower() for secret in ['token', 'password', 'key']):
                    masked_value = str(value)[:8] + '*' * max(0, len(str(value)) - 8) if len(str(value)) > 8 else '*' * len(str(value))
                    report += f"""
• {var_name}: {masked_value}"""
                else:
                    report += f"""
• {var_name}: {value}"""
        
        if not result.overall_success and result.error_summary:
            report += f"""

🚨 Error Summary: {result.error_summary}"""
        
        # Add generated files information
        workflow_summary_file = self.results_dir / f"test_{result.test_id}_workflow_summary.json"
        detailed_summary_file = self.results_dir / f"test_{result.test_id}_detailed_summary.json"
        workflow_results_file = self.results_dir / f"test_{result.test_id}_workflow_results.json"
        html_report_file = self.results_dir / f"html-report_{result.test_id}.html"
        
        report += f"""

📊 Generated Files:"""
        if workflow_summary_file.exists():
            report += f"""
• Workflow Summary: {workflow_summary_file.name} ({workflow_summary_file.stat().st_size:,} bytes)"""
        if detailed_summary_file.exists():
            report += f"""
• Detailed Summary: {detailed_summary_file.name} ({detailed_summary_file.stat().st_size:,} bytes)"""
        if workflow_results_file.exists():
            report += f"""
• Workflow Results: {workflow_results_file.name} ({workflow_results_file.stat().st_size:,} bytes)"""
        if html_report_file.exists():
            report += f"""
• 🌐 HTML Dashboard: {html_report_file.name} ({html_report_file.stat().st_size:,} bytes) - Open in browser for visual analysis"""
        else:
            report += f"""
• ⚠️ HTML Dashboard: Not generated (workflow may be too short < 3 seconds for K6 Web Dashboard)"""
        
        report += f"""

🕐 Timestamp: {result.timestamp}
"""
        
        # Add reminder for failed workflows
        if not result.overall_success:
            report += f"""

🚨 CRITICAL: This workflow failed and requires careful interpretation
⚠️  Remember: Failed workflows measure real system performance, not test configuration issues
"""
        
        return report
    
    async def get_workflow_results(self, test_id: str) -> Optional[K6WorkflowResult]:
        """Get workflow results by test ID."""
        return self.workflow_results.get(test_id)
    
    async def list_workflow_templates(self) -> str:
        """List available workflow templates."""
        from multi_request_models import list_workflow_templates, WORKFLOW_TEMPLATES
        
        templates = list_workflow_templates()
        
        report = "📊 Available Multi-Request Workflow Templates:\n\n"
        
        for template_name in templates:
            template = WORKFLOW_TEMPLATES[template_name]
            report += f"🔧 {template.template_name}\n"
            report += f"   Category: {template.category}\n"
            report += f"   Description: {template.description}\n"
            report += f"   Steps: {len(template.base_config.steps)}\n"
            
            if template.parameters:
                report += f"   Parameters: {', '.join(template.parameters.keys())}\n"
            
            report += "\n"
        
        report += "💡 Use create_test_workflow tool to create workflows from these templates"
        
        return report
    
    async def create_workflow_from_template(self, template_name: str, parameters: Dict[str, Any]) -> str:
        """Create a workflow from a predefined template."""
        try:
            from multi_request_models import create_workflow_from_template
            
            workflow_config = create_workflow_from_template(template_name, parameters)
            
            # Validate the created workflow
            validation_errors = await self.validate_workflow(workflow_config)
            if validation_errors:
                error_msg = "Created workflow has validation errors:\n" + "\n".join(f"• {error}" for error in validation_errors)
                return error_msg
            
            return f"""✅ Workflow created successfully from template '{template_name}'

Workflow Name: {workflow_config.workflow_name}
Steps: {len(workflow_config.steps)}
Virtual Users: {workflow_config.virtual_users}

Use run_k6_multi_request_test to execute this workflow."""
            
        except Exception as e:
            logger.error(f"Error creating workflow from template: {str(e)}")
            return f"Error creating workflow from template: {str(e)}"