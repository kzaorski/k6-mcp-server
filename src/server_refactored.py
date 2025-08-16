"""
Refactored K6 MCP Server.

Modern, maintainable architecture with dependency injection, proper separation
of concerns, and comprehensive error handling.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, Resource, Prompt, TextContent

# Core components
from core.container import DIContainer
from core.config import AppConfig
from core.base import HealthCheck

# Services
from services.k6_service import K6TestService
from services.workflow_service import WorkflowService
from services.openapi_service import OpenAPIService
from services.result_service import ResultService

# Repositories
from repositories.test_repository import TestRepository
from repositories.result_repository import ResultRepository
from repositories.workflow_repository import WorkflowRepository

# Handlers
from handlers.k6_handler import K6TestHandler
from handlers.workflow_handler import WorkflowHandler
from handlers.openapi_handler import OpenAPIHandler
from handlers.result_handler import ResultHandler

# Legacy imports for backward compatibility
from k6_runner import K6Runner
from workflow_manager import WorkflowManager
from har_processor import HARProcessor
from openapi_processor import OpenAPIProcessor

logger = logging.getLogger(__name__)


class K6MCPServer:
    """
    Refactored K6 MCP Server with modern architecture.
    
    Features:
    - Dependency injection container
    - Clean separation of concerns
    - Comprehensive error handling
    - Health monitoring
    - Configuration management
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.container = DIContainer()
        self.mcp_server = Server("k6-mcp-server")
        
        # Service instances
        self.k6_service: K6TestService = None
        self.workflow_service: WorkflowService = None
        self.openapi_service: OpenAPIService = None
        self.result_service: ResultService = None
        
        # Handler instances
        self.k6_handler: K6TestHandler = None
        self.workflow_handler: WorkflowHandler = None
        self.openapi_handler: OpenAPIHandler = None
        self.result_handler: ResultHandler = None
        
        # Legacy components (for backward compatibility)
        self.k6_runner: K6Runner = None
        self.workflow_manager: WorkflowManager = None
        self.har_processor: HARProcessor = None
        self.openapi_processor: OpenAPIProcessor = None
        
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the server and all components."""
        if self._initialized:
            return
        
        logger.info("Initializing K6 MCP Server...")
        
        # Configure logging
        self._configure_logging()
        
        # Validate configuration
        config_warnings = self.config.validate()
        for warning in config_warnings:
            logger.warning(f"Configuration warning: {warning}")
        
        # Register dependencies
        self._register_dependencies()
        
        # Initialize services
        await self._initialize_services()
        
        # Initialize handlers
        self._initialize_handlers()
        
        # Initialize legacy components (backward compatibility)
        self._initialize_legacy_components()
        
        # Register MCP handlers
        self._register_mcp_handlers()
        
        self._initialized = True
        logger.info("K6 MCP Server initialized successfully")
    
    async def dispose(self) -> None:
        """Dispose of all resources."""
        if not self._initialized:
            return
        
        logger.info("Disposing K6 MCP Server...")
        
        # Dispose services
        if self.k6_service:
            await self.k6_service.dispose()
        if self.workflow_service:
            await self.workflow_service.dispose()
        if self.openapi_service:
            await self.openapi_service.dispose()
        if self.result_service:
            await self.result_service.dispose()
        
        # Dispose DI container
        self.container.dispose()
        
        self._initialized = False
        logger.info("K6 MCP Server disposed")
    
    async def run(self) -> None:
        """Run the MCP server."""
        await self.initialize()
        
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.mcp_server.run(
                    read_stream,
                    write_stream,
                    self.mcp_server.create_initialization_options()
                )
        finally:
            await self.dispose()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        health_checks = []
        
        # Check each service
        if self.k6_service:
            health_checks.append(await self.k6_service.health_check())
        
        # Overall status
        unhealthy_count = sum(1 for hc in health_checks if hc.status == "unhealthy")
        degraded_count = sum(1 for hc in health_checks if hc.status == "degraded")
        
        overall_status = "healthy"
        if unhealthy_count > 0:
            overall_status = "unhealthy"
        elif degraded_count > 0:
            overall_status = "degraded"
        
        return {
            "status": overall_status,
            "components": [
                {
                    "component": hc.component,
                    "status": hc.status,
                    "message": hc.message,
                    "duration_ms": hc.duration_ms
                }
                for hc in health_checks
            ]
        }
    
    def _configure_logging(self) -> None:
        """Configure logging based on configuration."""
        log_level = getattr(logging, self.config.logging.level.value)
        
        # Configure root logger
        logging.basicConfig(
            level=log_level,
            format=self.config.logging.format,
            stream=sys.stderr
        )
        
        # Configure file logging if specified
        if self.config.logging.file_path:
            from logging.handlers import RotatingFileHandler
            
            file_handler = RotatingFileHandler(
                self.config.logging.file_path,
                maxBytes=self.config.logging.max_file_size,
                backupCount=self.config.logging.backup_count
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(logging.Formatter(self.config.logging.format))
            
            root_logger = logging.getLogger()
            root_logger.addHandler(file_handler)
    
    def _register_dependencies(self) -> None:
        """Register all dependencies in the DI container."""
        # Register configuration
        self.container.register_instance(AppConfig, self.config)
        
        # Register repositories
        self.container.register_singleton(TestRepository)
        self.container.register_singleton(ResultRepository) 
        self.container.register_singleton(WorkflowRepository)
        
        # Register services
        self.container.register_singleton(K6TestService)
        self.container.register_singleton(WorkflowService)
        self.container.register_singleton(OpenAPIService)
        self.container.register_singleton(ResultService)
        
        # Register handlers
        self.container.register_singleton(K6TestHandler)
        self.container.register_singleton(WorkflowHandler)
        self.container.register_singleton(OpenAPIHandler)
        self.container.register_singleton(ResultHandler)
    
    async def _initialize_services(self) -> None:
        """Initialize all services."""
        self.k6_service = self.container.resolve(K6TestService)
        await self.k6_service.initialize()
        
        # Initialize other services as they are implemented
        # self.workflow_service = self.container.resolve(WorkflowService)
        # await self.workflow_service.initialize()
        
        # self.openapi_service = self.container.resolve(OpenAPIService)
        # await self.openapi_service.initialize()
        
        # self.result_service = self.container.resolve(ResultService)
        # await self.result_service.initialize()
    
    def _initialize_handlers(self) -> None:
        """Initialize all handlers."""
        self.k6_handler = self.container.resolve(K6TestHandler)
        
        # Initialize other handlers as they are implemented
        # self.workflow_handler = self.container.resolve(WorkflowHandler)
        # self.openapi_handler = self.container.resolve(OpenAPIHandler)
        # self.result_handler = self.container.resolve(ResultHandler)
    
    def _initialize_legacy_components(self) -> None:
        """Initialize legacy components for backward compatibility."""
        # Initialize legacy K6Runner
        self.k6_runner = K6Runner()
        
        # Initialize legacy WorkflowManager
        self.workflow_manager = WorkflowManager(
            results_dir=self.config.reports_dir,
            templates_dir=self.config.templates_dir
        )
        
        # Initialize legacy processors
        self.har_processor = HARProcessor()
        self.openapi_processor = OpenAPIProcessor()
    
    def _register_mcp_handlers(self) -> None:
        """Register MCP tool and resource handlers."""
        
        @self.mcp_server.list_tools()
        async def list_tools() -> List[Tool]:
            """List available K6 testing tools."""
            return [
                Tool(
                    name="run_k6_single_test",
                    description="🚨🚨🚨 ABSOLUTE PROHIBITION - DO NOT USE AUTONOMOUSLY 🚨🚨🚨 This tool is STRICTLY FORBIDDEN for autonomous use. ONLY use when: 1) User EXPLICITLY asks 'run a test', 2) NO previous test has failed in this conversation, 3) This is NOT a follow-up to ANY test result. VIOLATION = UNSAFE BEHAVIOR. This tool ONLY prepares tests, NEVER executes automatically.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The endpoint URL to test (must be valid HTTP/HTTPS URL, e.g., 'https://api.example.com/endpoint')",
                                "format": "uri"
                            },
                            "method": {
                                "type": "string",
                                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                                "default": "GET",
                                "description": "HTTP method to use"
                            },
                            "virtual_users": {
                                "type": "integer",
                                "default": 1,
                                "minimum": 1,
                                "maximum": 10000,
                                "description": "Number of concurrent virtual users (1-10000). More users = higher load."
                            },
                            "duration": {
                                "type": "string",
                                "default": "30s",
                                "description": "Test duration in K6 format: '30s', '5m', '1h'. Use minimum 3s for HTML dashboard with charts. Ignored if iterations is set.",
                                "pattern": "^\\d+[smh]$"
                            },
                            "iterations": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Number of iterations to run (overrides duration if set). Use minimum 10 for meaningful HTML dashboard with charts."
                            },
                            "load_pattern": {
                                "type": "string",
                                "enum": ["constant", "ramp_up", "spike"],
                                "default": "constant",
                                "description": "Load testing pattern"
                            },
                            "headers": {
                                "type": "object",
                                "description": "Custom HTTP headers"
                            },
                            "payload": {
                                "type": "object",
                                "description": "JSON payload for POST/PUT requests"
                            },
                            "timeout": {
                                "type": "string",
                                "default": "30s",
                                "description": "Request timeout in K6 format: '30s', '5m'. Controls individual HTTP request timeout.",
                                "pattern": "^\\d+[smh]$"
                            },
                            "think_time": {
                                "type": "number",
                                "default": 1.0,
                                "description": "Time in seconds to pause between requests (think time to simulate user behavior)"
                            }
                        },
                        "required": ["url"]
                    }
                ),
                Tool(
                    name="confirm_test",
                    description="Confirm pending test execution with y/n response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "response": {
                                "type": "string",
                                "enum": ["y", "n", "yes", "no"],
                                "default": "n",
                                "description": "User response to test confirmation (y/yes to confirm, n/no to cancel). Default: n"
                            }
                        },
                        "required": ["response"]
                    }
                ),
                Tool(
                    name="execute_confirmed_test",
                    description="🚨 Execute previously confirmed test. ONLY call this after confirm_test returns 'confirmed'",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="get_test_status",
                    description="Get the status of a test",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_id": {
                                "type": "string",
                                "description": "Test ID to check status for"
                            }
                        },
                        "required": ["test_id"]
                    }
                ),
                Tool(
                    name="list_active_tests",
                    description="List all active tests",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                ),
                Tool(
                    name="health_check",
                    description="Check the health status of the K6 MCP server",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False
                    }
                )
            ]
        
        @self.mcp_server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]):
            """Handle tool calls."""
            try:
                # Route to appropriate handler
                if name in [
                    "run_k6_single_test", "run_k6_test", "run_k6_custom_stages_test",
                    "confirm_test", "execute_confirmed_test", "confirm_test_interactive",
                    "check_confirmation_state", "get_test_status", "cancel_test", "list_active_tests"
                ]:
                    return await self.k6_handler.handle(name, arguments)
                
                elif name == "health_check":
                    health_status = await self.health_check()
                    
                    health_text = f"""🏥 **K6 MCP Server Health Check**

**Overall Status: {health_status['status'].upper()}**

**Component Status:**"""
                    
                    for component in health_status['components']:
                        status_icon = {
                            "healthy": "✅",
                            "degraded": "⚠️", 
                            "unhealthy": "❌"
                        }.get(component['status'], "❓")
                        
                        health_text += f"\n{status_icon} **{component['component']}**: {component['status']}"
                        if component['message']:
                            health_text += f" - {component['message']}"
                        if component['duration_ms']:
                            health_text += f" ({component['duration_ms']:.1f}ms)"
                    
                    return {
                        "content": [{"type": "text", "text": health_text}]
                    }
                
                # Legacy tool handling for backward compatibility
                elif name in [
                    "run_k6_workflow_test", "run_k6_multi_request_test",
                    "create_test_workflow", "validate_request_chain",
                    "list_workflow_templates", "get_workflow_results",
                    "load_har_file", "run_k6_har_test", "analyze_har_structure",
                    "import_openapi_spec", "generate_tests_from_openapi",
                    "analyze_openapi_coverage", "preview_openapi_tests", "select_openapi_endpoints",
                    "get_test_results", "list_test_templates", "upload_csv_data"
                ]:
                    # Delegate to legacy handlers (import from original server.py)
                    from server import call_tool as legacy_call_tool
                    return await legacy_call_tool(name, arguments)
                
                else:
                    return {
                        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                        "isError": True
                    }
                    
            except Exception as e:
                logger.error(f"Error executing tool {name}: {str(e)}", exc_info=True)
                return {
                    "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                    "isError": True
                }
        
        @self.mcp_server.list_resources()
        async def list_resources() -> List[Resource]:
            """List available resources."""
            return [
                Resource(
                    uri="file://README.md",
                    name="K6 MCP Documentation", 
                    description="Complete documentation for K6 MCP Server including usage examples and configuration.",
                    mimeType="text/markdown"
                ),
                Resource(
                    uri="file://health",
                    name="Server Health Status",
                    description="Current health status of the K6 MCP Server and its components.",
                    mimeType="application/json"
                )
            ]
        
        @self.mcp_server.read_resource()
        async def read_resource(uri: str) -> str:
            """Read resource content by URI."""
            normalized_uri = uri.lower().rstrip('/')
            
            if normalized_uri in ["file://readme.md", "file://README.md"]:
                try:
                    readme_file = self.config.base_dir / "README.md"
                    if readme_file.exists():
                        with open(readme_file, 'r', encoding='utf-8') as f:
                            return f.read()
                    else:
                        return "README.md not found"
                except Exception as e:
                    return f"Error reading README.md: {str(e)}"
            
            elif normalized_uri == "file://health":
                health_status = await self.health_check()
                import json
                return json.dumps(health_status, indent=2)
            
            else:
                raise ValueError(f"Unknown resource URI: {uri}")


async def main():
    """Main entry point for the refactored MCP server."""
    # Load configuration
    config = AppConfig.from_environment("K6_MCP")
    
    # Create and run server
    server = K6MCPServer(config)
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())