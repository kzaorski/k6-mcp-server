"""
HAR Processor for K6 MCP Server.

This module processes HAR (HTTP Archive) files and converts them into
K6 multi-request workflows with intelligent response chaining detection
and static files management.
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, parse_qs

from har_models import (
    HARFile, HAREntry, HARRequest, HARConversionOptions, HARAnalysisResult, 
    ChainPoint, PageGroup, RequestType, StaticFilesConfig
)
from multi_request_models import K6MultiRequestConfig, RequestStep
from static_files_manager import StaticFilesManager
from template_engine import TemplateEngine
from security_utils import (
    safe_json_parse,
    sanitize_url,
    validate_json_payload,
    InputValidationError
)

logger = logging.getLogger(__name__)


class HARProcessor:
    """
    Main processor for converting HAR files to K6 multi-request workflows.
    
    Handles parsing, analysis, response chaining detection, and static files
    management with configurable strategies.
    """
    
    def __init__(self, options: Optional[HARConversionOptions] = None):
        self.options = options or HARConversionOptions()
        self.static_manager = StaticFilesManager(self.options)
        self.template_engine = TemplateEngine()
        
        # Authentication patterns to detect
        self.auth_patterns = [
            r'/login', r'/auth', r'/signin', r'/authenticate',
            r'/oauth', r'/sso', r'/session', r'/token'
        ]
        
        # Common response fields that might be chained
        self.chain_candidates = [
            'token', 'accessToken', 'access_token', 'authToken',
            'sessionId', 'session_id', 'id', 'userId', 'user_id',
            'csrf_token', 'csrfToken', 'nonce', 'key', 'apiKey'
        ]
    
    def parse_har_file(self, har_content: str) -> HARFile:
        """
        Parse HAR file content into structured HAR models.
        
        Args:
            har_content: HAR file content as JSON string
            
        Returns:
            Parsed HARFile object
            
        Raises:
            ValueError: If HAR content is invalid
        """
        try:
            har_data = json.loads(har_content)
            return HARFile(**har_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in HAR file: {e}")
        except Exception as e:
            raise ValueError(f"Failed to parse HAR file: {e}")
    
    def analyze_har_file(self, har_file: HARFile) -> HARAnalysisResult:
        """
        Analyze HAR file to understand structure and potential optimizations.
        
        Args:
            har_file: Parsed HAR file
            
        Returns:
            Analysis result with insights and recommendations
        """
        entries = har_file.log.entries
        
        # Basic statistics
        total_requests = len(entries)
        unique_domains = set()
        request_types = defaultdict(int)
        
        # Classify all requests
        classified_entries = []
        for entry in entries:
            request_type = self.static_manager.classify_request(entry)
            request_types[request_type.value] += 1
            unique_domains.add(urlparse(entry.request.url).netloc)
            classified_entries.append((entry, request_type))
        
        # Detect page boundaries
        page_groups = self.static_manager.detect_page_boundaries(entries)
        
        # Analyze response chaining opportunities
        potential_chains = self.detect_response_chaining_opportunities(entries)
        
        # Static files analysis
        static_files_summary = self.static_manager.get_static_files_summary(page_groups)
        
        # Timing analysis
        timing_analysis = self._analyze_timing_patterns(entries)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            total_requests, request_types, static_files_summary, timing_analysis
        )
        
        return HARAnalysisResult(
            total_requests=total_requests,
            unique_domains=sorted(unique_domains),
            request_types=dict(request_types),
            page_groups=page_groups,
            potential_chains=potential_chains,
            static_files_summary=static_files_summary,
            timing_analysis=timing_analysis,
            recommendations=recommendations
        )
    
    def convert_har_to_workflow(self, har_file: HARFile, workflow_name: Optional[str] = None) -> K6MultiRequestConfig:
        """
        Convert HAR file to K6 multi-request workflow configuration.
        
        Args:
            har_file: Parsed HAR file
            workflow_name: Name for the generated workflow
            
        Returns:
            K6MultiRequestConfig ready for execution
        """
        entries = har_file.log.entries
        
        if not entries:
            raise ValueError("HAR file contains no HTTP requests")
        
        # Filter entries based on options
        filtered_entries = self._filter_entries(entries)
        
        # Detect page boundaries and group requests
        page_groups = self.static_manager.detect_page_boundaries(filtered_entries)
        
        # Process static files according to configuration
        page_groups = self.static_manager.process_static_files(page_groups)
        
        # Convert entries to request steps
        request_steps = self._convert_entries_to_steps(filtered_entries, page_groups)
        
        # Detect and apply response chaining
        if self.options.extract_dynamic_data:
            request_steps = self._apply_response_chaining(request_steps)
        
        # Generate workflow configuration
        workflow_name = workflow_name or self._generate_workflow_name(har_file)
        
        # Create static files configuration
        static_config = self.static_manager.generate_static_files_config(page_groups)
        
        return K6MultiRequestConfig(
            workflow_name=workflow_name,
            description=f"Generated from HAR file with {len(filtered_entries)} requests",
            steps=request_steps,
            virtual_users=1,
            iterations=1,
            load_pattern="constant",
            global_headers=self._extract_global_headers(filtered_entries),
            share_cookies=True,
            stop_on_failure=True,
            detailed_per_step_metrics=True,
            log_requests=False
        )
    
    def _filter_entries(self, entries: List[HAREntry]) -> List[HAREntry]:
        """Filter entries based on conversion options."""
        filtered = []
        
        for entry in entries:
            # Filter by domain
            domain = urlparse(entry.request.url).netloc
            
            if self.options.exclude_domains and domain in self.options.exclude_domains:
                continue
            
            if self.options.include_only_domains and domain not in self.options.include_only_domains:
                continue
            
            # Filter by status code
            if entry.response.status in self.options.exclude_status_codes:
                continue
            
            # Filter by response time
            if (self.options.min_response_time and 
                entry.timings.total_time < self.options.min_response_time):
                continue
            
            filtered.append(entry)
        
        return filtered
    
    def _convert_entries_to_steps(self, entries: List[HAREntry], page_groups: List[PageGroup]) -> List[RequestStep]:
        """Convert HAR entries to K6 request steps."""
        steps = []
        step_counter = 1
        
        for entry in entries:
            request_type = self.static_manager.classify_request(entry)
            
            # Skip static files if configured to exclude them
            if (request_type == RequestType.STATIC and 
                self.options.static_files_handling.value == "exclude"):
                continue
            
            step = self._create_request_step(entry, step_counter)
            steps.append(step)
            step_counter += 1
        
        return steps
    
    def _create_request_step(self, entry: HAREntry, step_number: int) -> RequestStep:
        """Create a RequestStep from HAR entry."""
        request = entry.request
        response = entry.response
        
        # Generate step ID and name
        step_id = f"step_{step_number}_{self._sanitize_url_for_id(request.url)}"
        step_name = self._generate_step_name(request, response, step_number)
        
        # Convert headers
        headers = {h.name: h.value for h in request.headers}
        
        # Handle cookies
        cookies = {c.name: c.value for c in request.cookies} if request.cookies else None
        
        # Handle query parameters
        parsed_url = urlparse(request.url)
        query_params = dict(parse_qs(parsed_url.query)) if parsed_url.query else None
        if query_params:
            # Flatten single-item lists
            query_params = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}
        
        # Handle POST data
        payload = None
        if request.postData:
            if request.postData.mimeType == 'application/json':
                try:
                    payload = json.loads(request.postData.text) if request.postData.text else None
                except json.JSONDecodeError:
                    payload = request.postData.text
            else:
                payload = request.postData.text
        
        # Detect potential response data to extract
        extract_variables = self._detect_extraction_candidates(response)
        
        # Calculate think time if preserving timing
        think_time = 1.0
        if self.options.preserve_timing:
            think_time = max(0.1, entry.timings.total_time / 1000.0)  # Convert to seconds
        
        return RequestStep(
            step_id=step_id,
            name=step_name,
            url=request.url,
            method=request.method,
            payload=payload,
            headers=headers,
            cookies=cookies,
            query_params=query_params,
            extract_variables=extract_variables,
            timeout=f"{max(30, int(entry.timings.total_time / 100))}s",
            think_time=think_time
        )
    
    def _sanitize_url_for_id(self, url: str) -> str:
        """Create a safe identifier from URL."""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Extract meaningful parts
        path_parts = [p for p in path.split('/') if p and not p.isdigit()][:2]  # Max 2 parts, skip numeric IDs
        
        if not path_parts:
            path_parts = [parsed.netloc.split('.')[0]]  # Use domain name
        
        # Sanitize for use as identifier
        sanitized = '_'.join(path_parts)
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', sanitized)
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        
        return sanitized[:30]  # Limit length
    
    def _generate_step_name(self, request: HARRequest, response, step_number: int) -> str:
        """Generate human-readable step name."""
        # Try to extract meaningful name from URL
        parsed = urlparse(request.url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        
        if path_parts:
            # Use last meaningful path component
            last_part = path_parts[-1]
            if not last_part.isdigit() and '.' not in last_part:  # Not an ID or file
                return f"{request.method} {last_part.replace('_', ' ').replace('-', ' ').title()}"
        
        # Check for API endpoints
        if '/api/' in parsed.path:
            api_parts = parsed.path.split('/api/')[-1].split('/')
            if api_parts and api_parts[0]:
                return f"{request.method} API {api_parts[0].title()}"
        
        # Fallback to generic name
        domain = parsed.netloc.split('.')[0] if '.' in parsed.netloc else parsed.netloc
        return f"{request.method} {domain.title()} Request {step_number}"
    
    def _detect_extraction_candidates(self, response) -> Optional[Dict[str, str]]:
        """Detect potential fields to extract from response."""
        if not response.is_json_response() or not response.content.text:
            return None
        
        try:
            response_data = json.loads(response.content.text)
            extract_vars = {}
            
            # Look for common chain candidate fields
            def find_candidates(obj, path="$"):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        current_path = f"{path}.{key}"
                        
                        # Check if this key is a chain candidate
                        if key.lower() in [c.lower() for c in self.chain_candidates]:
                            if isinstance(value, (str, int, float)) and value:
                                extract_vars[key] = current_path
                        
                        # Recurse into nested objects
                        if isinstance(value, dict):
                            find_candidates(value, current_path)
                        elif isinstance(value, list) and value and isinstance(value[0], dict):
                            find_candidates(value[0], f"{current_path}[0]")
            
            find_candidates(response_data)
            return extract_vars if extract_vars else None
            
        except (json.JSONDecodeError, Exception):
            return None
    
    def detect_response_chaining_opportunities(self, entries: List[HAREntry]) -> List[ChainPoint]:
        """Detect potential response chaining between requests."""
        chains = []
        
        # Create mapping of entries with response data
        entries_with_data = []
        for i, entry in enumerate(entries):
            if entry.response.is_json_response() and entry.response.content.text:
                try:
                    response_data = json.loads(entry.response.content.text)
                    entries_with_data.append((i, entry, response_data))
                except json.JSONDecodeError:
                    pass
        
        # Look for chains between entries
        for i, (idx1, entry1, data1) in enumerate(entries_with_data):
            for j, (idx2, entry2, data2) in enumerate(entries_with_data[i+1:], i+1):
                # Only consider chains going forward in time
                if idx2 <= idx1:
                    continue
                
                # Look for potential chains
                potential_chains = self._find_chains_between_entries(
                    entry1, data1, entry2, idx1, idx2
                )
                chains.extend(potential_chains)
        
        return chains
    
    def _find_chains_between_entries(self, source_entry: HAREntry, source_data: Dict, 
                                   target_entry: HAREntry, source_idx: int, target_idx: int) -> List[ChainPoint]:
        """Find potential chains between two specific entries."""
        chains = []
        
        # Look for values in source response that might be used in target request
        def find_values_in_response(obj, path="$"):
            found_values = {}
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}"
                    if isinstance(value, (str, int, float)) and value:
                        found_values[str(value)] = (key, current_path)
                    elif isinstance(value, dict):
                        found_values.update(find_values_in_response(value, current_path))
            return found_values
        
        source_values = find_values_in_response(source_data)
        
        # Check if any source values appear in target request
        target_request = target_entry.request
        target_content = [
            target_request.url,
            json.dumps({h.name: h.value for h in target_request.headers}),
        ]
        
        if target_request.postData and target_request.postData.text:
            target_content.append(target_request.postData.text)
        
        target_text = ' '.join(target_content)
        
        for value_str, (field_name, extraction_path) in source_values.items():
            if str(value_str) in target_text and len(str(value_str)) > 3:  # Avoid short common values
                # Determine where the value appears in target
                target_location = "url"
                target_field = "url"
                
                if str(value_str) in json.dumps({h.name: h.value for h in target_request.headers}):
                    target_location = "header"
                    # Find which header
                    for header in target_request.headers:
                        if str(value_str) in header.value:
                            target_field = header.name
                            break
                
                elif (target_request.postData and target_request.postData.text and 
                      str(value_str) in target_request.postData.text):
                    target_location = "payload"
                    target_field = "payload"
                
                # Create chain point
                chain = ChainPoint(
                    source_step_id=f"step_{source_idx + 1}",
                    source_field=field_name,
                    target_step_id=f"step_{target_idx + 1}",
                    target_location=target_location,
                    target_field=target_field,
                    extraction_path=extraction_path,
                    confidence=self._calculate_chain_confidence(field_name, value_str, target_location),
                    chain_type=self._determine_chain_type(field_name, value_str)
                )
                chains.append(chain)
        
        return chains
    
    def _calculate_chain_confidence(self, field_name: str, value: str, target_location: str) -> float:
        """Calculate confidence score for a potential chain."""
        confidence = 0.5  # Base confidence
        
        # Higher confidence for known auth fields
        auth_fields = ['token', 'access_token', 'session_id', 'csrf_token']
        if any(auth in field_name.lower() for auth in auth_fields):
            confidence += 0.3
        
        # Higher confidence for authorization headers
        if target_location == "header" and "authorization" in target_location.lower():
            confidence += 0.2
        
        # Higher confidence for longer values (likely to be unique)
        if len(str(value)) > 20:
            confidence += 0.2
        
        return min(1.0, confidence)
    
    def _determine_chain_type(self, field_name: str, value: str) -> str:
        """Determine the type of chain based on field name and value."""
        field_lower = field_name.lower()
        
        if 'token' in field_lower:
            return 'token'
        elif 'session' in field_lower:
            return 'session'
        elif 'csrf' in field_lower:
            return 'csrf'
        elif 'id' in field_lower:
            return 'id'
        elif 'key' in field_lower:
            return 'key'
        else:
            return 'data'
    
    def _apply_response_chaining(self, steps: List[RequestStep]) -> List[RequestStep]:
        """Apply response chaining to request steps."""
        # This would implement the actual chaining logic
        # For now, just return steps as-is
        # TODO: Implement intelligent template variable replacement
        return steps
    
    def _extract_global_headers(self, entries: List[HAREntry]) -> Optional[Dict[str, str]]:
        """Extract headers that appear in most requests as global headers."""
        if not entries:
            return None
        
        header_counts = defaultdict(lambda: defaultdict(int))
        total_requests = len(entries)
        
        # Count header occurrences
        for entry in entries:
            for header in entry.request.headers:
                header_counts[header.name.lower()][header.value] += 1
        
        # Find headers that appear in most requests
        global_headers = {}
        for header_name, value_counts in header_counts.items():
            # Get most common value for this header
            most_common_value = max(value_counts.items(), key=lambda x: x[1])
            value, count = most_common_value
            
            # If header appears in >50% of requests, make it global
            if count > total_requests * 0.5:
                # Skip certain headers that shouldn't be global
                skip_headers = ['content-length', 'content-type', 'cookie', 'authorization']
                if header_name not in skip_headers:
                    global_headers[header_name.title()] = value
        
        return global_headers if global_headers else None
    
    def _generate_workflow_name(self, har_file: HARFile) -> str:
        """Generate a workflow name from HAR file metadata."""
        # Try to get meaningful name from HAR
        if har_file.log.pages and har_file.log.pages[0].title:
            title = har_file.log.pages[0].title
            # Sanitize title for use as workflow name
            sanitized = re.sub(r'[^a-zA-Z0-9\s]', '', title)
            sanitized = re.sub(r'\s+', '_', sanitized).lower()
            return f"har_workflow_{sanitized[:30]}"
        
        # Fallback to domain-based name
        if har_file.log.entries:
            domain = urlparse(har_file.log.entries[0].request.url).netloc
            domain_clean = domain.split('.')[0] if '.' in domain else domain
            return f"har_workflow_{domain_clean}"
        
        return "har_workflow_unnamed"
    
    def _analyze_timing_patterns(self, entries: List[HAREntry]) -> Dict[str, float]:
        """Analyze timing patterns in HAR entries."""
        if not entries:
            return {}
        
        response_times = [entry.timings.total_time for entry in entries]
        gaps = []
        
        for i in range(1, len(entries)):
            time_diff = (entries[i].startedDateTime - entries[i-1].startedDateTime).total_seconds()
            gaps.append(time_diff)
        
        return {
            "avg_response_time": sum(response_times) / len(response_times),
            "max_response_time": max(response_times),
            "min_response_time": min(response_times),
            "avg_gap_between_requests": sum(gaps) / len(gaps) if gaps else 0,
            "max_gap": max(gaps) if gaps else 0,
            "total_session_duration": (entries[-1].startedDateTime - entries[0].startedDateTime).total_seconds()
        }
    
    def _generate_recommendations(self, total_requests: int, request_types: Dict, 
                                static_summary: Dict, timing_analysis: Dict) -> List[str]:
        """Generate recommendations based on HAR analysis."""
        recommendations = []
        
        # Request volume recommendations
        if total_requests > 100:
            recommendations.append(
                f"High request count ({total_requests}). Consider using 'simulate' mode for static files to reduce test complexity."
            )
        
        # Static files recommendations
        static_count = request_types.get(RequestType.STATIC, 0)
        if static_count > 0:
            static_ratio = (static_count / total_requests) * 100
            if static_ratio > 50:
                recommendations.append(
                    f"High static files ratio ({static_ratio:.1f}%). Consider 'exclude' or 'group' mode for performance testing."
                )
            elif static_ratio > 20:
                recommendations.append(
                    "Moderate static files presence. Consider 'simulate' mode for realistic user experience testing."
                )
        
        # Timing recommendations
        avg_response = timing_analysis.get("avg_response_time", 0)
        if avg_response > 2000:  # >2 seconds
            recommendations.append(
                f"High average response time ({avg_response:.0f}ms). Consider increasing timeouts in test configuration."
            )
        
        # API vs UI recommendations
        api_count = request_types.get(RequestType.API, 0) + request_types.get(RequestType.AJAX, 0)
        if api_count > total_requests * 0.7:
            recommendations.append(
                "Mostly API traffic detected. Consider excluding static files for API performance testing."
            )
        
        return recommendations