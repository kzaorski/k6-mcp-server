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
            
            # Clean up temporary script
            os.unlink(script_path)
            
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
        
        # Simple template substitution (in production, use proper templating engine)
        script = template.replace('{{url}}', config.url)
        script = script.replace('{{method_lower}}', config.method.lower())
        script = script.replace('{{virtual_users}}', str(config.virtual_users))
        script = script.replace('{{duration}}', config.duration)
        
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
        
        # Handle payload
        if config.payload:
            payload_json = json.dumps(config.payload)
            script = script.replace('{{json payload}}', payload_json)
            script = script.replace('{{#if payload}}', '')
            script = script.replace('{{else}}', '/*')
            script = script.replace('{{/if}}', '*/')
        else:
            # Remove payload sections
            script = script.replace('{{#if payload}}', '/*')
            script = script.replace('{{else}}', '*/')
            script = script.replace('{{/if}}', '')
        
        # Handle thresholds
        if config.thresholds:
            thresholds_js = []
            for key, value in config.thresholds.items():
                thresholds_js.append(f"    '{key}': ['{value}']")
            thresholds_str = ',\n'.join(thresholds_js)
            
            script = script.replace('{{#if thresholds}}', '')
            script = script.replace('{{#each thresholds}}', '')
            script = script.replace("    '{{@key}}': ['{{this}}'],", thresholds_str)
            script = script.replace('{{/each}}', '')
            script = script.replace('{{/if}}', '')
        else:
            # Remove thresholds section
            script = script.replace('{{#if thresholds}}', '/*')
            script = script.replace('{{/if}}', '*/')
            lines = script.split('\n')
            script = '\n'.join([line for line in lines if '{{#each thresholds}}' not in line and '{{/each}}' not in line and '{{@key}}' not in line])
        
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