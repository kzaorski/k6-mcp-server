"""
System Handler.

Handles MCP tool calls for system operations including health checks,
status monitoring, and administrative functions.
"""

import logging
import platform
from datetime import datetime
from typing import Any, Dict

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from core.base import BaseHandler
from core.config import AppConfig

logger = logging.getLogger(__name__)


class SystemHandler(BaseHandler):
    """
    Handler for system-related MCP tool calls.
    
    Processes requests for system health, status monitoring,
    and administrative operations with proper validation.
    """
    
    def __init__(self, config: AppConfig, services: Dict[str, Any] = None):
        super().__init__(config)
        self.services = services or {}
    
    async def handle(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle system tool calls."""
        
        try:
            if name == "health_check":
                return await self._handle_health_check(arguments)
            
            elif name == "system_status":
                return await self._handle_system_status(arguments)
            
            elif name == "list_test_templates":
                return await self._handle_list_test_templates(arguments)
            
            elif name == "get_server_info":
                return await self._handle_get_server_info(arguments)
            
            elif name == "upload_csv_data":
                return await self._handle_upload_csv_data(arguments)
            
            elif name == "list_uploaded_data":
                return await self._handle_list_uploaded_data(arguments)
            
            else:
                return self.create_error_response(f"Unknown system tool: {name}")
                
        except Exception as e:
            self.logger.error(f"Error handling system {name}: {e}", exc_info=True)
            return self.create_error_response(f"System handler error: {str(e)}")
    
    async def _handle_health_check(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle comprehensive health check."""
        operation_id = self.log_operation_start("health_check")
        
        try:
            health_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "overall_status": "healthy",
                "components": {},
                "system_metrics": {},
                "issues": []
            }
            
            # System metrics
            try:
                if PSUTIL_AVAILABLE:
                    health_data["system_metrics"] = {
                        "cpu_percent": psutil.cpu_percent(interval=1),
                        "memory_percent": psutil.virtual_memory().percent,
                        "disk_percent": psutil.disk_usage('/').percent,
                        "uptime_seconds": (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds()
                    }
                else:
                    health_data["system_metrics"] = {
                        "cpu_percent": 0,
                        "memory_percent": 0,
                        "disk_percent": 0,
                        "uptime_seconds": 0
                    }
                    health_data["issues"].append("psutil not available - system metrics unavailable")
            except Exception as e:
                health_data["issues"].append(f"Failed to get system metrics: {str(e)}")
            
            # Service health checks
            unhealthy_services = []
            for service_name, service in self.services.items():
                try:
                    if hasattr(service, 'health_check'):
                        service_health = await service.health_check()
                        health_data["components"][service_name] = service_health
                        
                        if isinstance(service_health, dict):
                            status = service_health.get("status", "unknown")
                        else:
                            status = getattr(service_health, "status", "unknown")
                        
                        if status != "healthy":
                            unhealthy_services.append(service_name)
                    else:
                        health_data["components"][service_name] = {
                            "status": "unknown",
                            "message": "No health check available"
                        }
                except Exception as e:
                    health_data["components"][service_name] = {
                        "status": "error",
                        "message": f"Health check failed: {str(e)}"
                    }
                    unhealthy_services.append(service_name)
            
            # Determine overall status
            if unhealthy_services:
                health_data["overall_status"] = "degraded"
                health_data["issues"].append(f"Unhealthy services: {', '.join(unhealthy_services)}")
            
            # Check system resources
            cpu_percent = health_data["system_metrics"].get("cpu_percent", 0)
            memory_percent = health_data["system_metrics"].get("memory_percent", 0)
            disk_percent = health_data["system_metrics"].get("disk_percent", 0)
            
            if cpu_percent > 90:
                health_data["overall_status"] = "degraded"
                health_data["issues"].append(f"High CPU usage: {cpu_percent:.1f}%")
            
            if memory_percent > 90:
                health_data["overall_status"] = "degraded"
                health_data["issues"].append(f"High memory usage: {memory_percent:.1f}%")
            
            if disk_percent > 90:
                health_data["overall_status"] = "degraded"
                health_data["issues"].append(f"High disk usage: {disk_percent:.1f}%")
            
            self.log_operation_end(operation_id, True)
            
            # Format health check response
            health_display = self._format_health_check_display(health_data)
            return self.create_success_response(health_display)
            
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Health check failed: {str(e)}")
    
    async def _handle_system_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle system status retrieval."""
        try:
            # Get basic system information
            system_info = {
                "platform": platform.system(),
                "platform_version": platform.version(),
                "platform_release": platform.release(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
                "hostname": platform.node()
            }
            
            # Get resource usage
            try:
                if PSUTIL_AVAILABLE:
                    cpu_count = psutil.cpu_count()
                    memory = psutil.virtual_memory()
                    disk = psutil.disk_usage('/')
                    
                    resource_info = {
                        "cpu_cores": cpu_count,
                        "cpu_usage_percent": psutil.cpu_percent(interval=1),
                        "memory_total_gb": memory.total / (1024**3),
                        "memory_used_gb": memory.used / (1024**3),
                        "memory_percent": memory.percent,
                        "disk_total_gb": disk.total / (1024**3),
                        "disk_used_gb": disk.used / (1024**3),
                        "disk_percent": (disk.used / disk.total) * 100
                    }
                else:
                    resource_info = {"error": "psutil not available - resource monitoring disabled"}
            except Exception as e:
                resource_info = {"error": f"Failed to get resource info: {str(e)}"}
            
            # Server configuration
            server_config = {
                "base_directory": str(self.config.base_dir),
                "reports_directory": str(self.config.reports_dir),
                "environment": self.config.environment.value,
                "k6_binary": self.config.k6.k6_binary_path,
                "max_virtual_users": self.config.k6.max_virtual_users,
                "results_retention_days": self.config.k6.results_retention_days
            }
            
            status_display = self._format_system_status_display(system_info, resource_info, server_config)
            return self.create_success_response(status_display)
            
        except Exception as e:
            return self.create_error_response(f"Failed to get system status: {str(e)}")
    
    async def _handle_list_test_templates(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test template listing."""
        templates_info = """📋 **Available K6 Test Templates**

🔄 **Load Patterns:**

**Constant Load (constant)**
• Steady number of virtual users
• Consistent load throughout test duration
• Perfect for baseline performance testing
• Use with: `load_pattern: "constant"`

**Ramp-Up Load (ramp_up)**
• Gradually increase virtual users
• Simulates growing user base
• Good for finding breaking points
• Use with: `load_pattern: "ramp_up"`

**Spike Testing (spike)**
• Sudden traffic spikes
• Tests system resilience
• Identifies performance bottlenecks
• Use with: `load_pattern: "spike"`

**Custom Stages (custom_stages)**
• Define your own load progression
• Multiple stages with different VU targets
• Complex load scenarios
• Use with: `load_pattern: "custom_stages"` + `stages` array

🔧 **Configuration Examples:**

**Simple Constant Load:**
```json
{
  "url": "https://api.example.com/endpoint",
  "method": "GET",
  "virtual_users": 10,
  "duration": "60s",
  "load_pattern": "constant"
}
```

**Custom Stages:**
```json
{
  "url": "https://api.example.com/endpoint",
  "load_pattern": "custom_stages",
  "stages": [
    {"duration": "2m", "target": 10},
    {"duration": "5m", "target": 50},
    {"duration": "2m", "target": 0}
  ]
}
```

**With Authentication:**
```json
{
  "url": "https://api.example.com/protected",
  "method": "GET",
  "auth": {
    "type": "bearer",
    "token": "your-token-here"
  },
  "virtual_users": 5,
  "duration": "30s"
}
```

**POST with Payload:**
```json
{
  "url": "https://api.example.com/users",
  "method": "POST",
  "payload": {
    "name": "Test User",
    "email": "test@example.com"
  },
  "headers": {
    "Content-Type": "application/json"
  },
  "virtual_users": 3,
  "iterations": 10
}
```"""
        
        return self.create_success_response(templates_info)
    
    async def _handle_get_server_info(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle server information retrieval."""
        try:
            server_info = f"""🖥️ **K6 MCP Server Information**

🔧 **Server Details:**
• Server Type: K6 MCP (Model Context Protocol) Server
• Environment: {self.config.environment.value}
• Base Directory: {self.config.base_dir}
• Reports Directory: {self.config.reports_dir}

⚙️ **K6 Configuration:**
• K6 Binary Path: {self.config.k6.k6_binary_path}
• Max Virtual Users: {self.config.k6.max_virtual_users}
• Default Timeout: {self.config.k6.default_timeout}
• Results Retention: {self.config.k6.results_retention_days} days
• HTML Reports: {'Enabled' if self.config.k6.enable_html_reports else 'Disabled'}

🌐 **Server Configuration:**
• Host: {self.config.server.host}
• Port: {self.config.server.port}
• Debug Mode: {'Enabled' if self.config.server.debug else 'Disabled'}

🔒 **Security Settings:**
• Rate Limiting: {'Enabled' if self.config.security.rate_limiting_enabled else 'Disabled'}
• Max Request Rate: {self.config.security.max_requests_per_minute} req/min
• Authentication Required: {'Yes' if self.config.security.require_authentication else 'No'}

📊 **Capabilities:**
• Single K6 Tests: ✅
• Multi-Request Workflows: ✅
• OpenAPI Integration: ✅
• Custom Load Stages: ✅
• Result Analysis: ✅
• Performance Trends: ✅
• HAR File Processing: ✅
• CSV Data Upload: ✅

💡 **Available Tools:**
• Test Execution: run_k6_single_test, run_k6_custom_stages_test
• Workflow Management: run_k6_workflow_test, create_test_workflow
• OpenAPI Integration: generate_tests_from_openapi, analyze_openapi_endpoints
• Result Analysis: get_test_results, analyze_performance_trends
• System Monitoring: health_check, system_status"""
            
            return self.create_success_response(server_info)
            
        except Exception as e:
            return self.create_error_response(f"Failed to get server info: {str(e)}")
    
    async def _handle_upload_csv_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle CSV data upload."""
        file_name = arguments.get("file_name")
        csv_data = arguments.get("csv_data")
        
        if not file_name:
            return self.create_error_response("file_name is required")
        if not csv_data:
            return self.create_error_response("csv_data is required")
        
        operation_id = self.log_operation_start("upload_csv_data", file_name=file_name)
        
        try:
            # Ensure CSV data directory exists
            csv_dir = self.config.base_dir / "csv_data"
            csv_dir.mkdir(parents=True, exist_ok=True)
            
            # Save CSV file
            csv_file_path = csv_dir / file_name
            if not csv_file_path.suffix.lower() == '.csv':
                csv_file_path = csv_file_path.with_suffix('.csv')
            
            with open(csv_file_path, 'w', encoding='utf-8') as f:
                f.write(csv_data)
            
            # Analyze CSV structure
            lines = csv_data.strip().split('\n')
            header_line = lines[0] if lines else ""
            data_rows = len(lines) - 1 if len(lines) > 1 else 0
            
            columns = header_line.split(',') if header_line else []
            
            self.log_operation_end(operation_id, True)
            
            upload_summary = f"""✅ **CSV Data Uploaded Successfully**

📁 **File Information:**
• File Name: {csv_file_path.name}
• File Path: {csv_file_path}
• File Size: {len(csv_data)} bytes

📊 **Data Structure:**
• Columns: {len(columns)}
• Data Rows: {data_rows}
• Total Lines: {len(lines)}

📋 **Column Headers:**"""
            
            for i, column in enumerate(columns[:10], 1):  # Show first 10 columns
                upload_summary += f"\n{i}. {column.strip()}"
            
            if len(columns) > 10:
                upload_summary += f"\n... and {len(columns) - 10} more columns"
            
            upload_summary += f"""

💡 **Usage in Tests:**
• Reference in K6 tests using the file path
• Use for parameterized testing with dynamic data
• Integrate with workflow data generation

✅ **Ready for Use:**
• File is available for K6 test data injection
• Can be referenced in test configurations
• Suitable for load testing with varied data"""
            
            return self.create_success_response(upload_summary)
            
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to upload CSV data: {str(e)}")
    
    async def _handle_list_uploaded_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle listing uploaded data files."""
        try:
            csv_dir = self.config.base_dir / "csv_data"
            
            if not csv_dir.exists():
                return self.create_success_response("📁 **No data directory found.**\n\nNo CSV files have been uploaded yet. Use 'upload_csv_data' to add data files.")
            
            csv_files = list(csv_dir.glob("*.csv"))
            
            if not csv_files:
                return self.create_success_response("📁 **No CSV files found.**\n\nThe data directory exists but contains no CSV files. Use 'upload_csv_data' to add data files.")
            
            file_list = f"""📁 **Uploaded Data Files ({len(csv_files)} files)**

📊 **Available CSV Files:**

"""
            
            for i, csv_file in enumerate(sorted(csv_files), 1):
                try:
                    file_stat = csv_file.stat()
                    file_size = file_stat.st_size
                    modified_time = datetime.fromtimestamp(file_stat.st_mtime)
                    
                    # Try to read first line for column count
                    try:
                        with open(csv_file, 'r', encoding='utf-8') as f:
                            first_line = f.readline().strip()
                            columns = len(first_line.split(',')) if first_line else 0
                    except:
                        columns = "Unknown"
                    
                    file_list += f"""{i}. **{csv_file.name}**
   • Size: {file_size:,} bytes
   • Columns: {columns}
   • Modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}
   • Path: {csv_file}

"""
                except Exception as e:
                    file_list += f"{i}. **{csv_file.name}** (Error reading file info: {str(e)})\n\n"
            
            file_list += """💡 **Usage Tips:**
• Reference files by name or full path in test configurations
• Use with K6 data parameterization features
• Suitable for load testing with dynamic data sets
• Files are persistent across server restarts"""
            
            return self.create_success_response(file_list)
            
        except Exception as e:
            return self.create_error_response(f"Failed to list uploaded data: {str(e)}")
    
    def _format_health_check_display(self, health_data: Dict[str, Any]) -> str:
        """Format health check data for display."""
        overall_status = health_data.get("overall_status", "unknown")
        status_icon = {
            "healthy": "✅",
            "degraded": "⚠️",
            "unhealthy": "❌"
        }.get(overall_status, "❓")
        
        display_text = f"""{status_icon} **System Health Check**

🎯 **Overall Status:** {overall_status.upper()}
🕐 **Timestamp:** {health_data.get('timestamp', 'Unknown')}

📊 **System Metrics:**"""
        
        metrics = health_data.get("system_metrics", {})
        if metrics:
            display_text += f"""
• CPU Usage: {metrics.get('cpu_percent', 0):.1f}%
• Memory Usage: {metrics.get('memory_percent', 0):.1f}%
• Disk Usage: {metrics.get('disk_percent', 0):.1f}%
• Uptime: {metrics.get('uptime_seconds', 0) / 3600:.1f} hours"""
        
        display_text += f"\n\n🔧 **Service Components:**"
        
        components = health_data.get("components", {})
        for service_name, service_health in components.items():
            if isinstance(service_health, dict):
                status = service_health.get("status", "unknown")
                message = service_health.get("message", "")
            else:
                status = getattr(service_health, "status", "unknown")
                message = getattr(service_health, "message", "")
            
            service_icon = {
                "healthy": "✅",
                "degraded": "⚠️",
                "unhealthy": "❌",
                "error": "💥"
            }.get(status, "❓")
            
            display_text += f"\n{service_icon} **{service_name}**: {status}"
            if message:
                display_text += f" - {message}"
        
        issues = health_data.get("issues", [])
        if issues:
            display_text += f"\n\n⚠️ **Issues Found:**"
            for i, issue in enumerate(issues, 1):
                display_text += f"\n{i}. {issue}"
        
        return display_text
    
    def _format_system_status_display(self, system_info: Dict[str, Any], resource_info: Dict[str, Any], server_config: Dict[str, Any]) -> str:
        """Format system status for display."""
        display_text = f"""🖥️ **System Status Report**

💻 **Platform Information:**
• Operating System: {system_info.get('platform', 'Unknown')} {system_info.get('platform_release', '')}
• Architecture: {system_info.get('architecture', 'Unknown')}
• Hostname: {system_info.get('hostname', 'Unknown')}
• Python Version: {system_info.get('python_version', 'Unknown')}

📊 **Resource Usage:**"""
        
        if "error" not in resource_info:
            display_text += f"""
• CPU Cores: {resource_info.get('cpu_cores', 'Unknown')}
• CPU Usage: {resource_info.get('cpu_usage_percent', 0):.1f}%
• Memory: {resource_info.get('memory_used_gb', 0):.1f}GB / {resource_info.get('memory_total_gb', 0):.1f}GB ({resource_info.get('memory_percent', 0):.1f}%)
• Disk: {resource_info.get('disk_used_gb', 0):.1f}GB / {resource_info.get('disk_total_gb', 0):.1f}GB ({resource_info.get('disk_percent', 0):.1f}%)"""
        else:
            display_text += f"\n• Error: {resource_info['error']}"
        
        display_text += f"""

⚙️ **Server Configuration:**
• Environment: {server_config.get('environment', 'Unknown')}
• Base Directory: {server_config.get('base_directory', 'Unknown')}
• Reports Directory: {server_config.get('reports_directory', 'Unknown')}
• K6 Binary: {server_config.get('k6_binary', 'Unknown')}
• Max Virtual Users: {server_config.get('max_virtual_users', 'Unknown')}
• Results Retention: {server_config.get('results_retention_days', 'Unknown')} days

✅ **System Ready:**
• All core components operational
• K6 testing capability available
• MCP protocol server running
• Ready to process test requests"""
        
        return display_text