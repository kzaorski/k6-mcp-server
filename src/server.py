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
    Resource,
    Prompt,
    TextContent,
)
from pydantic import BaseModel

from k6_runner import K6Runner
from report_instructions import ReportInstructions
from pathlib import Path

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("k6-mcp-server")

# Initialize MCP server
app = Server("k6-mcp-server")

async def _get_safety_instructions() -> str:
    """Load and return critical AI safety instructions."""
    try:
        safety_file = Path(__file__).parent.parent / "AI_SAFETY_CRITICAL.md"
        if safety_file.exists():
            with open(safety_file, 'r', encoding='utf-8') as f:
                content = f.read()
            return f"\n\n🚨🚨🚨 CRITICAL AI SAFETY INSTRUCTIONS 🚨🚨🚨\n{content}"
        else:
            return "\n\n🚨🚨🚨 CRITICAL: DO NOT run additional tests or modify configurations after ANY test result! 🚨🚨🚨"
    except Exception as e:
        return f"\n\n🚨🚨🚨 CRITICAL: Error loading safety instructions: {e} - DO NOT run additional tests! 🚨🚨🚨"

# Initialize K6 runner
k6_runner = K6Runner()

# Cache for pending test configurations
pending_test_configs = {}


class K6TestConfig(BaseModel):
    url: str
    method: str = "GET"
    payload: Optional[Dict[str, Any]] = None
    load_pattern: str = "constant"  # constant, ramp_up, spike
    duration: Optional[str] = "30s"
    iterations: Optional[int] = None  # If set, use iterations instead of duration
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
    
    # Logging options
    log_requests: Optional[bool] = False
    
    # Think time (pause between requests)
    think_time: Optional[float] = 1.0


@app.list_resources()
async def list_resources() -> List[Resource]:
    """List available resources including AI safety instructions."""
    return [
        Resource(
            uri="file://AI_SAFETY_CRITICAL.md",
            name="AI Safety Instructions",
            description="🚨 Critical AI safety instructions for K6 MCP Server. Contains mandatory behavioral rules and response protocols for AI models.",
            mimeType="text/markdown"
        ),
        Resource(
            uri="file://README.md", 
            name="K6 MCP Documentation",
            description="Complete documentation for K6 MCP Server including usage examples and configuration.",
            mimeType="text/markdown"
        )
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Read resource content by URI."""
    # Normalize URI (MCP may lowercase URIs and add trailing slashes)
    normalized_uri = uri.lower().rstrip('/')
    
    if normalized_uri in ["file://ai_safety_critical.md", "file://AI_SAFETY_CRITICAL.md"]:
        safety_instructions = await _get_safety_instructions()
        return safety_instructions
    elif normalized_uri in ["file://readme.md", "file://README.md"]:
        try:
            readme_file = Path(__file__).parent.parent / "README.md"
            if readme_file.exists():
                with open(readme_file, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return "README.md not found"
        except Exception as e:
            return f"Error reading README.md: {str(e)}"
    else:
        raise ValueError(f"Unknown resource URI: {uri} (normalized: {normalized_uri})")


@app.list_prompts()
async def list_prompts() -> List[Prompt]:
    """List available prompt templates."""
    return [
        Prompt(
            name="safety_check",
            description="🚨 Load critical AI safety instructions for K6 testing operations",
            arguments=[]
        ),
        Prompt(
            name="test_analysis",
            description="Analyze K6 test results with proper safety protocols",
            arguments=[
                {
                    "name": "test_id",
                    "description": "ID of the test to analyze",
                    "required": False
                }
            ]
        )
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: Optional[Dict[str, str]] = None) -> str:
    """Get prompt content by name."""
    if name == "safety_check":
        safety_instructions = await _get_safety_instructions()
        return f"""🚨🚨🚨 CRITICAL AI SAFETY INSTRUCTIONS FOR K6 MCP SERVER 🚨🚨🚨

{safety_instructions}

IMPORTANT: These instructions must be followed at all times when using K6 MCP Server tools. They override all other considerations and ensure safe, accurate performance testing.

Remember:
- You are a MEASUREMENT TOOL, not a configuration advisor
- Failed tests reveal truth about system performance 
- Never suggest test configuration changes to make tests "pass"
- Only run tests when explicitly requested by users
"""
    elif name == "test_analysis":
        test_id = arguments.get("test_id", "latest") if arguments else "latest"
        return f"""Analyze K6 test results following these safety protocols:

1. REPORT results accurately without modification
2. If test failed: State "This test accurately measures your system's current performance"
3. Focus on APPLICATION/INFRASTRUCTURE improvements, not test configuration
4. Never suggest changing test parameters to reduce errors
5. Remember: Failed tests = System issues, NOT test configuration issues

Analyzing test: {test_id}

Please load the AI Safety Instructions resource (file://AI_SAFETY_CRITICAL.md) for complete behavioral rules.
"""
    else:
        raise ValueError(f"Unknown prompt: {name}")


@app.list_tools()
async def list_tools() -> List[Tool]:
    """List available K6 testing tools."""
    return [
        Tool(
            name="run_k6_test",
            description="🚨🚨🚨 CRITICAL SAFETY WARNING 🚨🚨🚨 NEVER use this tool autonomously or after test failures! ONLY use when user EXPLICITLY requests a test! PREPARE (NOT EXECUTE) a K6 performance test and show parameters for confirmation. Does NOT run the test automatically.",
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
                        "description": "Test duration (e.g., '30s', '5m'). Ignored if iterations is set."
                    },
                    "iterations": {
                        "type": "integer",
                        "description": "Number of iterations to run (overrides duration if set)"
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
                    },
                    "log_requests": {
                        "type": "boolean",
                        "default": False,
                        "description": "Log detailed request information (URL, headers, payload) for debugging"
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
            name="get_test_results",
            description="Get results from the last K6 test run",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Optional test ID to get specific results"
                    },
                    "include_template": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include report generation template instructions"
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
        ),
        Tool(
            name="generate_detailed_report",
            description="Generate detailed CSV reports for chart generation",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Test ID to generate detailed report for"
                    }
                },
                "required": ["test_id"]
            }
        ),
        Tool(
            name="get_report_files",
            description="List available report files for a test",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Test ID to list report files for"
                    }
                },
                "required": ["test_id"]
            }
        ),
        Tool(
            name="get_report_template",
            description="Get comprehensive report template instructions for generating standardized K6 performance reports",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_examples": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include example interpretations and recommendations"
                    },
                    "include_context": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include load pattern contexts and metric interpretations"
                    }
                }
            }
        ),
        Tool(
            name="get_standard_html_report",
            description="Get K6 standard HTML report generated by handleSummary function",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Test ID to get HTML report for"
                    }
                },
                "required": ["test_id"]
            }
        ),
        Tool(
            name="confirm_and_execute_test",
            description="Respond to test confirmation dialog with y/n and execute if confirmed",
            inputSchema={
                "type": "object",
                "properties": {
                    "response": {
                        "type": "string",
                        "enum": ["y", "n", "yes", "no"],
                        "description": "User response to test confirmation (y/yes to execute, n/no to cancel)"
                    }
                },
                "required": ["response"]
            }
        ),
        Tool(
            name="upload_csv_data",
            description="Upload CSV data content to be used in K6 tests",
            inputSchema={
                "type": "object",
                "properties": {
                    "csv_content": {
                        "type": "string",
                        "description": "CSV file content as string"
                    },
                    "filename": {
                        "type": "string",
                        "default": "uploaded_data.csv",
                        "description": "Filename for the uploaded CSV data"
                    }
                },
                "required": ["csv_content"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]):
    """Handle tool calls for K6 testing operations."""
    
    try:
        if name == "run_k6_test":
            # ⚠️ CRITICAL: This tool should ONLY be used when user explicitly requests a test
            # If used autonomously, this is a violation of safety protocols
            logger.info(f"Received run_k6_test call with arguments: {arguments}")
            config = K6TestConfig(**arguments)
            logger.info(f"Running K6 test for {config.url} - always requiring confirmation")
            
            result = await k6_runner.prepare_test(config)
            
            logger.info(f"Returning result with length: {len(result)}")
            logger.info(f"Result starts with: {result[:200]}...")
            
            # Simplest possible response
            return {
                "content": [
                    {"type": "text", "text": result}
                ]
            }
            
        elif name == "get_test_results":
            test_id = arguments.get("test_id")
            include_template = arguments.get("include_template", False)
            
            results = await k6_runner.get_results(test_id)
            
            # If template instructions are requested, append them
            if include_template:
                template_instructions = "\n\n" + "="*80 + "\n"
                template_instructions += "## 📋 REPORT GENERATION INSTRUCTIONS\n\n"
                template_instructions += "Use the following template to generate a comprehensive report:\n\n"
                template_instructions += ReportInstructions.get_report_template()
                results += template_instructions
            
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
            
        elif name == "generate_detailed_report":
            test_id = arguments.get("test_id")
            if not test_id:
                return {
                    "content": [
                        {"type": "text", "text": "Error: test_id is required"}
                    ],
                    "isError": True
                }
            
            report_result = await k6_runner.generate_detailed_report(test_id)
            
            return {
                "content": [
                    {"type": "text", "text": report_result}
                ]
            }
            
        elif name == "get_report_files":
            test_id = arguments.get("test_id")
            if not test_id:
                return {
                    "content": [
                        {"type": "text", "text": "Error: test_id is required"}
                    ],
                    "isError": True
                }
            
            files_list = await k6_runner.get_report_files(test_id)
            
            return {
                "content": [
                    {"type": "text", "text": files_list}
                ]
            }
            
        elif name == "get_report_template":
            include_examples = arguments.get("include_examples", True)
            include_context = arguments.get("include_context", True)
            
            # Get base template
            template = ReportInstructions.get_report_template()
            
            # Add additional context if requested
            if include_context:
                template += "\n\n" + "="*80 + "\n"
                template += "## 📖 METRIC INTERPRETATION GUIDELINES\n\n"
                
                interpretations = ReportInstructions.get_metric_interpretations()
                for metric, details in interpretations.items():
                    template += f"### {metric.replace('_', ' ').title()}\n"
                    if isinstance(details, dict) and 'unit' in details:
                        template += f"**Unit**: {details['unit']}\n\n"
                        for level, info in details.items():
                            if level != 'unit' and isinstance(info, dict):
                                template += f"- **{level.title()}**: {info['description']}\n"
                    template += "\n"
                
                template += "\n## 🎯 LOAD PATTERN CONTEXTS\n\n"
                contexts = ReportInstructions.get_load_pattern_contexts()
                for pattern, context in contexts.items():
                    template += f"### {pattern.replace('_', ' ').title()} Load Pattern\n"
                    template += context.strip() + "\n\n"
            
            if include_examples:
                template += "\n" + "="*80 + "\n"
                template += "## 💡 RECOMMENDATION TEMPLATES\n\n"
                
                recommendations = ReportInstructions.get_recommendation_templates()
                for issue_type, recs in recommendations.items():
                    template += f"### {issue_type.replace('_', ' ').title()}\n"
                    for rec in recs:
                        template += f"- {rec}\n"
                    template += "\n"
            
            return {
                "content": [
                    {"type": "text", "text": template}
                ]
            }
            
        elif name == "get_standard_html_report":
            test_id = arguments.get("test_id")
            if not test_id:
                return {
                    "content": [
                        {"type": "text", "text": "Error: test_id is required"}
                    ],
                    "isError": True
                }
            
            html_report = await k6_runner.get_standard_html_report(test_id)
            
            return {
                "content": [
                    {"type": "text", "text": html_report}
                ]
            }
            
        elif name == "upload_csv_data":
            csv_content = arguments.get("csv_content")
            filename = arguments.get("filename", "uploaded_data.csv")
            
            if not csv_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: csv_content is required"}
                    ],
                    "isError": True
                }
            
            result = await k6_runner.save_csv_data(csv_content, filename)
            
            return {
                "content": [
                    {"type": "text", "text": result}
                ]
            }
            
        elif name == "confirm_and_execute_test":
            response = arguments.get("response")
            
            if not response:
                return {
                    "content": [
                        {"type": "text", "text": "Error: response is required"}
                    ],
                    "isError": True
                }
            
            result = await k6_runner.confirm_test_execution(response)
            
            return {
                "content": [
                    {"type": "text", "text": result}
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