"""
Template Engine for K6 Multi-Request Testing.

This module handles template variable interpolation for URLs, payloads, headers,
and other configuration values using data from previous request responses.
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


class TemplateEngineError(Exception):
    """Exception raised when template processing fails."""
    pass


class TemplateEngine:
    """
    Processes template variables in multi-request workflows.
    
    Supports variable interpolation using {{variable_name}} syntax with:
    - Response data from previous steps
    - Extracted variables 
    - Built-in variables (timestamp, uuid, etc.)
    - Global configuration values
    """
    
    def __init__(self):
        self.variable_pattern = re.compile(r'\{\{([^}]+)\}\}')
        self.json_path_pattern = re.compile(r'response\.([^.]+)\.([^}]+)')
    
    def interpolate_template(self, template: str, context: Dict[str, Any]) -> str:
        """
        Interpolate template variables using provided context.
        
        Args:
            template: String containing {{variable}} placeholders
            context: Context dict with variable values
            
        Returns:
            String with variables replaced
            
        Raises:
            TemplateEngineError: When interpolation fails
        """
        if not isinstance(template, str):
            return str(template)
        
        try:
            result = template
            
            # Find all template variables
            matches = self.variable_pattern.findall(template)
            
            for match in matches:
                variable_path = match.strip()
                
                try:
                    # Get variable value from context
                    value = self._resolve_variable_path(variable_path, context)
                    
                    if value is not None:
                        # Replace template variable with value
                        placeholder = '{{' + match + '}}'
                        
                        # Convert value to string, handling different types
                        if isinstance(value, (dict, list)):
                            value_str = json.dumps(value)
                        elif isinstance(value, bool):
                            value_str = 'true' if value else 'false'
                        else:
                            value_str = str(value)
                        
                        result = result.replace(placeholder, value_str)
                        logger.debug(f"Interpolated {placeholder} -> {value_str}")
                    else:
                        logger.warning(f"Variable '{variable_path}' not found in context")
                        
                except Exception as e:
                    logger.warning(f"Error resolving variable '{variable_path}': {str(e)}")
                    continue
            
            return result
            
        except Exception as e:
            logger.error(f"Template interpolation failed: {str(e)}")
            raise TemplateEngineError(f"Failed to interpolate template: {str(e)}")
    
    def _resolve_variable_path(self, variable_path: str, context: Dict[str, Any]) -> Any:
        """
        Resolve a variable path like 'response.step1.body.userId' to its value.
        
        Args:
            variable_path: Dot-separated path to variable
            context: Context dict with variables
            
        Returns:
            Variable value or None if not found
        """
        try:
            # Handle built-in variables
            if variable_path in self._get_builtin_variables():
                return self._get_builtin_variables()[variable_path]
            
            # Split path into components
            path_components = variable_path.split('.')
            
            # Navigate through context
            current = context
            for component in path_components:
                if isinstance(current, dict) and component in current:
                    current = current[component]
                else:
                    return None
            
            return current
            
        except Exception as e:
            logger.debug(f"Could not resolve variable path '{variable_path}': {str(e)}")
            return None
    
    def _get_builtin_variables(self) -> Dict[str, Any]:
        """Get built-in template variables."""
        import random
        
        return {
            'timestamp': int(time.time()),
            'current_timestamp': datetime.now().isoformat(),
            'random_int': random.randint(1000, 9999),
            'random_uuid': str(uuid.uuid4()),
            'uuid': str(uuid.uuid4()),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'time': datetime.now().strftime('%H:%M:%S'),
            'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def extract_template_variables(self, template: str) -> Set[str]:
        """
        Extract all template variables from a string.
        
        Args:
            template: String that may contain {{variable}} placeholders
            
        Returns:
            Set of variable names found in template
        """
        if not isinstance(template, str):
            return set()
        
        variables = set()
        matches = self.variable_pattern.findall(template)
        
        for match in matches:
            variable_path = match.strip()
            variables.add(variable_path)
        
        return variables
    
    def validate_template_variables(
        self, 
        template: str, 
        available_variables: Set[str]
    ) -> List[str]:
        """
        Validate that all variables in template are available.
        
        Args:
            template: Template string to validate
            available_variables: Set of available variable names
            
        Returns:
            List of validation errors
        """
        errors = []
        
        try:
            used_variables = self.extract_template_variables(template)
            builtin_variables = set(self._get_builtin_variables().keys())
            
            # Check each used variable
            for variable in used_variables:
                if (variable not in available_variables and 
                    variable not in builtin_variables):
                    
                    # Check if it's a response path that might be valid
                    if not self._is_potentially_valid_response_path(variable):
                        errors.append(f"Undefined variable: {variable}")
            
        except Exception as e:
            errors.append(f"Template validation error: {str(e)}")
        
        return errors
    
    def _is_potentially_valid_response_path(self, variable_path: str) -> bool:
        """Check if variable path could be a valid response path."""
        # Pattern: response.stepId.field or response.stepId.body.subfield
        response_pattern = r'^response\.[a-zA-Z_][a-zA-Z0-9_]*\.(?:status|body|headers|extracted)(?:\..*)?$'
        return bool(re.match(response_pattern, variable_path))
    
    def interpolate_json_object(
        self, 
        json_obj: Union[Dict, List, str, Any], 
        context: Dict[str, Any]
    ) -> Any:
        """
        Recursively interpolate variables in a JSON object/array.
        
        Args:
            json_obj: JSON object, array, or primitive value
            context: Variable context
            
        Returns:
            Object with interpolated variables
        """
        try:
            if isinstance(json_obj, str):
                return self.interpolate_template(json_obj, context)
            
            elif isinstance(json_obj, dict):
                result = {}
                for key, value in json_obj.items():
                    # Interpolate both key and value
                    interpolated_key = self.interpolate_template(str(key), context)
                    result[interpolated_key] = self.interpolate_json_object(value, context)
                return result
            
            elif isinstance(json_obj, list):
                return [self.interpolate_json_object(item, context) for item in json_obj]
            
            else:
                # Primitive types (int, float, bool, None)
                return json_obj
                
        except Exception as e:
            logger.error(f"Error interpolating JSON object: {str(e)}")
            return json_obj
    
    def interpolate_url_with_params(
        self, 
        base_url: str, 
        query_params: Optional[Dict[str, str]], 
        context: Dict[str, Any]
    ) -> str:
        """
        Interpolate URL and query parameters.
        
        Args:
            base_url: Base URL template
            query_params: Query parameters (may contain templates)
            context: Variable context
            
        Returns:
            Complete URL with interpolated variables
        """
        try:
            # Interpolate base URL
            url = self.interpolate_template(base_url, context)
            
            # Interpolate query parameters
            if query_params:
                interpolated_params = {}
                for key, value in query_params.items():
                    interpolated_key = self.interpolate_template(key, context)
                    interpolated_value = self.interpolate_template(value, context)
                    interpolated_params[interpolated_key] = interpolated_value
                
                # Build query string
                from urllib.parse import urlencode
                query_string = urlencode(interpolated_params)
                
                # Append to URL
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}{query_string}"
            
            return url
            
        except Exception as e:
            logger.error(f"Error interpolating URL: {str(e)}")
            return base_url
    
    def interpolate_headers(
        self, 
        headers: Dict[str, str], 
        context: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Interpolate template variables in HTTP headers.
        
        Args:
            headers: Headers dict with potential template variables
            context: Variable context
            
        Returns:
            Headers with interpolated values
        """
        try:
            result = {}
            
            for key, value in headers.items():
                interpolated_key = self.interpolate_template(key, context)
                interpolated_value = self.interpolate_template(value, context)
                result[interpolated_key] = interpolated_value
            
            return result
            
        except Exception as e:
            logger.error(f"Error interpolating headers: {str(e)}")
            return headers
    
    def interpolate_payload(
        self, 
        payload: Union[Dict, List, str], 
        context: Dict[str, Any]
    ) -> Union[str, Dict, List]:
        """
        Interpolate template variables in request payload.
        
        Args:
            payload: Request payload (dict, list, or string)
            context: Variable context
            
        Returns:
            Payload with interpolated variables
        """
        try:
            if isinstance(payload, str):
                # String payload - interpolate directly
                return self.interpolate_template(payload, context)
            
            elif isinstance(payload, (dict, list)):
                # JSON payload - recursively interpolate
                return self.interpolate_json_object(payload, context)
            
            else:
                return payload
                
        except Exception as e:
            logger.error(f"Error interpolating payload: {str(e)}")
            return payload
    
    def evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """
        Evaluate a condition expression with template variables.
        
        Args:
            condition: Condition string like "{{response.step1.status}} == 200"
            context: Variable context
            
        Returns:
            Boolean result of condition evaluation
        """
        try:
            # Interpolate variables in condition
            interpolated_condition = self.interpolate_template(condition, context)
            
            # Basic condition evaluation
            # Support simple comparisons: ==, !=, <, >, <=, >=
            comparison_operators = ['==', '!=', '<=', '>=', '<', '>']
            
            for operator in comparison_operators:
                if operator in interpolated_condition:
                    left, right = interpolated_condition.split(operator, 1)
                    left = left.strip()
                    right = right.strip()
                    
                    # Try to convert to appropriate types for comparison
                    left_val = self._parse_value(left)
                    right_val = self._parse_value(right)
                    
                    # Perform comparison
                    if operator == '==':
                        return left_val == right_val
                    elif operator == '!=':
                        return left_val != right_val
                    elif operator == '<':
                        return left_val < right_val
                    elif operator == '>':
                        return left_val > right_val
                    elif operator == '<=':
                        return left_val <= right_val
                    elif operator == '>=':
                        return left_val >= right_val
            
            # If no comparison operator found, treat as boolean
            return bool(self._parse_value(interpolated_condition))
            
        except Exception as e:
            logger.warning(f"Error evaluating condition '{condition}': {str(e)}")
            return False
    
    def _parse_value(self, value_str: str) -> Any:
        """Parse string value to appropriate type."""
        value_str = value_str.strip()
        
        # Remove quotes if present
        if ((value_str.startswith('"') and value_str.endswith('"')) or
            (value_str.startswith("'") and value_str.endswith("'"))):
            return value_str[1:-1]
        
        # Try to parse as number
        try:
            if '.' in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass
        
        # Check for boolean
        if value_str.lower() in ('true', 'false'):
            return value_str.lower() == 'true'
        
        # Check for null/none
        if value_str.lower() in ('null', 'none'):
            return None
        
        # Return as string
        return value_str
    
    def create_context_from_responses(
        self, 
        step_responses: List[Dict[str, Any]], 
        global_variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create template context from step responses and global variables.
        
        Args:
            step_responses: List of step response data
            global_variables: Additional global variables
            
        Returns:
            Complete context for template interpolation
        """
        context = {}
        
        # Add built-in variables
        context.update(self._get_builtin_variables())
        
        # Add global variables
        if global_variables:
            context.update(global_variables)
        
        # Add response data
        context['response'] = {}
        
        for step_data in step_responses:
            step_id = step_data.get('step_id')
            if step_id:
                context['response'][step_id] = {
                    'status': step_data.get('status'),
                    'body': step_data.get('body', {}),
                    'headers': step_data.get('headers', {}),
                    'extracted': step_data.get('extracted_variables', {})
                }
                
                # Also add extracted variables at root level for convenience
                if 'extracted_variables' in step_data:
                    context.update(step_data['extracted_variables'])
        
        return context
    
    def generate_k6_interpolation_code(
        self, 
        template: str, 
        context_var_name: str = "globalContext"
    ) -> str:
        """
        Generate JavaScript code for K6 to perform template interpolation.
        
        Args:
            template: Template string with {{variables}}
            context_var_name: Name of context variable in K6 script
            
        Returns:
            JavaScript code string
        """
        try:
            variables = self.extract_template_variables(template)
            
            js_code = f'let interpolatedValue = "{template}";\n'
            
            for variable in variables:
                placeholder = '{{' + variable + '}}'
                js_code += f'''
if ({context_var_name}["{variable}"] !== undefined) {{
  interpolatedValue = interpolatedValue.replace("{placeholder}", {context_var_name}["{variable}"]);
}}'''
            
            js_code += '\nreturn interpolatedValue;'
            
            return js_code
            
        except Exception as e:
            logger.error(f"Error generating K6 interpolation code: {str(e)}")
            return f'return "{template}";'