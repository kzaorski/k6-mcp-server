#!/usr/bin/env python3

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
)
from pydantic import BaseModel

from k6_runner import K6Runner

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("k6-mcp-server")

# Initialize MCP server
app = Server("k6-mcp-server")

# Initialize K6 runner
k6_runner = K6Runner()


class K6TestConfig(BaseModel):
    url: str
    method: str = "GET"
    payload: Optional[Dict[str, Any]] = None
    load_pattern: str = "constant"  # constant, ramp_up, spike
    duration: str = "30s"
    virtual_users: int = 10
    thresholds: Optional[Dict[str, str]] = None
    
    # Advanced HTTP request parameters
    headers: Optional[Dict[str, str]] = None
    auth: Optional[Dict[str, Any]] = None  # {type: "bearer|basic|apikey", token/credentials}
    cookies: Optional[Dict[str, str]] = None
    query_params: Optional[Dict[str, str]] = None
    timeout: Optional[str] = "30s"
    retry_attempts: Optional[int] = 0
    
    # Dynamic request data
    env_variables: Optional[Dict[str, str]] = None
    data_generators: Optional[Dict[str, Dict[str, Any]]] = None
    data_file: Optional[str] = None
    payload_template: Optional[str] = None


@app.list_tools()
async def list_tools() -> List[Tool]:
    """List available K6 testing tools."""
    return [
        Tool(
            name="run_k6_test",
            description="Run a K6 performance test with specified parameters",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The endpoint URL to test"
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                        "default": "GET",
                        "description": "HTTP method to use"
                    },
                    "payload": {
                        "type": "object",
                        "description": "JSON payload for POST/PUT requests"
                    },
                    "load_pattern": {
                        "type": "string",
                        "enum": ["constant", "ramp_up", "spike"],
                        "default": "constant",
                        "description": "Load testing pattern"
                    },
                    "duration": {
                        "type": "string",
                        "default": "30s",
                        "description": "Test duration (e.g., '30s', '5m')"
                    },
                    "virtual_users": {
                        "type": "integer",
                        "default": 10,
                        "description": "Number of virtual users"
                    },
                    "thresholds": {
                        "type": "object",
                        "description": "Performance thresholds (optional)"
                    },
                    "headers": {
                        "type": "object",
                        "description": "Custom HTTP headers"
                    },
                    "auth": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["bearer", "basic", "apikey"]
                            },
                            "token": {"type": "string"},
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                            "header_name": {"type": "string"}
                        },
                        "description": "Authentication configuration"
                    },
                    "cookies": {
                        "type": "object",
                        "description": "HTTP cookies"
                    },
                    "query_params": {
                        "type": "object",
                        "description": "URL query parameters"
                    },
                    "timeout": {
                        "type": "string",
                        "default": "30s",
                        "description": "Request timeout"
                    },
                    "retry_attempts": {
                        "type": "integer",
                        "default": 0,
                        "description": "Number of retry attempts"
                    },
                    "env_variables": {
                        "type": "object",
                        "description": "Environment variables for K6 script"
                    },
                    "data_generators": {
                        "type": "object",
                        "description": "Data generators configuration"
                    },
                    "data_file": {
                        "type": "string",
                        "description": "Path to data file (CSV/JSON)"
                    },
                    "payload_template": {
                        "type": "string",
                        "description": "Dynamic payload template with variables"
                    }
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="get_test_results",
            description="Get results from the last K6 test run",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Optional test ID to get specific results"
                    }
                }
            }
        ),
        Tool(
            name="list_test_templates",
            description="List available K6 test templates",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]):
    """Handle tool calls for K6 testing operations."""
    
    try:
        if name == "run_k6_test":
            # Validate and run K6 test
            config = K6TestConfig(**arguments)
            logger.info(f"Running K6 test for {config.url}")
            
            result = await k6_runner.run_test(config)
            
            # Simplest possible response
            return {
                "content": [
                    {"type": "text", "text": result}
                ]
            }
            
        elif name == "get_test_results":
            test_id = arguments.get("test_id")
            results = await k6_runner.get_results(test_id)
            
            return {
                "content": [
                    {"type": "text", "text": results}
                ]
            }
            
        elif name == "list_test_templates":
            templates = await k6_runner.list_templates()
            
            return {
                "content": [
                    {"type": "text", "text": templates}
                ]
            }
            
        else:
            return {
                "content": [
                    {"type": "text", "text": f"Unknown tool: {name}"}
                ],
                "isError": True
            }
            
    except Exception as e:
        logger.error(f"Error executing tool {name}: {str(e)}")
        return {
            "content": [
                {"type": "text", "text": f"Error: {str(e)}"}
            ],
            "isError": True
        }


async def main():
    """Main entry point for the MCP server."""
    logger.info("Starting K6 MCP Server...")
    
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())