"""
Chain Processor for K6 Multi-Request Testing.

This module handles response data extraction and chaining between request steps,
enabling variables from one response to be used in subsequent requests.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


class ChainProcessingError(Exception):
    """Exception raised when chain processing fails."""
    pass


class ChainProcessor:
    """
    Processes response data extraction and variable chaining for multi-request workflows.
    
    Handles:
    - JSON path extraction from response bodies
    - Header value extraction
    - Cookie extraction and management
    - Session data persistence
    - Variable context building
    """
    
    def __init__(self):
        self.session_cookies = {}
        self.global_context = {}
    
    def extract_from_response(
        self, 
        response_data: Dict[str, Any], 
        extraction_rules: Dict[str, str],
        step_id: str
    ) -> Dict[str, Any]:
        """
        Extract variables from HTTP response using configured extraction rules.
        
        Args:
            response_data: Response data containing body, headers, status, etc.
            extraction_rules: Dict mapping variable names to extraction paths
            step_id: ID of the step for context building
            
        Returns:
            Dict of extracted variable values
            
        Raises:
            ChainProcessingError: When extraction fails
        """
        extracted = {}
        
        try:
            for var_name, extraction_path in extraction_rules.items():
                try:
                    value = self._extract_single_value(response_data, extraction_path)
                    if value is not None:
                        extracted[var_name] = value
                        logger.debug(f"Extracted {var_name} = {value} from step {step_id}")
                    else:
                        logger.warning(f"Failed to extract {var_name} using path '{extraction_path}' from step {step_id}")
                        
                except Exception as e:
                    logger.warning(f"Error extracting {var_name} from step {step_id}: {str(e)}")
                    continue
            
            return extracted
            
        except Exception as e:
            logger.error(f"Error in extract_from_response: {str(e)}")
            raise ChainProcessingError(f"Failed to extract variables from response: {str(e)}")
    
    def _extract_single_value(self, response_data: Dict[str, Any], extraction_path: str) -> Any:
        """Extract a single value using the specified path."""
        
        if extraction_path.startswith('$.'):
            # JSON Path extraction from response body
            return self._extract_json_path(response_data.get('body', {}), extraction_path)
            
        elif extraction_path.startswith('headers.'):
            # Header extraction
            header_name = extraction_path[8:]  # Remove 'headers.' prefix
            return self._extract_header(response_data.get('headers', {}), header_name)
            
        elif extraction_path.startswith('cookies.'):
            # Cookie extraction
            cookie_name = extraction_path[8:]  # Remove 'cookies.' prefix
            return self._extract_cookie(response_data.get('headers', {}), cookie_name)
            
        elif extraction_path == 'status':
            # Status code
            return response_data.get('status')
            
        elif extraction_path.startswith('url.'):
            # URL component extraction
            return self._extract_url_component(response_data.get('url', ''), extraction_path[4:])
            
        else:
            logger.warning(f"Unknown extraction path format: {extraction_path}")
            return None
    
    def _extract_json_path(self, data: Any, json_path: str) -> Any:
        """
        Extract value using JSONPath-like syntax.
        
        Supports basic JSONPath patterns:
        - $.field - root level field
        - $.field.subfield - nested field
        - $.array[0] - array index
        - $.array[0].field - array element field
        """
        try:
            if not json_path.startswith('$.'):
                raise ValueError("JSON path must start with '$.'")
            
            path = json_path[2:]  # Remove '$.' prefix
            current = data
            
            # Split path into components, handling array indices
            components = []
            current_component = ""
            in_brackets = False
            
            for char in path:
                if char == '[':
                    if current_component:
                        components.append(current_component)
                        current_component = ""
                    in_brackets = True
                elif char == ']':
                    if current_component:
                        # Array index
                        try:
                            index = int(current_component)
                            components.append(index)
                        except ValueError:
                            components.append(current_component)  # Could be a key with brackets
                        current_component = ""
                    in_brackets = False
                elif char == '.' and not in_brackets:
                    if current_component:
                        components.append(current_component)
                        current_component = ""
                else:
                    current_component += char
            
            if current_component:
                components.append(current_component)
            
            # Navigate through the data structure
            for component in components:
                if isinstance(component, int):
                    # Array index
                    if isinstance(current, list) and 0 <= component < len(current):
                        current = current[component]
                    else:
                        return None
                else:
                    # Object key
                    if isinstance(current, dict) and component in current:
                        current = current[component]
                    else:
                        return None
            
            return current
            
        except Exception as e:
            logger.warning(f"JSON path extraction failed for '{json_path}': {str(e)}")
            return None
    
    def _extract_header(self, headers: Dict[str, str], header_name: str) -> Optional[str]:
        """Extract header value (case-insensitive)."""
        try:
            # Case-insensitive header lookup
            for key, value in headers.items():
                if key.lower() == header_name.lower():
                    return value
            return None
        except Exception as e:
            logger.warning(f"Header extraction failed for '{header_name}': {str(e)}")
            return None
    
    def _extract_cookie(self, headers: Dict[str, str], cookie_name: str) -> Optional[str]:
        """Extract cookie value from Set-Cookie headers."""
        try:
            set_cookie_headers = []
            
            # Collect all Set-Cookie headers (case-insensitive)
            for key, value in headers.items():
                if key.lower() == 'set-cookie':
                    set_cookie_headers.append(value)
            
            # Parse cookies from Set-Cookie headers
            for cookie_header in set_cookie_headers:
                # Parse cookie string: "name=value; Path=/; HttpOnly"
                cookie_parts = cookie_header.split(';')
                if cookie_parts:
                    name_value = cookie_parts[0].strip()
                    if '=' in name_value:
                        name, value = name_value.split('=', 1)
                        if name.strip() == cookie_name:
                            return value.strip()
            
            return None
            
        except Exception as e:
            logger.warning(f"Cookie extraction failed for '{cookie_name}': {str(e)}")
            return None
    
    def _extract_url_component(self, url: str, component: str) -> Optional[str]:
        """Extract component from URL (host, path, query parameters)."""
        try:
            parsed_url = urlparse(url)
            
            if component == 'host':
                return parsed_url.hostname
            elif component == 'path':
                return parsed_url.path
            elif component == 'query':
                return parsed_url.query
            elif component.startswith('query.'):
                # Extract specific query parameter
                param_name = component[6:]  # Remove 'query.' prefix
                query_params = parse_qs(parsed_url.query)
                param_values = query_params.get(param_name, [])
                return param_values[0] if param_values else None
            else:
                return None
                
        except Exception as e:
            logger.warning(f"URL component extraction failed for '{component}': {str(e)}")
            return None
    
    def extract_cookies_from_response(self, response_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract all cookies from response Set-Cookie headers.
        
        Returns:
            Dict mapping cookie names to values
        """
        cookies = {}
        headers = response_data.get('headers', {})
        
        try:
            # Find Set-Cookie headers (case-insensitive)
            set_cookie_headers = []
            for key, value in headers.items():
                if key.lower() == 'set-cookie':
                    if isinstance(value, list):
                        set_cookie_headers.extend(value)
                    else:
                        set_cookie_headers.append(value)
            
            # Parse each Set-Cookie header
            for cookie_header in set_cookie_headers:
                cookie_parts = cookie_header.split(';')
                if cookie_parts:
                    name_value = cookie_parts[0].strip()
                    if '=' in name_value:
                        name, value = name_value.split('=', 1)
                        cookies[name.strip()] = value.strip()
            
        except Exception as e:
            logger.warning(f"Error extracting cookies: {str(e)}")
        
        return cookies
    
    def merge_session_data(
        self, 
        previous_session: Dict[str, Any], 
        new_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge new session data with previous session data.
        
        Args:
            previous_session: Previous session data
            new_data: New data to merge
            
        Returns:
            Merged session data
        """
        try:
            merged = previous_session.copy()
            
            # Merge extracted variables
            if 'extracted_variables' in new_data:
                if 'extracted_variables' not in merged:
                    merged['extracted_variables'] = {}
                merged['extracted_variables'].update(new_data['extracted_variables'])
            
            # Merge cookies
            if 'cookies' in new_data:
                if 'cookies' not in merged:
                    merged['cookies'] = {}
                merged['cookies'].update(new_data['cookies'])
            
            # Update other fields
            for key, value in new_data.items():
                if key not in ['extracted_variables', 'cookies']:
                    merged[key] = value
            
            return merged
            
        except Exception as e:
            logger.error(f"Error merging session data: {str(e)}")
            return previous_session
    
    def build_context_for_step(
        self, 
        step_responses: List[Dict[str, Any]], 
        global_variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build template context for current step based on previous responses.
        
        Args:
            step_responses: List of previous step responses with extracted data
            global_variables: Global variables to include
            
        Returns:
            Context dict for template interpolation
        """
        context = {}
        
        try:
            # Add global variables
            if global_variables:
                context.update(global_variables)
            
            # Add built-in variables
            context.update({
                'timestamp': int(time.time()),
                'current_timestamp': datetime.now().isoformat(),
                'random_int': random.randint(1000, 9999),
                'uuid': str(uuid.uuid4())
            })
            
            # Build response context
            context['response'] = {}
            
            for step_data in step_responses:
                step_id = step_data.get('step_id')
                if not step_id:
                    continue
                
                # Add response data for this step
                step_context = {
                    'status': step_data.get('status'),
                    'body': step_data.get('body'),
                    'headers': step_data.get('headers', {}),
                    'extracted': step_data.get('extracted_variables', {})
                }
                
                context['response'][step_id] = step_context
                
                # Also add extracted variables at root level for easier access
                if 'extracted_variables' in step_data:
                    context.update(step_data['extracted_variables'])
            
            # Add session cookies
            if self.session_cookies:
                context['cookies'] = self.session_cookies
            
            return context
            
        except Exception as e:
            logger.error(f"Error building context: {str(e)}")
            return {}
    
    def update_session_cookies(self, new_cookies: Dict[str, str]) -> None:
        """Update session cookies with new values."""
        self.session_cookies.update(new_cookies)
        logger.debug(f"Updated session cookies: {list(self.session_cookies.keys())}")
    
    def clear_session_cookies(self) -> None:
        """Clear all session cookies."""
        self.session_cookies.clear()
        logger.debug("Cleared session cookies")
    
    def get_session_cookies(self) -> Dict[str, str]:
        """Get current session cookies."""
        return self.session_cookies.copy()
    
    def process_response_chain(
        self,
        step_id: str,
        response_data: Dict[str, Any],
        extraction_rules: Dict[str, str],
        extract_cookies: bool = True,
        extract_headers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Process a single response in the chain, extracting variables and updating session.
        
        Args:
            step_id: ID of the current step
            response_data: HTTP response data
            extraction_rules: Variable extraction rules
            extract_cookies: Whether to auto-extract cookies
            extract_headers: List of header names to extract
            
        Returns:
            Dict containing extracted data and updated session info
        """
        result = {
            'step_id': step_id,
            'status': response_data.get('status'),
            'body': response_data.get('body'),
            'headers': response_data.get('headers', {}),
            'extracted_variables': {},
            'extracted_cookies': {},
            'extracted_headers': {}
        }
        
        try:
            # Extract variables using configured rules
            if extraction_rules:
                result['extracted_variables'] = self.extract_from_response(
                    response_data, extraction_rules, step_id
                )
            
            # Auto-extract cookies if enabled
            if extract_cookies:
                result['extracted_cookies'] = self.extract_cookies_from_response(response_data)
                # Update session cookies
                if result['extracted_cookies']:
                    self.update_session_cookies(result['extracted_cookies'])
            
            # Extract specific headers if requested
            if extract_headers:
                headers = response_data.get('headers', {})
                for header_name in extract_headers:
                    header_value = self._extract_header(headers, header_name)
                    if header_value is not None:
                        result['extracted_headers'][header_name] = header_value
            
            logger.info(f"Processed response chain for step {step_id}: "
                       f"extracted {len(result['extracted_variables'])} variables, "
                       f"{len(result['extracted_cookies'])} cookies")
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing response chain for step {step_id}: {str(e)}")
            raise ChainProcessingError(f"Failed to process response chain: {str(e)}")


# Import required modules for built-in variables
import time
import random
import uuid
from datetime import datetime