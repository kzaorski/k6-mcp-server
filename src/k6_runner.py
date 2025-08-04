import asyncio
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
        self.results_dir.mkdir(exist_ok=True)
        self.last_result: Optional[K6TestResult] = None
        
    async def run_test(self, config) -> str:
        """Run a K6 performance test with the given configuration."""
        test_id = f"test_{int(time.time())}"
        timestamp = datetime.now().isoformat()
        
        try:
            # Generate K6 script
            script_content = self._generate_script(config)
            
            # Write script to local file in reports directory
            script_path = self.results_dir / f"k6_test_{test_id}.js"
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            # Prepare K6 command
            output_file = self.results_dir / f"{test_id}_results.json"
            cmd = [
                "k6", "run", 
                "--out", f"json={output_file}",
                "--summary-export", f"{self.results_dir}/{test_id}_summary.json",
                str(script_path)
            ]
            
            logger.info(f"Running K6 command: {' '.join(cmd)}")
            
            # Run K6 test
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Parse and format results
                metrics = await self._parse_results(test_id)
                
                self.last_result = K6TestResult(
                    test_id=test_id,
                    timestamp=timestamp,
                    config=config.dict(),
                    metrics=metrics,
                    success=True
                )
                
                return self._format_report(self.last_result)
            else:
                error_msg = stderr.decode('utf-8') if stderr else "Unknown error"
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
    
    def _generate_script(self, config) -> str:
        """Generate K6 script based on configuration and template."""
        template_map = {
            "constant": "constant_load.js",
            "ramp_up": "ramp_up.js", 
            "spike": "spike.js"
        }
        
        template_name = template_map.get(config.load_pattern, "constant_load.js")
        template_path = self.templates_dir / template_name
        
        # Read template
        with open(template_path, 'r') as f:
            template = f.read()
        
        # Process dynamic data and variables
        script_vars = self._process_dynamic_data(config)
        
        # Build final URL with query parameters
        final_url = self._build_url_with_params(config.url, config.query_params)
        
        # Basic template substitution (but not URL yet)
        script = template.replace('{{method_lower}}', config.method.lower())
        script = script.replace('{{virtual_users}}', str(config.virtual_users))
        script = script.replace('{{duration}}', config.duration)
        script = script.replace('{{timeout}}', config.timeout or '30s')
        script = script.replace('{{retry_attempts}}', str(config.retry_attempts or 0))
        
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
        
        # Handle payload (including template processing)
        script = self._process_payload(script, config, script_vars)
        
        # Handle thresholds
        script = self._process_thresholds(script, config.thresholds)
        
        # Add environment variables and dynamic data to script
        script = self._inject_script_variables(script, script_vars, config.env_variables)
        
        # Replace URL last to avoid conflicts
        script = script.replace('{{url}}', final_url)
        
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
    
    def _process_dynamic_data(self, config) -> Dict[str, Any]:
        """Process dynamic data generators and file data."""
        script_vars = {}
        
        # Generate data from generators config
        if config.data_generators:
            generated = DataGenerator.generate_data_from_config(config.data_generators)
            script_vars.update(generated)
        
        # Load data from file
        if config.data_file:
            file_data = DataGenerator.process_data_file(config.data_file)
            if file_data:
                # For now, use first record or make available as array
                script_vars['file_data'] = file_data
                if len(file_data) > 0:
                    script_vars.update(file_data[0])  # Make first record fields available
        
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
        
        # Use payload_template if provided, otherwise use regular payload
        if config.payload_template:
            # Interpolate variables in template
            payload_str = DataGenerator.interpolate_variables(config.payload_template, script_vars)
            try:
                # Try to parse as JSON to validate
                json.loads(payload_str)
                payload_json = payload_str
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in payload template, using as string")
                payload_json = json.dumps(payload_str)
        elif config.payload:
            payload_json = json.dumps(config.payload)
        
        # Generate payload block
        if config.payload or config.payload_template:
            payload_block = f"const payload = JSON.stringify({payload_json});\n  const response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
            retry_block = f"response = http.{config.method.lower()}('{{{{url}}}}', payload, params);"
        else:
            payload_block = f"const response = http.{config.method.lower()}('{{{{url}}}}', params);"
            retry_block = f"response = http.{config.method.lower()}('{{{{url}}}}', params);"
        
        script = script.replace('{{payload_block}}', payload_block)
        script = script.replace('{{retry_block}}', retry_block)
        
        return script
    
    def _inject_script_variables(self, script: str, script_vars: Dict[str, Any], env_vars: Optional[Dict[str, str]]) -> str:
        """Inject environment variables and dynamic data into script."""
        # Add environment variables setup
        if env_vars:
            env_setup = "// Environment variables\n"
            for key, value in env_vars.items():
                env_setup += f"const {key} = __ENV.{key} || '{value}';\n"
            script = env_setup + "\n" + script
        
        # Add dynamic variables setup
        if script_vars:
            vars_setup = "// Dynamic variables\n"
            for key, value in script_vars.items():
                if key != 'file_data':  # Skip complex file_data object
                    if isinstance(value, str):
                        vars_setup += f"const {key} = '{value}';\n"
                    else:
                        vars_setup += f"const {key} = {json.dumps(value)};\n"
            script = vars_setup + "\n" + script
        
        return script
    
    async def _parse_results(self, test_id: str) -> Dict[str, Any]:
        """Parse K6 results from JSON files."""
        summary_file = self.results_dir / f"{test_id}_summary.json"
        
        if not summary_file.exists():
            return {}
        
        try:
            with open(summary_file, 'r') as f:
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
                        'p95': f"{duration.get('p(95)', 0):.2f}ms"
                    }
                
                # HTTP requests per second
                if 'http_reqs' in metrics_data:
                    reqs = metrics_data['http_reqs']
                    metrics['throughput'] = f"{reqs.get('rate', 0):.2f} req/s"
                    metrics['total_requests'] = reqs.get('count', 0)
                
                # HTTP request failed rate
                if 'http_req_failed' in metrics_data:
                    failed = metrics_data['http_req_failed']
                    metrics['error_rate'] = f"{failed.get('rate', 0)*100:.2f}%"
                
                # Virtual users
                if 'vus' in metrics_data:
                    vus = metrics_data['vus']
                    metrics['virtual_users'] = vus.get('max', 0)
                
                # Data received/sent
                if 'data_received' in metrics_data:
                    received = metrics_data['data_received']
                    metrics['data_received'] = f"{received.get('count', 0)/1024:.2f} KB"
                
                if 'data_sent' in metrics_data:
                    sent = metrics_data['data_sent']
                    metrics['data_sent'] = f"{sent.get('count', 0)/1024:.2f} KB"
            
            # Test duration
            if 'state' in summary:
                metrics['test_duration'] = summary['state'].get('testRunDurationMs', 0) / 1000
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error parsing results: {str(e)}")
            return {}
    
    def _format_report(self, result: K6TestResult) -> str:
        """Format test results into a readable report."""
        if not result.success:
            return f"❌ Test Failed: {result.error_message}"
        
        metrics = result.metrics
        config = result.config
        
        report = f"""
✅ K6 Performance Test Report
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
            report += f"""
⚠️  Error Rate: {metrics.get('error_rate')}
"""
        
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
        
        report += f"""
🆔 Test ID: {result.test_id}
🕐 Timestamp: {result.timestamp}
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
                with open(summary_file, 'r') as f:
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