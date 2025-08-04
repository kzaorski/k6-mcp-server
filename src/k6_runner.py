import asyncio
import csv
import json
import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from urllib.parse import urlencode

from data_generators import DataGenerator

logger = logging.getLogger(__name__)

def convert_path_for_system(path: str) -> str:
    """Convert path format based on the current system."""
    import platform
    import os
    
    if not path:
        return path
    
    current_system = platform.system()
    logger.info(f"Current system: {current_system}, Platform release: {platform.release()}")
    
    if current_system == "Windows":
        # We're on native Windows
        if path.startswith('/mnt/c/'):
            # Convert WSL path to Windows: /mnt/c/Users/... -> C:\Users\...
            return 'C:\\' + path[7:].replace('/', '\\')
        elif path.startswith('/mnt/'):
            # Handle other drives: /mnt/d/... -> D:\...
            drive_letter = path[5:6].upper()
            return f'{drive_letter}:\\' + path[7:].replace('/', '\\')
        elif path.startswith('C:/') or path.startswith('c:/'):
            # Convert forward slashes to backslashes for Windows: C:/... -> C:\...
            return path.replace('/', '\\')
        # If already Windows format, return as-is
        return path
    
    elif current_system == "Linux" and "microsoft" in platform.release().lower():
        # We're in WSL - convert Windows paths to WSL format
        if path.startswith('C:\\') or path.startswith('c:\\'):
            # Convert C:\path to /mnt/c/path
            path = path.replace('\\', '/')
            if path.startswith('C:/'):
                return '/mnt/c/' + path[3:]
            elif path.startswith('c:/'):
                return '/mnt/c/' + path[3:]
        elif path.startswith('C:/') or path.startswith('c:/'):
            # Already in forward slash format, just convert drive
            if path.startswith('C:/'):
                return '/mnt/c/' + path[3:]
            elif path.startswith('c:/'):
                return '/mnt/c/' + path[3:]
    
    # For other Linux systems or unrecognized formats, return as-is
    return path


class K6TestResult(BaseModel):
    test_id: str
    timestamp: str
    config: Dict[str, Any]
    metrics: Dict[str, Any]
    success: bool
    error_message: Optional[str] = None


class K6Runner:
    def __init__(self):
        self.results_dir = Path(__file__).parent.parent / "reports"
        self.templates_dir = Path(__file__).parent / "templates"
        self.csv_data_dir = Path(__file__).parent.parent / "csv_data"
        self.results_dir.mkdir(exist_ok=True)
        self.csv_data_dir.mkdir(exist_ok=True)
        self.last_result: Optional[K6TestResult] = None
        self.pending_config = None
        
    def _format_test_parameters(self, config, test_id: str, csv_file_info: str = None) -> str:
        """Format test parameters for user confirmation."""
        logger.info(f"🚨 PREPARING (NOT EXECUTING) test parameters for test_id: {test_id}")
        logger.info(f"Config URL: {config.url}, Method: {config.method} - TEST NOT EXECUTED YET")
        
        params = f"""
=== K6 TEST CONFIGURATION PREVIEW ===
Test ID: {test_id}
URL: {config.url}
Method: {config.method}
Load Pattern: {config.load_pattern}

Execution:"""
        
        if config.iterations:
            params += f"""
• Iterations: {config.iterations}
• Virtual Users: {config.virtual_users}
• Total Requests: {config.iterations * config.virtual_users}"""
        else:
            params += f"""
• Duration: {config.duration}
• Virtual Users: {config.virtual_users}"""
        
        if config.headers:
            params += f"""

Headers:"""
            for key, value in config.headers.items():
                # Mask potential tokens/secrets
                if any(secret in key.lower() for secret in ['token', 'auth', 'key', 'secret']):
                    masked_value = value[:8] + '*' * (len(value) - 8) if len(value) > 8 else '*' * len(value)
                    params += f"""
• {key}: {masked_value}"""
                else:
                    params += f"""
• {key}: {value}"""
        
        if config.payload or config.payload_template:
            params += f"""

Payload:"""
            if config.payload_template:
                params += f"""
• Template: {config.payload_template}"""
            elif config.payload:
                params += f"""
• Static: {config.payload}"""
        
        if csv_file_info:
            params += f"""

Data Source:
• CSV File: {csv_file_info}"""
        
        if config.log_requests:
            params += f"""

Debug Options:
• Request Logging: ENABLED (detailed HTTP logs)"""
        
        params += f"""

Advanced:
• Timeout: {config.timeout}
• Retry Attempts: {config.retry_attempts}
• Think Time: {getattr(config, 'think_time', 1)} seconds (pause between requests)
======================================

🚨 TEST NOT EXECUTED YET - CONFIRMATION REQUIRED 🚨

PLEASE CONFIRM: Do you want to run this test?
Use confirm_and_execute_test tool with response: "y" or "n"

⚠️  The test will NOT run until you confirm with "y"
"""
        return params

    async def prepare_test(self, config) -> str:
        """Prepare a K6 test configuration and show parameters for confirmation. Does NOT execute the test."""
        test_id = f"test_{int(time.time())}"
        timestamp = datetime.now().isoformat()
        
        try:
            # Handle CSV file - find it and use directly (no copying)
            csv_local_path = None
            csv_file_info = None
            if config.data_file:
                try:
                    from pathlib import Path
                    
                    # First check if file exists in csv_data directory (uploaded via MCP)
                    csv_in_data_dir = self.csv_data_dir / config.data_file
                    if csv_in_data_dir.exists():
                        # Use file directly from csv_data directory
                        csv_local_path = csv_in_data_dir
                        file_size = csv_local_path.stat().st_size
                        csv_file_info = f"{config.data_file} ({file_size} bytes, csv_data/)"
                        logger.info(f"Using CSV file from csv_data directory: {csv_local_path}")
                    else:
                        # Try external path (legacy behavior)
                        file_path = convert_path_for_system(config.data_file)
                        logger.info(f"Path conversion for CSV: {config.data_file} -> {file_path}")
                        
                        source_path = Path(file_path)
                        if not source_path.exists():
                            # Check if it exists directly as specified
                            source_path = Path(config.data_file)
                            if not source_path.exists():
                                raise FileNotFoundError(f"CSV file not found in csv_data directory ({csv_in_data_dir}) or external path ({config.data_file})")
                        
                        csv_local_path = source_path
                        file_size = csv_local_path.stat().st_size
                        csv_file_info = f"{config.data_file} ({file_size} bytes, external)"
                        logger.info(f"Using CSV file from external path: {csv_local_path}")
                    
                except Exception as e:
                    logger.error(f"Error finding CSV file: {str(e)}")
                    return f"Error finding CSV file: {str(e)}"
            
            # ALWAYS show confirmation dialog - no exceptions
            logger.info("🚨 ALWAYS requiring confirmation - NO TEST EXECUTION HERE")
            # Show test configuration and ask for confirmation
            logger.info("🚨 PREPARING test configuration for user confirmation - NOT EXECUTING")
            confirmation_prompt = self._format_test_parameters(config, test_id, csv_file_info)
            confirmation_prompt += f"\n\nTest ID for confirmation: {test_id}"
            
            # Store test configuration for later execution
            self.pending_config = {
                'config': config,
                'test_id': test_id,
                'csv_local_path': csv_local_path
            }
            
            # Return confirmation prompt - user must respond to continue
            logger.info(f"Returning confirmation prompt (length: {len(confirmation_prompt)})")
            return confirmation_prompt
            
        except Exception as e:
            logger.error(f"Error preparing test: {str(e)}")
            return f"Error preparing test: {str(e)}"
    
    async def confirm_test_execution(self, response: str) -> str:
        """Handle test confirmation response."""
        if not self.pending_config:
            return "No pending test to confirm. Please run run_k6_test first."
        
        response_lower = response.lower()
        if response_lower in ['y', 'yes']:
            # Execute the pending test
            config = self.pending_config['config']
            test_id = self.pending_config['test_id']
            csv_local_path = self.pending_config['csv_local_path']
            
            # Clear pending config
            self.pending_config = None
            
            # Execute test
            return await self._execute_test(config, test_id, csv_local_path)
        
        elif response_lower in ['n', 'no']:
            # Cancel test
            self.pending_config = None
            return "Test execution cancelled by user."
        
        else:
            return f"Invalid response '{response}'. Please respond with 'y' (yes) or 'n' (no)."
    
    async def _execute_test(self, config, test_id: str, csv_local_path = None) -> str:
        """Execute the K6 test (internal method)."""
        timestamp = datetime.now().isoformat()
        
        try:
            # Generate K6 script
            script_content = self._generate_script(config, test_id, csv_local_path)
            
            # Write script to local file in reports directory with UTF-8 encoding
            script_path = self.results_dir / f"k6_test_{test_id}.js"
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            # Prepare K6 command with relative paths (since we're running from reports dir)
            script_filename = f"k6_test_{test_id}.js"
            results_filename = f"{test_id}_results.json"
            summary_filename = f"{test_id}_summary.json"
            
            cmd = [
                "k6", "run", 
                "--out", f"json={results_filename}",
                "--summary-export", summary_filename,
                script_filename
            ]
            
            logger.info(f"Running K6 command: {' '.join(cmd)}")
            
            # Run K6 test from the reports directory so relative paths work
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.results_dir)  # Change working directory to reports
            )
            
            stdout, stderr = await process.communicate()
            
            # Decode output with proper encoding
            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""
            
            if process.returncode == 0:
                # Parse and format results
                metrics = await self._parse_results(test_id)
                
                # Determine actual success based on error rates and checks, not just process exit code
                actual_success = True
                failure_reasons = []
                
                # Check error rate
                if 'error_rate_raw' in metrics and metrics['error_rate_raw'] > 0:
                    actual_success = False
                    failure_reasons.append(f"High error rate: {metrics['error_rate']}")
                
                # Check failed checks
                if 'checks_failed' in metrics and metrics['checks_failed'] > 0:
                    if 'check_details' in metrics:
                        for check_name, details in metrics['check_details'].items():
                            if details['fails'] > 0:
                                failure_reasons.append(f"Check failed: '{check_name}' ({details['fails']} failures)")
                
                # Check if thresholds were violated (if any were set)
                if config.thresholds:
                    # This would require more complex threshold checking logic
                    # For now, we rely on K6's built-in threshold handling
                    pass
                
                self.last_result = K6TestResult(
                    test_id=test_id,
                    timestamp=timestamp,
                    config=config.dict(),
                    metrics=metrics,
                    success=actual_success,
                    error_message='; '.join(failure_reasons) if failure_reasons else None
                )
                
                return self._format_report(self.last_result)
            else:
                error_msg = stderr_text or "Unknown error"
                logger.error(f"K6 test failed: {error_msg}")
                
                self.last_result = K6TestResult(
                    test_id=test_id,
                    timestamp=timestamp,
                    config=config.dict(),
                    metrics={},
                    success=False,
                    error_message=error_msg
                )
                
                return f"Test failed: {error_msg}"
                
        except Exception as e:
            logger.error(f"Error running K6 test: {str(e)}")
            return f"Error running test: {str(e)}"
    
    def _generate_script(self, config, test_id: str, csv_file_path: Optional[Path] = None) -> str:
        """Generate K6 script based on configuration and template."""
        template_map = {
            "constant": "constant_load.js",
            "ramp_up": "ramp_up.js", 
            "spike": "spike.js"
        }
        
        template_name = template_map.get(config.load_pattern, "constant_load.js")
        template_path = self.templates_dir / template_name
        
        # Read template
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        # Process dynamic data and variables
        script_vars = self._process_dynamic_data(config)
        
        # Build final URL with query parameters
        final_url = self._build_url_with_params(config.url, config.query_params)
        
        # Basic template substitution (but not URL yet)
        script = template.replace('{{method_lower}}', config.method.lower())
        script = script.replace('{{method_upper}}', config.method.upper())
        script = script.replace('{{load_pattern}}', config.load_pattern)
        script = script.replace('{{virtual_users}}', str(config.virtual_users))
        script = script.replace('{{duration}}', config.duration)
        script = script.replace('{{timeout}}', config.timeout or '30s')
        script = script.replace('{{retry_attempts}}', str(config.retry_attempts or 0))
        script = script.replace('{{think_time}}', str(config.think_time or 1))
        
        # Handle ramp_up specific variables
        if config.load_pattern == "ramp_up":
            ramp_duration = "30s"  # Default ramp time
            script = script.replace('{{ramp_duration}}', ramp_duration)
        
        # Handle spike specific variables  
        if config.load_pattern == "spike":
            base_users = max(1, config.virtual_users // 4)
            spike_users = config.virtual_users * 3
            script = script.replace('{{base_users}}', str(base_users))
            script = script.replace('{{spike_users}}', str(spike_users))
        
        # Handle custom headers
        script = self._process_headers(script, config.headers)
        
        # Handle authentication
        script = self._process_auth(script, config.auth)
        
        # Handle cookies
        script = self._process_cookies(script, config.cookies)
        
        # Add CSV data loading FIRST (before payload processing)
        if csv_file_path and csv_file_path.exists():
            script = self._inject_csv_loading(script, csv_file_path)
        
        # Handle payload (including template processing)
        script = self._process_payload(script, config, script_vars)
        
        # Handle request logging
        script = self._process_request_logging(script, config.log_requests or False)
        
        # Handle thresholds
        script = self._process_thresholds(script, config.thresholds)
        
        # Handle checks (only add if user specified thresholds or specifically requested checks)
        script = self._process_checks(script, config.thresholds)
        
        # Handle execution mode (iterations vs duration)
        script = self._process_execution_mode(script, config)
        
        # Add environment variables and dynamic data to script (without CSV now)
        script = self._inject_script_variables(script, script_vars, config.env_variables)
        
        # Replace test_id in templates
        script = script.replace('{{test_id}}', test_id)
        
        # Replace URL last to avoid conflicts
        script = script.replace('{{url}}', final_url)
        
        return script
    
    def _process_request_logging(self, script: str, log_requests: bool) -> str:
        """Process request logging configuration."""
        if not log_requests:
            script = script.replace('{{request_logging_block}}', '')
            return script
        
        logging_block = """
  // REQUEST LOGGING - Detailed request information
  console.log('\\n=== REQUEST DETAILS ===');
  console.log('URL:', '{{url}}');
  console.log('Method:', '{{method_upper}}');
  console.log('Headers:', JSON.stringify(params.headers, null, 2));
  if (typeof payload !== 'undefined') {
    console.log('Payload:', payload);
  }
  console.log('Timeout:', params.timeout);
  console.log('=======================\\n');"""
        
        script = script.replace('{{request_logging_block}}', logging_block)
        return script
    
    def _process_thresholds(self, script: str, thresholds: Optional[Dict[str, str]]) -> str:
        """Process thresholds in the script."""
        if not thresholds:
            script = script.replace('{{thresholds_block}}', '')
            return script
        
        thresholds_js = []
        for key, value in thresholds.items():
            thresholds_js.append(f"    '{key}': ['{value}']")
        thresholds_str = ',\n'.join(thresholds_js)
        
        thresholds_block = f"thresholds: {{\n{thresholds_str}\n  }},"
        script = script.replace('{{thresholds_block}}', thresholds_block)
        
        return script
    
    def _process_execution_mode(self, script: str, config) -> str:
        """Process execution mode - iterations vs duration."""
        if config.iterations is not None:
            # Use iterations mode
            execution_block = f"iterations: {config.iterations},"
        else:
            # Use duration mode (default)
            duration = config.duration or "30s"
            execution_block = f"duration: '{duration}',"
        
        script = script.replace('{{execution_mode_block}}', execution_block)
        return script
    
    def _process_checks(self, script: str, thresholds: Optional[Dict[str, str]]) -> str:
        """Process checks - only add if user specified thresholds (indicating they want validation)."""
        if not thresholds:
            # No thresholds = no automatic checks
            script = script.replace('{{checks_block}}', '')
            return script
        
        # User specified thresholds, so add basic checks
        checks_block = """check(response, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
    'response time < 1000ms': (r) => r.timings.duration < 1000,
    'response time < 2000ms': (r) => r.timings.duration < 2000,
  });"""
        
        script = script.replace('{{checks_block}}', checks_block)
        return script
    
    def _process_dynamic_data(self, config) -> Dict[str, Any]:
        """Process dynamic data generators and file data."""
        script_vars = {}
        
        # Generate data from generators config
        if config.data_generators:
            generated = DataGenerator.generate_data_from_config(config.data_generators)
            script_vars.update(generated)
        
        # Load data from file
        if config.data_file:
            # Convert path for current system
            converted_path = convert_path_for_system(config.data_file)
            logger.info(f"Path conversion for data loading: {config.data_file} -> {converted_path}")
            file_data = DataGenerator.process_data_file(converted_path)
            if file_data:
                # Store file path and data for K6 CSV processing
                script_vars['csv_file_path'] = converted_path
                script_vars['file_data'] = file_data
                
                # Get column names for template usage
                if len(file_data) > 0:
                    column_names = list(file_data[0].keys())
                    script_vars['csv_columns'] = column_names
                    # Still provide first value for compatibility with templates
                    script_vars.update(file_data[0])
        
        return script_vars
    
    def _build_url_with_params(self, base_url: str, query_params: Optional[Dict[str, str]]) -> str:
        """Build URL with query parameters."""
        if not query_params:
            return base_url
        
        separator = '&' if '?' in base_url else '?'
        query_string = urlencode(query_params)
        return f"{base_url}{separator}{query_string}"
    
    def _process_headers(self, script: str, headers: Optional[Dict[str, str]]) -> str:
        """Process custom headers in the script."""
        if not headers:
            script = script.replace('{{custom_headers_block}}', '')
            return script
        
        headers_js = []
        for key, value in headers.items():
            headers_js.append(f"      '{key}': '{value}'")
        headers_str = ',\n'.join(headers_js)
        
        script = script.replace('{{custom_headers_block}}', headers_str + ',')
        return script
    
    def _process_auth(self, script: str, auth: Optional[Dict[str, Any]]) -> str:
        """Process authentication in the script."""
        if not auth:
            script = script.replace('{{auth_header_block}}', '')
            return script
        
        auth_type = auth.get('type', '')
        auth_header = ''
        
        if auth_type == 'bearer':
            token = auth.get('token', '')
            auth_header = f"      'Authorization': 'Bearer {token}'"
        elif auth_type == 'basic':
            username = auth.get('username', '')
            password = auth.get('password', '')
            import base64
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            auth_header = f"      'Authorization': 'Basic {credentials}'"
        elif auth_type == 'apikey':
            token = auth.get('token', '')
            header_name = auth.get('header_name', 'X-API-Key')
            auth_header = f"      '{header_name}': '{token}'"
        
        script = script.replace('{{auth_header_block}}', auth_header + ',')
        return script
    
    def _process_cookies(self, script: str, cookies: Optional[Dict[str, str]]) -> str:
        """Process cookies in the script."""
        if not cookies:
            script = script.replace('{{cookies_block}}', '')
            return script
        
        cookie_pairs = [f"{key}={value}" for key, value in cookies.items()]
        cookie_string = '; '.join(cookie_pairs)
        
        cookies_block = f"cookies: {{\n      Cookie: '{cookie_string}'\n    }},"
        script = script.replace('{{cookies_block}}', cookies_block)
        return script
    
    def _process_payload(self, script: str, config, script_vars: Dict[str, Any]) -> str:
        """Process payload including template interpolation."""
        payload_json = '{}'
        has_csv_data = 'csv_file_path' in script_vars
        
        # Use payload_template if provided, otherwise use regular payload
        if config.payload_template:
            if has_csv_data:
                # For CSV data, create dynamic payload that uses csvData array
                # Replace template variables with CSV data access
                payload_js = config.payload_template.replace('{{WER}}', 'csvRecord.WER')
                
                payload_block = f"""// Select random CSV record
  const csvRecord = csvData[Math.floor(Math.random() * csvData.length)];
  
  const payload = JSON.stringify({payload_js});
  const response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"""
                retry_block = f"response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
            else:
                # No CSV data - use regular template interpolation
                payload_str = DataGenerator.interpolate_variables(config.payload_template, script_vars)
                try:
                    # Try to parse as JSON to validate structure
                    json.loads(payload_str)
                    # If valid JSON, use directly as JavaScript object
                    payload_block = f"const payload = JSON.stringify({payload_str});\n  const response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON in payload template, using as string")
                    # If not valid JSON, treat as string and encode it
                    payload_json = json.dumps(payload_str)
                    payload_block = f"const payload = JSON.stringify({payload_json});\n  const response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
                
                retry_block = f"response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
        elif config.payload:
            payload_json = json.dumps(config.payload)
            payload_block = f"const payload = JSON.stringify({payload_json});\n  const response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
            retry_block = f"response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
        else:
            payload_block = f"const response = http.{config.method.lower()}('{{{{url}}}}', params);"
            retry_block = f"response = http.{config.method.lower()}('{{{{url}}}}', params);"
        
        script = script.replace('{{payload_block}}', payload_block)
        script = script.replace('{{retry_block}}', retry_block)
        
        return script
    
    def _inject_csv_loading(self, script: str, csv_file_path: Path) -> str:
        """Inject CSV loading code at the beginning of the script."""
        # Calculate relative path from reports directory to CSV file
        # K6 runs from reports/, so we need to go up one level to reach csv_data/
        if csv_file_path.parent.name == "csv_data":
            # CSV is in csv_data directory - go up one level from reports to reach it
            relative_csv_path = f"../csv_data/{csv_file_path.name}"
        else:
            # External CSV file - use absolute path
            relative_csv_path = str(csv_file_path.resolve())
        
        csv_setup = f"""// CSV Data Loading
import papaparse from 'https://jslib.k6.io/papaparse/5.1.1/index.js';
import {{ SharedArray }} from 'k6/data';

const csvData = new SharedArray('csv data', function () {{
  return papaparse.parse(open('{relative_csv_path}'), {{ header: true }}).data;
}});

"""
        # Add CSV imports to the beginning of the script
        logger.info(f"Using CSV path in K6 script: {relative_csv_path} (K6 runs from reports/ directory)")
        return csv_setup + script
    
    def _inject_script_variables(self, script: str, script_vars: Dict[str, Any], env_vars: Optional[Dict[str, str]]) -> str:
        """Inject environment variables and dynamic data into script."""
        # Add environment variables setup
        if env_vars:
            env_setup = "// Environment variables\n"
            for key, value in env_vars.items():
                env_setup += f"const {key} = __ENV.{key} || '{value}';\n"
            script = env_setup + "\n" + script
        
        # Add dynamic variables setup (skip CSV-related vars since CSV is handled separately)
        if script_vars:
            vars_setup = "// Dynamic variables\n"
            for key, value in script_vars.items():
                if key not in ['file_data', 'csv_file_path', 'csv_columns']:  # Skip CSV-related data
                    if isinstance(value, str):
                        vars_setup += f"const {key} = '{value}';\n"
                    else:
                        vars_setup += f"const {key} = {json.dumps(value)};\n"
            
            # Only add vars_setup if there are any non-CSV variables
            if vars_setup.strip() != "// Dynamic variables":
                script = vars_setup + "\n" + script
        
        return script
    
    async def _parse_results(self, test_id: str) -> Dict[str, Any]:
        """Parse K6 results from JSON files."""
        summary_file = self.results_dir / f"{test_id}_summary.json"
        
        if not summary_file.exists():
            return {}
        
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            
            metrics = {}
            
            # Extract key metrics
            if 'metrics' in summary:
                metrics_data = summary['metrics']
                
                # HTTP request duration
                if 'http_req_duration' in metrics_data:
                    duration = metrics_data['http_req_duration']
                    metrics['response_time'] = {
                        'avg': f"{duration.get('avg', 0):.2f}ms",
                        'min': f"{duration.get('min', 0):.2f}ms", 
                        'max': f"{duration.get('max', 0):.2f}ms",
                        'p50': f"{duration.get('med', 0):.2f}ms",
                        'p90': f"{duration.get('p(90)', 0):.2f}ms",
                        'p95': f"{duration.get('p(95)', 0):.2f}ms",
                        'p99': f"{duration.get('p(99)', 0):.2f}ms"
                    }
                    # Store raw values for CSV export
                    metrics['response_time_raw'] = {
                        'avg': duration.get('avg', 0),
                        'min': duration.get('min', 0),
                        'max': duration.get('max', 0),
                        'p50': duration.get('med', 0),
                        'p90': duration.get('p(90)', 0),
                        'p95': duration.get('p(95)', 0),
                        'p99': duration.get('p(99)', 0)
                    }
                
                # HTTP requests per second
                if 'http_reqs' in metrics_data:
                    reqs = metrics_data['http_reqs']
                    metrics['throughput'] = f"{reqs.get('rate', 0):.2f} req/s"
                    metrics['total_requests'] = reqs.get('count', 0)
                    metrics['throughput_raw'] = reqs.get('rate', 0)
                
                # HTTP request failed rate
                if 'http_req_failed' in metrics_data:
                    failed = metrics_data['http_req_failed']
                    # K6 uses 'value' for the failure rate (0.0-1.0), not 'rate'
                    error_rate = failed.get('value', 0)
                    metrics['error_rate'] = f"{error_rate*100:.2f}%"
                    metrics['error_rate_raw'] = error_rate * 100
                    # For failed request count, we need to calculate from total requests
                    total_requests = metrics_data.get('http_reqs', {}).get('count', 0)
                    metrics['failed_requests'] = int(total_requests * error_rate)
                    metrics['success_requests'] = total_requests - metrics['failed_requests']
                
                # Virtual users
                if 'vus' in metrics_data:
                    vus = metrics_data['vus']
                    metrics['virtual_users'] = vus.get('max', 0)
                
                # Data received/sent
                if 'data_received' in metrics_data:
                    received = metrics_data['data_received']
                    metrics['data_received'] = f"{received.get('count', 0)/1024:.2f} KB"
                    metrics['data_received_raw'] = received.get('count', 0)
                
                if 'data_sent' in metrics_data:
                    sent = metrics_data['data_sent']
                    metrics['data_sent'] = f"{sent.get('count', 0)/1024:.2f} KB"
                    metrics['data_sent_raw'] = sent.get('count', 0)
                
                # Additional detailed metrics
                if 'http_req_waiting' in metrics_data:
                    waiting = metrics_data['http_req_waiting']
                    metrics['waiting_time_raw'] = {
                        'avg': waiting.get('avg', 0),
                        'min': waiting.get('min', 0),
                        'max': waiting.get('max', 0),
                        'p95': waiting.get('p(95)', 0)
                    }
                
                if 'http_req_connecting' in metrics_data:
                    connecting = metrics_data['http_req_connecting']
                    metrics['connection_time_raw'] = {
                        'avg': connecting.get('avg', 0),
                        'max': connecting.get('max', 0)
                    }
            
            # Test duration
            if 'state' in summary:
                metrics['test_duration'] = summary['state'].get('testRunDurationMs', 0) / 1000
            
            # Add check results for better error reporting
            if 'root_group' in summary and 'checks' in summary['root_group']:
                checks = summary['root_group']['checks']
                total_checks = sum(check.get('passes', 0) + check.get('fails', 0) for check in checks.values())
                failed_checks = sum(check.get('fails', 0) for check in checks.values())
                
                metrics['checks_total'] = total_checks
                metrics['checks_failed'] = failed_checks
                metrics['checks_passed'] = total_checks - failed_checks
                metrics['checks_success_rate'] = (total_checks - failed_checks) / total_checks * 100 if total_checks > 0 else 100
                
                # Detail specific check failures
                metrics['check_details'] = {}
                for check_name, check_data in checks.items():
                    metrics['check_details'][check_name] = {
                        'passes': check_data.get('passes', 0),
                        'fails': check_data.get('fails', 0),
                        'success_rate': check_data.get('passes', 0) / (check_data.get('passes', 0) + check_data.get('fails', 0)) * 100 if (check_data.get('passes', 0) + check_data.get('fails', 0)) > 0 else 100
                    }
            
            # Extract detailed error information from raw results
            raw_results_file = self.results_dir / f"{test_id}_results.json"
            if raw_results_file.exists():
                error_details = await self._extract_error_details(raw_results_file)
                metrics.update(error_details)
            
            # Process handleSummary outputs if available
            standard_reports = await self._process_standard_reports(test_id)
            if standard_reports:
                metrics.update(standard_reports)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error parsing results: {str(e)}")
            return {}
    
    def _format_report(self, result: K6TestResult) -> str:
        """Format test results into a readable report."""
        
        metrics = result.metrics
        config = result.config
        
        # Determine report header based on success/failure
        status_icon = "✅" if result.success else "❌"
        status_text = "SUCCESS" if result.success else "FAILED"
        
        report = f"""
{status_icon} K6 Performance Test Report - {status_text}
═══════════════════════════════════════

📊 Test Configuration:
• URL: {config.get('url')}
• Method: {config.get('method')}
• Load Pattern: {config.get('load_pattern')}
• Duration: {config.get('duration')}
• Virtual Users: {config.get('virtual_users')}

📈 Performance Metrics:
"""
        
        if 'response_time' in metrics:
            rt = metrics['response_time']
            report += f"""
⏱️  Response Times:
• Average: {rt.get('avg')}
• Minimum: {rt.get('min')}
• Maximum: {rt.get('max')}
• 95th Percentile: {rt.get('p95')}
"""
        
        if 'throughput' in metrics:
            report += f"""
🚀 Throughput:
• Requests/sec: {metrics.get('throughput')}
• Total Requests: {metrics.get('total_requests')}
"""
        
        if 'error_rate' in metrics:
            error_rate_raw = metrics.get('error_rate_raw', 0)
            status_emoji = '✅' if error_rate_raw == 0 else '⚠️' if error_rate_raw < 5 else '🚨'
            report += f"""
{status_emoji} Error Analysis:
• Error Rate: {metrics.get('error_rate')}
• Failed Requests: {metrics.get('failed_requests', 'N/A')}
• Successful Requests: {metrics.get('success_requests', 'N/A')}
"""
            
            # Add detailed error information if available
            if 'error_messages' in metrics and metrics['error_messages']:
                report += "\n🔍 Error Details:\n"
                for message in metrics['error_messages']:
                    report += f"• {message}\n"
            
            # Add status code distribution
            if 'status_code_distribution' in metrics and metrics['status_code_distribution']:
                report += "\n📊 HTTP Status Codes:\n"
                for status, count in metrics['status_code_distribution'].items():
                    report += f"• {status}: {count} requests\n"
            
            # Add most common errors
            if 'most_common_errors' in metrics and metrics['most_common_errors']:
                report += "\n⚠️ Most Common Errors:\n"
                for error_code, details in list(metrics['most_common_errors'].items())[:3]:
                    report += f"• {error_code}: {details['count']} occurrences - {details['description']}\n"
            
            # Add error timeline sample
            if 'error_timeline' in metrics and metrics['error_timeline']:
                report += "\n⏰ First Few Errors:\n"
                for i, error in enumerate(metrics['error_timeline'][:3]):
                    timestamp = error['timestamp'][:19] if len(error['timestamp']) > 19 else error['timestamp']
                    report += f"• {timestamp}: {error['method']} {error['url']} → {error['status_code']} (K6: {error['error_code']})\n"
            
            # Add check details if available
            if 'check_details' in metrics:
                report += "\n📋 Check Results:\n"
                for check_name, details in metrics['check_details'].items():
                    status = '✅' if details['fails'] == 0 else '❌'
                    report += f"• {status} {check_name}: {details['passes']} passed, {details['fails']} failed\n"
        
        if 'data_received' in metrics:
            report += f"""
📦 Data Transfer:
• Received: {metrics.get('data_received')}
• Sent: {metrics.get('data_sent')}
"""
        
        if 'test_duration' in metrics:
            report += f"""
⏰ Test Duration: {metrics.get('test_duration')}s
"""
        
        # Add K6 standard reports information if available
        if 'standard_reports_available' in metrics and metrics['standard_reports_available']:
            report += f"\n📊 K6 Standard Reports Available:\n"
            for report_file in metrics.get('report_files', []):
                report += f"• {report_file}\n"
            
            # Add LLM-optimized summary key points
            if 'llm_optimized_summary' in metrics and metrics['llm_optimized_summary']:
                llm_summary = metrics['llm_optimized_summary']
                if 'quality_assessment' in llm_summary:
                    qa = llm_summary['quality_assessment']
                    report += f"\n🎆 K6 Quality Assessment:\n"
                    report += f"• Grade: {qa.get('performance_grade', 'N/A')}\n"
                    report += f"• Status: {qa.get('overall_status', 'unknown').upper()}\n"
                    if qa.get('recommendations'):
                        report += f"• Recommendations: {len(qa['recommendations'])} available\n"
        
        # Add overall test status
        overall_status = '✅ PASSED' if result.success else '❌ FAILED'
        report += f"\n📊 Overall Test Status: {overall_status}\n"
        
        if not result.success and result.error_message:
            report += f"🚨 Failure Reasons: {result.error_message}\n"
        
        report += f"""
🆔 Test ID: {result.test_id}
🕐 Timestamp: {result.timestamp}
"""
        
        # Add reference to safety instructions for failed tests
        if not result.success:
            report += f"""

🚨 CRITICAL: This test failed and requires careful interpretation
📋 Please consult the AI Safety Instructions (available as MCP resource: file://AI_SAFETY_CRITICAL.md)
⚠️  Remember: Failed tests measure real system performance, not test configuration issues
"""
        
        return report
    
    async def get_results(self, test_id: Optional[str] = None) -> str:
        """Get test results for a specific test or the last test."""
        if test_id:
            # Load specific test results
            summary_file = self.results_dir / f"{test_id}_summary.json"
            if not summary_file.exists():
                return f"No results found for test ID: {test_id}"
            
            try:
                with open(summary_file, 'r', encoding='utf-8') as f:
                    summary = json.load(f)
                
                # Create a mock result object for formatting
                mock_result = K6TestResult(
                    test_id=test_id,
                    timestamp="N/A",
                    config={},
                    metrics=await self._parse_results(test_id),
                    success=True
                )
                
                return self._format_report(mock_result)
            except Exception as e:
                return f"Error loading results: {str(e)}"
        
        elif self.last_result:
            return self._format_report(self.last_result)
        else:
            return "No test results available. Run a test first."
    
    async def list_templates(self) -> str:
        """List available test templates."""
        templates = [
            "📊 Available K6 Test Templates:",
            "",
            "1. 🔄 constant - Constant load testing",
            "   • Maintains steady number of virtual users",
            "   • Good for baseline performance testing",
            "",
            "2. 📈 ramp_up - Gradual load increase",
            "   • Gradually increases virtual users",
            "   • Good for finding performance breaking points",
            "",
            "3. ⚡ spike - Spike load testing",
            "   • Sudden traffic spikes", 
            "   • Tests system resilience under stress",
            "",
            "💡 Use these patterns with the 'load_pattern' parameter in run_k6_test"
        ]
        
        return "\n".join(templates)
    
    async def _extract_error_details(self, raw_results_file: Path) -> Dict[str, Any]:
        """Extract detailed error information from K6 raw JSON results."""
        error_details = {
            'error_breakdown': {},
            'status_code_distribution': {},
            'error_timeline': [],
            'unique_errors': set(),
            'error_messages': [],
            'most_common_errors': {},
            'error_by_endpoint': {}
        }
        
        try:
            with open(raw_results_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f):
                    try:
                        data = json.loads(line.strip())
                        
                        # Only process http_req_failed metrics (these contain error info)
                        if (data.get('type') == 'Point' and 
                            data.get('metric') == 'http_req_failed' and 
                            data.get('data', {}).get('value') == 1):
                            
                            tags = data.get('data', {}).get('tags', {})
                            timestamp = data.get('data', {}).get('time', '')
                            
                            # Extract error information
                            error_code = tags.get('error_code', 'unknown')
                            status_code = tags.get('status', 'unknown')
                            method = tags.get('method', 'unknown')
                            url = tags.get('url', 'unknown')
                            expected_response = tags.get('expected_response', 'unknown')
                            
                            # Build error breakdown by error code
                            if error_code not in error_details['error_breakdown']:
                                error_details['error_breakdown'][error_code] = {
                                    'count': 0,
                                    'status_codes': set(),
                                    'endpoints': set(),
                                    'methods': set(),
                                    'first_occurrence': timestamp,
                                    'description': self._get_error_description(error_code, status_code)
                                }
                            
                            error_details['error_breakdown'][error_code]['count'] += 1
                            error_details['error_breakdown'][error_code]['status_codes'].add(status_code)
                            error_details['error_breakdown'][error_code]['endpoints'].add(url)
                            error_details['error_breakdown'][error_code]['methods'].add(method)
                            
                            # Status code distribution
                            status_key = f"{status_code} ({self._get_status_description(status_code)})"
                            error_details['status_code_distribution'][status_key] = \
                                error_details['status_code_distribution'].get(status_key, 0) + 1
                            
                            # Error timeline (sample first 10 errors)
                            if len(error_details['error_timeline']) < 10:
                                error_details['error_timeline'].append({
                                    'timestamp': timestamp,
                                    'error_code': error_code,
                                    'status_code': status_code,
                                    'method': method,
                                    'url': url,
                                    'expected_response': expected_response
                                })
                            
                            # Track unique error patterns
                            error_pattern = f"{error_code}:{status_code}:{method}"
                            error_details['unique_errors'].add(error_pattern)
                            
                            # Error by endpoint
                            endpoint_key = f"{method} {url}"
                            if endpoint_key not in error_details['error_by_endpoint']:
                                error_details['error_by_endpoint'][endpoint_key] = {
                                    'count': 0,
                                    'error_codes': set(),
                                    'status_codes': set()
                                }
                            error_details['error_by_endpoint'][endpoint_key]['count'] += 1
                            error_details['error_by_endpoint'][endpoint_key]['error_codes'].add(error_code)
                            error_details['error_by_endpoint'][endpoint_key]['status_codes'].add(status_code)
                            
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.warning(f"Error processing line {line_num}: {str(e)}")
                        continue
            
            # Convert sets to lists for JSON serialization
            for error_code, details in error_details['error_breakdown'].items():
                details['status_codes'] = list(details['status_codes'])
                details['endpoints'] = list(details['endpoints'])
                details['methods'] = list(details['methods'])
            
            for endpoint, details in error_details['error_by_endpoint'].items():
                details['error_codes'] = list(details['error_codes'])
                details['status_codes'] = list(details['status_codes'])
            
            error_details['unique_errors'] = list(error_details['unique_errors'])
            
            # Find most common errors
            if error_details['error_breakdown']:
                sorted_errors = sorted(error_details['error_breakdown'].items(), 
                                     key=lambda x: x[1]['count'], reverse=True)
                error_details['most_common_errors'] = dict(sorted_errors[:5])  # Top 5
            
            # Generate human-readable error messages
            error_details['error_messages'] = self._generate_error_messages(error_details)
            
        except Exception as e:
            logger.error(f"Error extracting error details: {str(e)}")
        
        return error_details
    
    def _get_error_description(self, error_code: str, status_code: str) -> str:
        """Get human-readable description for K6 error codes and HTTP status codes."""
        # K6 Error codes (from K6 documentation)
        k6_errors = {
            '1000': 'Generic error',
            '1001': 'Connection refused',
            '1002': 'Connection reset',
            '1003': 'DNS resolution failed', 
            '1004': 'TLS handshake failed',
            '1005': 'Request timeout',
            '1006': 'Response timeout',
            '1007': 'Too many redirects',
            '1100': 'Generic HTTP error',
            '1101': 'HTTP request failed',
            '1201': 'WebSocket connection failed',
            '1401': 'HTTP 401 Unauthorized - Authentication required',
            '1403': 'HTTP 403 Forbidden - Access denied',
            '1404': 'HTTP 404 Not Found - Resource not found',
            '1500': 'HTTP 500 Internal Server Error - Server error',
            '1502': 'HTTP 502 Bad Gateway - Gateway error',
            '1503': 'HTTP 503 Service Unavailable - Service unavailable',
            '1504': 'HTTP 504 Gateway Timeout - Gateway timeout'
        }
        
        # HTTP Status descriptions
        http_status = {
            '400': 'Bad Request - Invalid request syntax',
            '401': 'Unauthorized - Authentication required',
            '403': 'Forbidden - Access denied to resource',
            '404': 'Not Found - Resource does not exist',
            '405': 'Method Not Allowed - HTTP method not supported',
            '408': 'Request Timeout - Client timeout',
            '429': 'Too Many Requests - Rate limit exceeded',
            '500': 'Internal Server Error - Server encountered an error',
            '502': 'Bad Gateway - Invalid response from upstream',
            '503': 'Service Unavailable - Server temporarily unavailable',
            '504': 'Gateway Timeout - Upstream server timeout'
        }
        
        description = k6_errors.get(error_code, f'Unknown K6 error code: {error_code}')
        if status_code in http_status:
            description += f' | {http_status[status_code]}'
        
        return description
    
    def _get_status_description(self, status_code: str) -> str:
        """Get brief description for HTTP status code."""
        status_descriptions = {
            '200': 'OK', '201': 'Created', '202': 'Accepted', '204': 'No Content',
            '301': 'Moved Permanently', '302': 'Found', '304': 'Not Modified',
            '400': 'Bad Request', '401': 'Unauthorized', '403': 'Forbidden',
            '404': 'Not Found', '405': 'Method Not Allowed', '408': 'Request Timeout',
            '429': 'Too Many Requests', '500': 'Internal Server Error',
            '502': 'Bad Gateway', '503': 'Service Unavailable', '504': 'Gateway Timeout'
        }
        return status_descriptions.get(status_code, 'Unknown')
    
    def _generate_error_messages(self, error_details: Dict[str, Any]) -> List[str]:
        """Generate human-readable error messages for the report."""
        messages = []
        
        if not error_details['error_breakdown']:
            return ['No detailed error information available']
        
        # Most common error
        if error_details['most_common_errors']:
            most_common = list(error_details['most_common_errors'].items())[0]
            error_code, details = most_common
            messages.append(
                f"Most common error: {error_code} ({details['count']} occurrences) - {details['description']}"
            )
        
        # Status code summary
        if error_details['status_code_distribution']:
            status_summary = []
            for status, count in list(error_details['status_code_distribution'].items())[:3]:
                status_summary.append(f"{status}: {count} requests")
            messages.append(f"HTTP Status Codes: {', '.join(status_summary)}")
        
        # Affected endpoints
        if error_details['error_by_endpoint']:
            endpoint_count = len(error_details['error_by_endpoint'])
            messages.append(f"Errors affected {endpoint_count} endpoint(s)")
            
            # Most problematic endpoint
            most_problematic = max(error_details['error_by_endpoint'].items(), 
                                 key=lambda x: x[1]['count'])
            endpoint, details = most_problematic
            messages.append(
                f"Most problematic endpoint: {endpoint} ({details['count']} errors)"
            )
        
        # Unique error patterns
        unique_count = len(error_details['unique_errors'])
        messages.append(f"Unique error patterns: {unique_count}")
        
        return messages
    
    async def _process_standard_reports(self, test_id: str) -> Dict[str, Any]:
        """Process K6 handleSummary outputs (LLM-optimized summary, HTML report, etc.)."""
        standard_reports = {
            'standard_reports_available': False,
            'llm_optimized_summary': None,
            'html_report_path': None,
            'detailed_k6_summary': None,
            'report_files': []
        }
        
        try:
            # Check for LLM-optimized summary
            llm_summary_file = self.results_dir / f"{test_id}_llm_optimized_summary.json"
            if llm_summary_file.exists():
                with open(llm_summary_file, 'r', encoding='utf-8') as f:
                    standard_reports['llm_optimized_summary'] = json.load(f)
                standard_reports['report_files'].append(f'{test_id}_llm_optimized_summary.json')
            
            # Check for HTML report
            html_report_file = self.results_dir / f"{test_id}_standard_report.html"
            if html_report_file.exists():
                standard_reports['html_report_path'] = str(html_report_file)
                standard_reports['report_files'].append(f'{test_id}_standard_report.html')
            
            # Check for detailed K6 summary
            detailed_summary_file = self.results_dir / f"{test_id}_detailed_summary.json"
            if detailed_summary_file.exists():
                # Only load if reasonably sized (< 5MB)
                if detailed_summary_file.stat().st_size < 5 * 1024 * 1024:
                    with open(detailed_summary_file, 'r', encoding='utf-8') as f:
                        standard_reports['detailed_k6_summary'] = json.load(f)
                standard_reports['report_files'].append(f'{test_id}_detailed_summary.json')
            
            if standard_reports['report_files']:
                standard_reports['standard_reports_available'] = True
                logger.info(f"Found K6 standard reports: {standard_reports['report_files']}")
            
        except Exception as e:
            logger.warning(f"Error processing standard reports: {str(e)}")
        
        return standard_reports
    
    async def get_standard_html_report(self, test_id: str) -> str:
        """Get the HTML report content for a test."""
        try:
            html_report_file = self.results_dir / f"{test_id}_standard_report.html"
            if not html_report_file.exists():
                return f"HTML report not found for test {test_id}. Ensure the test used handleSummary() function."
            
            # Check file size (limit to 2MB for safety)
            file_size = html_report_file.stat().st_size
            if file_size > 2 * 1024 * 1024:
                return f"HTML report too large ({file_size} bytes). File location: {html_report_file}"
            
            with open(html_report_file, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            return f"""📊 K6 Standard HTML Report for test {test_id}

📁 Report file: {html_report_file.name}
💾 File size: {file_size:,} bytes

📝 HTML Content:
{html_content}"""
            
        except Exception as e:
            logger.error(f"Error reading HTML report: {str(e)}")
            return f"Error reading HTML report: {str(e)}"
    
    
    async def generate_detailed_report(self, test_id: str) -> str:
        """Generate detailed CSV report for chart generation."""
        try:
            # Parse raw results
            raw_results_file = self.results_dir / f"{test_id}_results.json"
            summary_file = self.results_dir / f"{test_id}_summary.json"
            
            if not raw_results_file.exists() or not summary_file.exists():
                return f"Results files not found for test {test_id}"
            
            # Load summary for configuration info
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary = json.load(f)
            
            # Generate CSV with time-series data
            csv_file = self.results_dir / f"{test_id}_detailed_report.csv"
            
            # Parse raw K6 JSON output for time-series data
            time_series_data = []
            with open(raw_results_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if data.get('type') == 'Point' and data.get('metric'):
                            time_series_data.append(data)
                    except json.JSONDecodeError:
                        continue
            
            # Create CSV with detailed metrics over time
            with open(csv_file, 'w', encoding='utf-8', newline='') as csvfile:
                writer = csv.writer(csvfile)
                
                # Header
                writer.writerow([
                    'timestamp', 'metric_name', 'value', 'tags',
                    'response_time_ms', 'status_code', 'method', 'url'
                ])
                
                # Data rows
                for point in time_series_data:
                    timestamp = point.get('data', {}).get('time', '')
                    metric_name = point.get('metric', '')
                    value = point.get('data', {}).get('value', 0)
                    tags = json.dumps(point.get('data', {}).get('tags', {}))
                    
                    # Extract HTTP specific data
                    tags_dict = point.get('data', {}).get('tags', {})
                    response_time = value if metric_name == 'http_req_duration' else ''
                    status_code = tags_dict.get('status', '')
                    method = tags_dict.get('method', '')
                    url = tags_dict.get('url', '')
                    
                    writer.writerow([
                        timestamp, metric_name, value, tags,
                        response_time, status_code, method, url
                    ])
            
            # Also create a summary CSV for easier chart generation
            summary_csv_file = self.results_dir / f"{test_id}_summary_report.csv"
            
            with open(summary_csv_file, 'w', encoding='utf-8', newline='') as csvfile:
                writer = csv.writer(csvfile)
                
                # Summary metrics
                writer.writerow(['Metric', 'Value', 'Unit'])
                
                metrics = await self._parse_results(test_id)
                
                if 'response_time_raw' in metrics:
                    rt = metrics['response_time_raw']
                    writer.writerow(['Response Time - Average', rt['avg'], 'ms'])
                    writer.writerow(['Response Time - Minimum', rt['min'], 'ms'])
                    writer.writerow(['Response Time - Maximum', rt['max'], 'ms'])
                    writer.writerow(['Response Time - 50th Percentile', rt['p50'], 'ms'])
                    writer.writerow(['Response Time - 90th Percentile', rt['p90'], 'ms'])
                    writer.writerow(['Response Time - 95th Percentile', rt['p95'], 'ms'])
                    writer.writerow(['Response Time - 99th Percentile', rt['p99'], 'ms'])
                
                if 'throughput_raw' in metrics:
                    writer.writerow(['Throughput', metrics['throughput_raw'], 'req/s'])
                
                if 'total_requests' in metrics:
                    writer.writerow(['Total Requests', metrics['total_requests'], 'count'])
                
                if 'error_rate_raw' in metrics:
                    writer.writerow(['Error Rate', metrics['error_rate_raw'], '%'])
                
                if 'failed_requests' in metrics:
                    writer.writerow(['Failed Requests', metrics['failed_requests'], 'count'])
                
                if 'virtual_users' in metrics:
                    writer.writerow(['Virtual Users', metrics['virtual_users'], 'count'])
                
                if 'data_received_raw' in metrics:
                    writer.writerow(['Data Received', metrics['data_received_raw']/1024, 'KB'])
                
                if 'data_sent_raw' in metrics:
                    writer.writerow(['Data Sent', metrics['data_sent_raw']/1024, 'KB'])
                
                if 'test_duration' in metrics:
                    writer.writerow(['Test Duration', metrics['test_duration'], 'seconds'])
            
            return f"""📊 Detailed reports generated for test {test_id}:

📁 Files created:
• {csv_file.name} - Time-series data for detailed analysis
• {summary_csv_file.name} - Summary metrics for quick charts

💡 Chart suggestions:
• Line chart: Response time over time
• Bar chart: Response time percentiles (p50, p90, p95, p99)
• Area chart: Throughput over time
• Pie chart: Success vs Error rate
• Histogram: Response time distribution

📍 Files location: {self.results_dir}"""
            
        except Exception as e:
            logger.error(f"Error generating detailed report: {str(e)}")
            return f"Error generating detailed report: {str(e)}"
    
    async def get_report_files(self, test_id: str) -> str:
        """Get list of available report files for a test."""
        try:
            files = list(self.results_dir.glob(f"{test_id}*"))
            if not files:
                return f"No files found for test {test_id}"
            
            report = f"📁 Available files for test {test_id}:\n\n"
            
            for file in sorted(files):
                file_size = file.stat().st_size
                file_type = "Unknown"
                
                if file.suffix == '.json':
                    if 'summary' in file.name:
                        file_type = "Summary metrics (JSON)"
                    elif 'results' in file.name:
                        file_type = "Raw test data (JSON)"
                elif file.suffix == '.csv':
                    if 'detailed' in file.name:
                        file_type = "Time-series data (CSV)"
                    elif 'summary' in file.name:
                        file_type = "Summary metrics (CSV)"
                elif file.suffix == '.js':
                    file_type = "K6 test script"
                
                report += f"• {file.name} ({file_size:,} bytes) - {file_type}\n"
            
            report += f"\n📍 Location: {self.results_dir}"
            return report
            
        except Exception as e:
            logger.error(f"Error listing report files: {str(e)}")
            return f"Error listing report files: {str(e)}"
    
    async def save_csv_data(self, csv_content: str, filename: str = "uploaded_data.csv") -> str:
        """Save CSV data content to a file for use in K6 tests."""
        try:
            # Ensure filename has .csv extension
            if not filename.endswith('.csv'):
                filename += '.csv'
            
            # Save to dedicated csv_data directory
            csv_path = self.csv_data_dir / filename
            
            # Write CSV content to file
            with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                f.write(csv_content)
            
            logger.info(f"CSV data saved to {csv_path}")
            
            # Check if file was saved correctly
            if csv_path.exists():
                file_size = csv_path.stat().st_size
                return f"✅ CSV data successfully saved to {csv_path}\n\nFile size: {file_size} bytes\nLocation: csv_data/{filename}\nYou can now use this CSV file in K6 tests by specifying data_file: '{filename}'"
            else:
                return f"❌ Error: File was not created at {csv_path}"
            
        except Exception as e:
            logger.error(f"Error saving CSV data: {str(e)}")
            return f"❌ Error saving CSV data: {str(e)}"