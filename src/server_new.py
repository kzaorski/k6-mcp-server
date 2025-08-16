#!/usr/bin/env python3
"""
K6 MCP Server - Refactored Architecture

Modern, clean architecture implementation of the K6 MCP Server
using dependency injection, layered design, and separation of concerns.
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    Resource,
    Prompt,
    TextContent,
)

# Core infrastructure
from core.container import DIContainer
from core.config import AppConfig, Environment
from core.events import EventBus, get_event_bus
from core.logging import setup_logging
from core.exceptions import K6MCPError, ValidationError, ServiceError

# Services
from services.k6_service import K6TestService
from services.workflow_service import WorkflowService
from services.result_service import ResultService
from services.openapi_service import OpenAPIService

# Repositories
from repositories.test_repository import TestRepository
from repositories.workflow_repository import WorkflowRepository
from repositories.result_repository import ResultRepository

# Handlers
from handlers.k6_handler import K6TestHandler
from handlers.workflow_handler import WorkflowHandler
from handlers.result_handler import ResultHandler
from handlers.openapi_handler import OpenAPIHandler
from handlers.system_handler import SystemHandler

# Domain models
from domain.models import K6TestConfig

logger = logging.getLogger(__name__)


class K6MCPServer:
    """
    Refactored K6 MCP Server with clean architecture.
    
    Features:
    - Dependency Injection Container
    - Event-driven architecture  
    - Layered design (Handlers -> Services -> Repositories)
    - Comprehensive error handling
    - Health monitoring
    - Performance optimization
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the K6 MCP Server."""
        self.config = AppConfig.from_environment()
        self.container = DIContainer()
        self.mcp_server = Server("k6-mcp-server")
        self.handlers = {}
        self._initialized = False
        
        # Setup logging first
        setup_logging(self.config)
        logger.info("K6 MCP Server initializing...")
    
    async def initialize(self) -> None:
        """Initialize all server components."""
        if self._initialized:
            return
        
        try:
            # Initialize event bus
            event_bus = get_event_bus()
            
            # Register repositories
            await self._register_repositories()
            
            # Register services
            await self._register_services()
            
            # Register handlers
            await self._register_handlers()
            
            # Setup MCP tools
            await self._setup_mcp_tools()
            
            # Initialize all components
            await self._initialize_components()
            
            self._initialized = True
            logger.info("K6 MCP Server initialized successfully")
            
            # Publish initialization event
            from core.events import Event, EventType
            init_event = Event(
                event_type=EventType.CONFIGURATION_LOADED,
                data={
                    "environment": self.config.environment.value,
                    "components_count": len(self.handlers)
                },
                source="K6MCPServer"
            )
            await event_bus.publish(init_event)
            
        except Exception as e:
            logger.error(f"Failed to initialize K6 MCP Server: {e}", exc_info=True)
            raise K6MCPError(f"Server initialization failed: {str(e)}")
    
    async def _register_repositories(self) -> None:
        """Register repository components in DI container."""
        logger.debug("Registering repositories...")
        
        # Register repositories as singletons
        def create_test_repository():
            return TestRepository(self.config)
        def create_workflow_repository():
            return WorkflowRepository(self.config)
        def create_result_repository():
            return ResultRepository(self.config)
            
        self.container.register_factory(TestRepository, create_test_repository)
        self.container.register_factory(WorkflowRepository, create_workflow_repository)
        self.container.register_factory(ResultRepository, create_result_repository)
        
        logger.debug("Repositories registered successfully")
    
    async def _register_services(self) -> None:
        """Register service components in DI container."""
        logger.debug("Registering services...")
        
        # Register services as singletons
        def create_k6_service():
            return K6TestService(
                config=self.config,
                test_repository=self.container.resolve(TestRepository),
                result_repository=self.container.resolve(ResultRepository)
            )
            
        def create_workflow_service():
            return WorkflowService(
                config=self.config,
                workflow_repository=self.container.resolve(WorkflowRepository)
            )
            
        def create_result_service():
            return ResultService(
                config=self.config,
                result_repository=self.container.resolve(ResultRepository)
            )
            
        def create_openapi_service():
            return OpenAPIService(config=self.config)
        
        self.container.register_factory(K6TestService, create_k6_service)
        self.container.register_factory(WorkflowService, create_workflow_service)
        self.container.register_factory(ResultService, create_result_service)
        self.container.register_factory(OpenAPIService, create_openapi_service)
        
        logger.debug("Services registered successfully")
    
    async def _register_handlers(self) -> None:
        """Register handler components in DI container."""
        logger.debug("Registering handlers...")
        
        # Register handlers as singletons
        def create_k6_handler():
            return K6TestHandler(
                config=self.config,
                k6_service=self.container.resolve(K6TestService)
            )
            
        def create_workflow_handler():
            return WorkflowHandler(
                config=self.config,
                workflow_service=self.container.resolve(WorkflowService)
            )
            
        def create_result_handler():
            return ResultHandler(
                config=self.config,
                result_service=self.container.resolve(ResultService)
            )
            
        def create_openapi_handler():
            return OpenAPIHandler(
                config=self.config,
                openapi_service=self.container.resolve(OpenAPIService)
            )
            
        def create_system_handler():
            # System handler needs access to all services for health checks
            services = {
                "k6_service": self.container.resolve(K6TestService),
                "workflow_service": self.container.resolve(WorkflowService),
                "result_service": self.container.resolve(ResultService),
                "openapi_service": self.container.resolve(OpenAPIService)
            }
            return SystemHandler(config=self.config, services=services)
        
        self.container.register_factory(K6TestHandler, create_k6_handler)
        self.container.register_factory(WorkflowHandler, create_workflow_handler)
        self.container.register_factory(ResultHandler, create_result_handler)
        self.container.register_factory(OpenAPIHandler, create_openapi_handler)
        self.container.register_factory(SystemHandler, create_system_handler)
        
        # Store handlers for easy access
        self.handlers = {
            "k6": self.container.resolve(K6TestHandler),
            "workflow": self.container.resolve(WorkflowHandler),
            "result": self.container.resolve(ResultHandler),
            "openapi": self.container.resolve(OpenAPIHandler),
            "system": self.container.resolve(SystemHandler)
        }
        
        logger.debug("Handlers registered successfully")
    
    async def _setup_mcp_tools(self) -> None:
        """Setup MCP tools and route them to appropriate handlers."""
        logger.debug("Setting up MCP tools...")
        
        # Define tool routing - map tool names to handlers
        self.tool_routing = {
            # K6 Test Tools
            "run_k6_single_test": "k6",
            "run_k6_test": "k6",
            "run_k6_custom_stages_test": "k6", 
            "confirm_test": "k6",
            "execute_confirmed_test": "k6",
            "confirm_test_interactive": "k6",
            "check_confirmation_state": "k6",
            "get_test_status": "k6",
            "cancel_test": "k6",
            "list_active_tests": "k6",
            
            # Workflow Tools
            "run_k6_workflow_test": "workflow",
            "create_test_workflow": "workflow",
            "validate_request_chain": "workflow",
            "get_workflow_results": "workflow",
            "list_workflow_templates": "workflow",
            "get_workflow_status": "workflow",
            "cancel_workflow": "workflow",
            "list_active_workflows": "workflow",
            
            # Result Tools
            "get_test_results": "result",
            "generate_summary_report": "result",
            "list_recent_results": "result",
            "analyze_performance_trends": "result",
            "export_results": "result",
            "cleanup_old_results": "result",
            
            # OpenAPI Tools
            "load_openapi_spec": "openapi",
            "generate_tests_from_openapi": "openapi",
            "generate_workflow_from_openapi": "openapi",
            "analyze_openapi_endpoints": "openapi",
            "validate_openapi_spec": "openapi",
            
            # System Tools
            "health_check": "system",
            "system_status": "system",
            "list_test_templates": "system",
            "get_server_info": "system",
            "upload_csv_data": "system",
            "list_uploaded_data": "system"
        }
        
        # Register MCP tool definitions
        tools = self._create_tool_definitions()
        
        @self.mcp_server.list_tools()
        async def list_tools() -> List[Tool]:
            """List all available tools."""
            return tools
        
        @self.mcp_server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent]:
            """Handle tool calls by routing to appropriate handlers."""
            try:
                # Get handler for this tool
                handler_name = self.tool_routing.get(name)
                if not handler_name:
                    error_msg = f"Unknown tool: {name}"
                    logger.error(error_msg)
                    return [TextContent(type="text", text=json.dumps({
                        "content": [{"type": "text", "text": error_msg}],
                        "isError": True
                    }))]
                
                handler = self.handlers.get(handler_name)
                if not handler:
                    error_msg = f"Handler not found for tool: {name}"
                    logger.error(error_msg)
                    return [TextContent(type="text", text=json.dumps({
                        "content": [{"type": "text", "text": error_msg}],
                        "isError": True
                    }))]
                
                # Call handler
                logger.info(f"Calling tool: {name} with arguments: {mask_sensitive_data(arguments)}")
                result = await handler.handle(name, arguments)
                
                # Convert result to JSON string for MCP response
                return [TextContent(type="text", text=json.dumps(result))]
                
            except Exception as e:
                error_msg = f"Tool execution failed: {str(e)}"
                logger.error(f"Error executing tool {name}: {e}", exc_info=True)
                
                return [TextContent(type="text", text=json.dumps({
                    "content": [{"type": "text", "text": error_msg}],
                    "isError": True
                }))]
        
        logger.debug("MCP tools setup completed")
    
    def _create_tool_definitions(self) -> List[Tool]:
        """Create MCP tool definitions."""
        tools = []
        
        # K6 Test Tools
        tools.extend([
            Tool(
                name="run_k6_single_test",
                description="Prepare a K6 performance test for execution. Creates test configuration but does NOT execute automatically.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL for the test"},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
                        "virtual_users": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 1},
                        "duration": {"type": "string", "description": "Test duration (e.g., '30s', '5m')", "default": "30s"},
                        "iterations": {"type": "integer", "minimum": 1, "description": "Number of iterations per VU (overrides duration)"},
                        "load_pattern": {"type": "string", "enum": ["constant", "ramp_up", "spike"], "default": "constant"},
                        "headers": {"type": "object", "description": "HTTP headers"},
                        "payload": {"type": "object", "description": "Request payload for POST/PUT"},
                        "auth": {"type": "object", "description": "Authentication configuration"},
                        "timeout": {"type": "string", "default": "30s"},
                        "thresholds": {"type": "object", "description": "Performance thresholds"}
                    },
                    "required": ["url"]
                }
            ),
            Tool(
                name="run_k6_custom_stages_test", 
                description="Prepare a K6 test with custom load stages progression.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL for the test"},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
                        "stages": {
                            "type": "array",
                            "description": "Load stages configuration",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "duration": {"type": "string", "description": "Stage duration (e.g., '2m')"},
                                    "target": {"type": "integer", "minimum": 0, "description": "Target virtual users"}
                                },
                                "required": ["duration", "target"]
                            }
                        },
                        "headers": {"type": "object"},
                        "payload": {"type": "object"},
                        "auth": {"type": "object"}
                    },
                    "required": ["url", "stages"]
                }
            ),
            Tool(
                name="confirm_test",
                description="Confirm or cancel a prepared test execution.",
                inputSchema={
                    "type": "object", 
                    "properties": {
                        "response": {"type": "string", "enum": ["y", "yes", "n", "no"], "description": "Confirmation response"}
                    },
                    "required": ["response"]
                }
            ),
            Tool(
                name="execute_confirmed_test",
                description="Execute a previously confirmed test.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="list_active_tests",
                description="List all active test configurations and their status.",
                inputSchema={"type": "object", "properties": {}}
            )
        ])
        
        # Workflow Tools
        tools.extend([
            Tool(
                name="run_k6_workflow_test",
                description="Execute a multi-request workflow test with response chaining.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "workflow_name": {"type": "string", "description": "Workflow name"},
                        "steps": {
                            "type": "array",
                            "description": "Workflow steps",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "url": {"type": "string"},
                                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                                    "headers": {"type": "object"},
                                    "payload": {"type": "object"},
                                    "extract_variables": {"type": "object"},
                                    "depends_on": {"type": "array", "items": {"type": "string"}},
                                    "condition": {"type": "string"}
                                },
                                "required": ["step_id", "name", "url", "method"]
                            }
                        },
                        "virtual_users": {"type": "integer", "minimum": 1, "default": 1},
                        "duration": {"type": "string", "default": "60s"}
                    },
                    "required": ["workflow_name", "steps"]
                }
            ),
            Tool(
                name="create_test_workflow",
                description="Create a workflow from predefined templates.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "workflow_name": {"type": "string"},
                        "template_type": {"type": "string", "enum": ["auth", "crud", "custom"], "default": "custom"},
                        "base_url": {"type": "string"},
                        "virtual_users": {"type": "integer", "minimum": 1, "default": 1}
                    },
                    "required": ["workflow_name"]
                }
            ),
            Tool(
                name="list_workflow_templates",
                description="List available workflow templates and their usage.",
                inputSchema={"type": "object", "properties": {}}
            )
        ])
        
        # Result Tools
        tools.extend([
            Tool(
                name="get_test_results",
                description="Retrieve and format test results.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "test_id": {"type": "string", "description": "Test identifier"}
                    },
                    "required": ["test_id"]
                }
            ),
            Tool(
                name="list_recent_results",
                description="List recent test results.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 7},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}
                    }
                }
            ),
            Tool(
                name="analyze_performance_trends",
                description="Analyze performance trends over time.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "test_pattern": {"type": "string", "description": "Pattern to filter tests"},
                        "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 30}
                    }
                }
            )
        ])
        
        # OpenAPI Tools
        tools.extend([
            Tool(
                name="load_openapi_spec",
                description="Load and parse OpenAPI specification.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spec_url": {"type": "string", "description": "URL to OpenAPI specification"}
                    },
                    "required": ["spec_url"]
                }
            ),
            Tool(
                name="generate_tests_from_openapi",
                description="Generate K6 tests from OpenAPI specification.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spec_url": {"type": "string"},
                        "base_url": {"type": "string", "description": "Base URL for API"},
                        "test_config": {"type": "object", "description": "Test configuration options"}
                    },
                    "required": ["spec_url"]
                }
            ),
            Tool(
                name="analyze_openapi_endpoints",
                description="Analyze OpenAPI specification and provide endpoint summary.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spec_url": {"type": "string"}
                    },
                    "required": ["spec_url"]
                }
            )
        ])
        
        # System Tools
        tools.extend([
            Tool(
                name="health_check",
                description="Perform comprehensive system health check.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="system_status",
                description="Get detailed system status and resource usage.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="list_test_templates",
                description="List available test templates and configuration examples.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="get_server_info",
                description="Get server information and capabilities.",
                inputSchema={"type": "object", "properties": {}}
            )
        ])
        
        return tools
    
    async def _initialize_components(self) -> None:
        """Initialize all registered components."""
        logger.debug("Initializing components...")
        
        # Initialize repositories
        for repo_type in [TestRepository, WorkflowRepository, ResultRepository]:
            repo = self.container.resolve(repo_type)
            if hasattr(repo, 'initialize'):
                await repo.initialize()
        
        # Initialize services
        for service_type in [K6TestService, WorkflowService, ResultService, OpenAPIService]:
            service = self.container.resolve(service_type)
            if hasattr(service, 'initialize'):
                await service.initialize()
        
        logger.debug("All components initialized successfully")
    
    async def run(self) -> None:
        """Run the MCP server."""
        try:
            await self.initialize()
            logger.info("Starting K6 MCP Server...")
            
            # Run the MCP server
            async with stdio_server() as (read_stream, write_stream):
                await self.mcp_server.run(
                    read_stream, 
                    write_stream,
                    self.mcp_server.create_initialization_options()
                )
                
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        logger.info("Cleaning up server resources...")
        
        try:
            # Dispose services
            for service_type in [K6TestService, WorkflowService, ResultService, OpenAPIService]:
                try:
                    service = self.container.resolve(service_type)
                    if hasattr(service, 'dispose'):
                        await service.dispose()
                except Exception as e:
                    logger.warning(f"Error disposing service {service_type.__name__}: {e}")
            
            # Cleanup container
            if hasattr(self.container, 'dispose'):
                self.container.dispose()
            
            logger.info("Server cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)


def mask_sensitive_data(data: Any) -> Any:
    """Mask sensitive data in arguments for logging."""
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in ['password', 'token', 'key', 'secret']):
                masked[key] = "***MASKED***"
            else:
                masked[key] = mask_sensitive_data(value)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    else:
        return data


async def main():
    """Main entry point."""
    try:
        server = K6MCPServer()
        await server.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())