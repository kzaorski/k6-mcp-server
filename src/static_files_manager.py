"""
Static Files Manager for HAR Processing.

This module handles intelligent classification, grouping, and simulation
of static files (CSS, JS, images, fonts) from HAR files for realistic
K6 load testing scenarios.
"""

import re
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urljoin

from har_models import (
    HAREntry, HARRequest, PageGroup, RequestType, StaticFilesHandling,
    StaticFilesLoadPattern, HARConversionOptions, StaticFilesConfig
)
from multi_request_models import RequestStep

logger = logging.getLogger(__name__)


class StaticFilesManager:
    """
    Manages static files detection, classification, and simulation
    for HAR to K6 conversion with realistic browser behavior.
    """
    
    def __init__(self, options: HARConversionOptions):
        self.options = options
        self.static_extensions = self._build_extension_patterns()
        self.critical_resources = {'*.css', '*.js'}  # Resources that block rendering
        
    def _build_extension_patterns(self) -> Set[str]:
        """Build set of static file extensions from patterns."""
        extensions = set()
        for pattern in self.options.static_file_patterns:
            if pattern.startswith('*.'):
                extensions.add(pattern[1:].lower())  # Remove '*.', keep extension
        return extensions
    
    def classify_request(self, entry: HAREntry) -> RequestType:
        """
        Classify HTTP request based on URL, headers, and response characteristics.
        
        Args:
            entry: HAR entry to classify
            
        Returns:
            RequestType enum value
        """
        request = entry.request
        response = entry.response
        
        # 1. Check if it's a static resource by URL extension
        if self._is_static_by_url(request.url):
            return RequestType.STATIC
        
        # 2. Check response content type
        if self._is_static_by_content_type(response):
            return RequestType.STATIC
        
        # 3. Check for AJAX/XHR requests
        if self._is_ajax_request(request):
            return RequestType.AJAX
        
        # 4. Check for API endpoints (JSON responses)
        if response.is_json_response():
            return RequestType.API
        
        # 5. Check for HTML pages
        if response.is_html_response():
            return RequestType.PAGE
        
        # 6. Check for redirects (might be authentication flows)
        if 300 <= response.status < 400:
            return RequestType.API  # Treat redirects as API for flow analysis
            
        return RequestType.UNKNOWN
    
    def _is_static_by_url(self, url: str) -> bool:
        """Check if URL indicates a static resource by file extension."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Check against configured extensions
        for ext in self.static_extensions:
            if path.endswith(ext):
                return True
        
        # Additional patterns for static resources
        static_patterns = [
            '/static/', '/assets/', '/css/', '/js/', '/images/', '/img/',
            '/fonts/', '/media/', '/public/', '/_next/static/', '/build/'
        ]
        
        return any(pattern in path for pattern in static_patterns)
    
    def _is_static_by_content_type(self, response) -> bool:
        """Check if response content type indicates static resource."""
        content_type = response.get_header('content-type')
        if not content_type:
            return False
        
        content_type_lower = content_type.lower()
        static_content_types = [
            'text/css', 'application/javascript', 'text/javascript',
            'application/x-javascript', 'image/', 'font/',
            'application/font', 'application/x-font', 'text/plain'  # Sometimes used for fonts
        ]
        
        return any(content_type_lower.startswith(ct) for ct in static_content_types)
    
    def _is_ajax_request(self, request: HARRequest) -> bool:
        """Check if request is AJAX/XHR based on headers."""
        # Standard XHR header
        if request.get_header('X-Requested-With') == 'XMLHttpRequest':
            return True
        
        # Fetch API indicators
        fetch_headers = ['sec-fetch-mode', 'sec-fetch-dest']
        for header_name in fetch_headers:
            header_value = request.get_header(header_name)
            if header_value and 'xhr' in header_value.lower():
                return True
        
        # Accept header indicating JSON preference
        accept = request.get_header('accept')
        if accept and 'application/json' in accept and 'text/html' not in accept:
            return True
        
        return False
    
    def detect_page_boundaries(self, entries: List[HAREntry]) -> List[PageGroup]:
        """
        Detect page boundaries and group requests by navigation events.
        
        Args:
            entries: List of HAR entries in chronological order
            
        Returns:
            List of PageGroup objects with grouped requests
        """
        if not entries:
            return []
        
        page_groups = []
        current_group = None
        last_request_time = None
        
        for entry in entries:
            request_time = entry.startedDateTime
            request_type = self.classify_request(entry)
            
            # Check if this starts a new page (HTML document)
            is_new_page = self._is_page_navigation(entry, last_request_time)
            
            if is_new_page:
                # Finish current group
                if current_group:
                    page_groups.append(current_group)
                
                # Start new group
                page_id = f"page_{len(page_groups) + 1}_{int(request_time.timestamp())}"
                current_group = PageGroup(
                    page_id=page_id,
                    main_request=entry,
                    start_time=request_time,
                    page_title=self._extract_page_title(entry)
                )
            
            elif current_group:
                # Add to current group if it belongs
                if self._belongs_to_current_page(entry, current_group):
                    current_group.add_request(entry)
                else:
                    # This might be a new page that doesn't look like navigation
                    # (e.g., AJAX navigation in SPAs)
                    if self._is_likely_new_page_ajax(entry, current_group):
                        if current_group:
                            page_groups.append(current_group)
                        
                        page_id = f"page_{len(page_groups) + 1}_{int(request_time.timestamp())}"
                        current_group = PageGroup(
                            page_id=page_id,
                            main_request=entry,
                            start_time=request_time
                        )
                    else:
                        current_group.add_request(entry)
            
            else:
                # No current group, start one with this entry
                page_id = f"page_1_{int(request_time.timestamp())}"
                current_group = PageGroup(
                    page_id=page_id,
                    main_request=entry,
                    start_time=request_time
                )
            
            last_request_time = request_time
        
        # Don't forget the last group
        if current_group:
            page_groups.append(current_group)
        
        return page_groups
    
    def _is_page_navigation(self, entry: HAREntry, last_request_time: Optional[datetime]) -> bool:
        """Check if entry represents a page navigation."""
        request_type = self.classify_request(entry)
        
        # HTML responses are usually page navigations
        if request_type == RequestType.PAGE:
            return True
        
        # Check for timing gap indicating user action
        if (last_request_time and self.options.detect_page_boundaries and
            (entry.startedDateTime - last_request_time).total_seconds() > self.options.timing_gap_threshold):
            return True
        
        # Check for navigation-indicating headers
        if entry.request.get_header('sec-fetch-mode') == 'navigate':
            return True
        
        return False
    
    def _belongs_to_current_page(self, entry: HAREntry, page_group: PageGroup) -> bool:
        """Check if entry belongs to the current page group."""
        # Time-based grouping - requests within reasonable time of page load
        time_diff = (entry.startedDateTime - page_group.start_time).total_seconds()
        if time_diff > 30:  # 30 seconds seems reasonable for page loading
            return False
        
        # Referrer-based grouping
        referrer = entry.request.get_header('referer') or entry.request.get_header('referrer')
        if referrer and referrer == page_group.main_request.request.url:
            return True
        
        # Domain-based grouping (same domain usually belongs together)
        main_domain = urlparse(page_group.main_request.request.url).netloc
        entry_domain = urlparse(entry.request.url).netloc
        if main_domain == entry_domain:
            return True
        
        return True  # Default: include in current group
    
    def _is_likely_new_page_ajax(self, entry: HAREntry, current_group: PageGroup) -> bool:
        """Check if AJAX request likely represents new page/view in SPA."""
        request_type = self.classify_request(entry)
        
        if request_type != RequestType.AJAX:
            return False
        
        # Large time gap might indicate user action
        time_diff = (entry.startedDateTime - current_group.start_time).total_seconds()
        if time_diff > 10:  # 10+ seconds might be new user action
            return True
        
        # Check for navigation-like URLs in AJAX
        url_lower = entry.request.url.lower()
        navigation_patterns = ['/page/', '/view/', '/route/', '/api/page']
        if any(pattern in url_lower for pattern in navigation_patterns):
            return True
        
        return False
    
    def _extract_page_title(self, entry: HAREntry) -> Optional[str]:
        """Extract page title from HTML response if available."""
        if entry.response.content.text and entry.response.is_html_response():
            content = entry.response.content.text
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
            if title_match:
                return title_match.group(1).strip()
        return None
    
    def process_static_files(self, page_groups: List[PageGroup]) -> List[PageGroup]:
        """
        Process static files according to configuration options.
        
        Args:
            page_groups: List of page groups with static files
            
        Returns:
            Modified page groups based on static files handling strategy
        """
        if self.options.static_files_handling == StaticFilesHandling.EXCLUDE:
            # Remove all static files
            for group in page_groups:
                group.static_requests = []
        
        elif self.options.static_files_handling == StaticFilesHandling.INCLUDE:
            # Keep all static files as-is
            pass
        
        elif self.options.static_files_handling == StaticFilesHandling.SIMULATE:
            # Create representative sample of static files
            for group in page_groups:
                group.static_requests = self._create_static_sample(group.static_requests)
        
        elif self.options.static_files_handling == StaticFilesHandling.GROUP:
            # Group static files for parallel loading
            for group in page_groups:
                group.static_requests = self._group_static_files(group.static_requests)
        
        return page_groups
    
    def _create_static_sample(self, static_requests: List[HAREntry]) -> List[HAREntry]:
        """Create representative sample of static files."""
        if not static_requests:
            return []
        
        # Group by type
        by_type = defaultdict(list)
        for request in static_requests:
            file_type = self._get_static_file_type(request.request.url)
            by_type[file_type].append(request)
        
        # Take samples from each type
        sample_requests = []
        max_per_type = max(1, self.options.max_static_files_per_page // max(1, len(by_type)))
        
        for file_type, requests in by_type.items():
            # Prioritize critical resources
            if file_type in ['css', 'js']:
                sample_size = min(len(requests), max_per_type * 2)  # More CSS/JS
            else:
                sample_size = min(len(requests), max_per_type)
            
            # Sort by size (larger files first) and take sample
            requests_sorted = sorted(requests, 
                                   key=lambda r: r.response.content.size, 
                                   reverse=True)
            sample_requests.extend(requests_sorted[:sample_size])
        
        return sample_requests[:self.options.max_static_files_per_page]
    
    def _group_static_files(self, static_requests: List[HAREntry]) -> List[HAREntry]:
        """Group static files for optimized parallel loading."""
        if not static_requests:
            return []
        
        # Separate critical from non-critical resources
        critical_requests = []
        non_critical_requests = []
        
        for request in static_requests:
            if self._is_critical_resource(request.request.url):
                critical_requests.append(request)
            else:
                non_critical_requests.append(request)
        
        # Limit total requests
        max_critical = self.options.max_static_files_per_page // 2
        max_non_critical = self.options.max_static_files_per_page - len(critical_requests[:max_critical])
        
        result = critical_requests[:max_critical] + non_critical_requests[:max_non_critical]
        return result
    
    def _get_static_file_type(self, url: str) -> str:
        """Get static file type from URL."""
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        if path.endswith(('.css',)):
            return 'css'
        elif path.endswith(('.js',)):
            return 'js'
        elif path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.avif')):
            return 'image'
        elif path.endswith(('.woff', '.woff2', '.ttf', '.eot')):
            return 'font'
        else:
            return 'other'
    
    def _is_critical_resource(self, url: str) -> bool:
        """Check if static resource is critical for page rendering."""
        file_type = self._get_static_file_type(url)
        return file_type in ['css', 'js']
    
    def generate_static_files_config(self, page_groups: List[PageGroup]) -> StaticFilesConfig:
        """Generate static files configuration for K6 script."""
        if self.options.static_files_handling == StaticFilesHandling.EXCLUDE:
            return StaticFilesConfig(enabled=False)
        
        total_static = sum(len(group.static_requests) for group in page_groups)
        
        return StaticFilesConfig(
            enabled=total_static > 0,
            load_pattern=self.options.static_files_load_pattern,
            parallel_loading=self.options.static_files_parallel,
            max_per_page=self.options.max_static_files_per_page,
            think_time=self.options.static_files_think_time,
            simulate_caching=False,  # Could be enhanced later
            priority_resources=list(self.critical_resources)
        )
    
    def calculate_realistic_timing(self, static_requests: List[HAREntry]) -> Dict[str, float]:
        """Calculate realistic timing patterns for static file loading."""
        if not static_requests:
            return {"think_time": 0.0, "total_load_time": 0.0}
        
        # Analyze actual timing from HAR
        response_times = [entry.timings.total_time for entry in static_requests]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        # Calculate realistic think time based on file loading patterns
        if self.options.static_files_load_pattern == StaticFilesLoadPattern.BURST:
            think_time = 0.1  # Quick burst loading
        elif self.options.static_files_load_pattern == StaticFilesLoadPattern.DISTRIBUTED:
            think_time = avg_response_time * 0.1  # 10% of avg response time
        else:  # REALISTIC
            think_time = self.options.static_files_think_time
        
        return {
            "think_time": think_time,
            "total_load_time": max(response_times) if response_times else 0,
            "avg_response_time": avg_response_time,
            "parallel_loading": self.options.static_files_parallel
        }
    
    def get_static_files_summary(self, page_groups: List[PageGroup]) -> Dict[str, any]:
        """Generate summary statistics for static files."""
        total_static = sum(len(group.static_requests) for group in page_groups)
        if total_static == 0:
            return {"total_static_files": 0, "handling_strategy": self.options.static_files_handling}
        
        # Group by file type
        type_counts = defaultdict(int)
        total_size = 0
        
        for group in page_groups:
            for request in group.static_requests:
                file_type = self._get_static_file_type(request.request.url)
                type_counts[file_type] += 1
                total_size += request.response.content.size
        
        return {
            "total_static_files": total_static,
            "handling_strategy": self.options.static_files_handling,
            "file_types": dict(type_counts),
            "total_size_bytes": total_size,
            "avg_size_bytes": total_size / total_static if total_static > 0 else 0,
            "pages_with_static": len([g for g in page_groups if g.static_files_count > 0])
        }