#!/usr/bin/env python3

import asyncio
import json
import logging
import sys
import time
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
from workflow_manager import WorkflowManager
from multi_request_models import K6WorkflowConfig, K6MultiRequestConfig  # K6MultiRequestConfig for backward compatibility
from har_processor import HARProcessor
from har_models import HARConversionOptions
from pathlib import Path
from security_config import SecurityConfig, AuditLogger
from security_utils import (
    RateLimiter,
    validate_test_id,
    sanitize_url,
    validate_json_payload,
    mask_sensitive_data,
    generate_request_id,
    InputValidationError,
    SecurityError
)
from openapi_processor import OpenAPIProcessor
from openapi_test_generator import SmartTestGenerator
from openapi_models import TestGenerationOptions

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("k6-mcp-server")

# Initialize MCP server
app = Server("k6-mcp-server")


# Initialize security components
security_config = SecurityConfig()
audit_logger = AuditLogger(enabled=security_config.AUDIT_LOG_ENABLED)
rate_limiter = RateLimiter(
    max_requests=security_config.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=security_config.RATE_LIMIT_WINDOW_SECONDS
) if security_config.RATE_LIMIT_ENABLED else None

# Validate security configuration
config_warnings = security_config.validate_configuration()
if config_warnings:
    for warning in config_warnings:
        logger.warning(f"Security configuration warning: {warning}")

# Initialize K6 runner and workflow manager
k6_runner = K6Runner()
workflow_manager = WorkflowManager(
    results_dir=Path(__file__).parent.parent / "reports",
    templates_dir=Path(__file__).parent / "templates"
)
har_processor = HARProcessor()

# Global state storage for MCP calls persistence
# This preserves state between separate MCP tool calls
global_state = {
    'confirmed_test': None,
    'confirmed_workflow': None,
    'last_confirmation_time': None
}

# Initialize OpenAPI components
openapi_processor = OpenAPIProcessor()
openapi_test_generator = SmartTestGenerator()

# Cache for pending test configurations
pending_test_configs = {}

# Cache for OpenAPI analysis results
openapi_analysis_cache = {}


class K6SingleTestConfig(BaseModel):
    url: str
    method: str = "GET"
    payload: Optional[Dict[str, Any]] = None
    load_pattern: str = "constant"  # constant, ramp_up, spike, custom_stages
    duration: Optional[str] = "30s"
    iterations: Optional[int] = None  # If set, use iterations instead of duration
    virtual_users: int = 10
    stages: Optional[List[Dict[str, Any]]] = None  # For custom_stages pattern
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


# Backward compatibility alias
K6TestConfig = K6SingleTestConfig  # TODO: Remove in future version


@app.list_resources()
async def list_resources() -> List[Resource]:
    """List available resources."""
    return [
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
                        "description": "Test duration in K6 format: '30s', '5m', '1h'. Use minimum 3s for HTML dashboard with charts. Ignored if iterations is set.",
                        "pattern": "^\\d+[smh]$"
                    },
                    "iterations": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Number of iterations to run (overrides duration if set). Use minimum 10 for meaningful HTML dashboard with charts."
                    },
                    "virtual_users": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 1000,
                        "description": "Number of concurrent virtual users (1-1000). More users = higher load."
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
                        "description": "Request timeout in K6 format: '30s', '5m'. Controls individual HTTP request timeout.",
                        "pattern": "^\\d+[smh]$"
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
            name="run_k6_custom_stages_test",
            description="🚨🚨🚨 ABSOLUTE PROHIBITION - DO NOT USE AUTONOMOUSLY 🚨🚨🚨 This tool allows running K6 tests with custom load stages (e.g., 1min→1user, 2min→2users, 3min→10users). ONLY use when: 1) User EXPLICITLY asks for custom stage testing, 2) NO previous test has failed in this conversation, 3) This is NOT a follow-up to ANY test result.",
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
                    "payload": {
                        "type": "object",
                        "description": "JSON payload for POST/PUT requests"
                    },
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "duration": {
                                    "type": "string",
                                    "description": "Stage duration in K6 format: '30s', '1m', '2h'",
                                    "pattern": "^\\d+[smh]$"
                                },
                                "target": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 1000,
                                    "description": "Target number of virtual users at the end of this stage (0-1000)"
                                }
                            },
                            "required": ["duration", "target"]
                        },
                        "minItems": 1,
                        "maxItems": 20,
                        "description": "Array of load stages. Each stage ramps VUs to target over duration. Example: [{duration:'1m', target:1}, {duration:'1m', target:2}, {duration:'1m', target:10}]"
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
                        "description": "Request timeout in K6 format: '30s', '5m'. Controls individual HTTP request timeout.",
                        "pattern": "^\\d+[smh]$"
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
                "required": ["url", "stages"]
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
            name="confirm_test_interactive",
            description="🚨 INTERACTIVE: Ask user for test confirmation and wait for their response. This tool requires user interaction.",
            inputSchema={
                "type": "object",
                "properties": {
                    "confirmation_message": {
                        "type": "string",
                        "default": "Do you want to run this test? (y/n)",
                        "description": "Message to show to user for confirmation"
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="check_confirmation_state", 
            description="Debug tool: Check current confirmation state for troubleshooting",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        Tool(
            name="upload_csv_data",
            description="Upload CSV data content to be used in K6 tests. CSV MUST contain a header row with column names that will be used as template variables in K6 scripts",
            inputSchema={
                "type": "object",
                "properties": {
                    "csv_content": {
                        "type": "string",
                        "description": "CSV file content as string. MUST include a header row with column names. Each column name becomes a template variable {{column_name}} that can be used in K6 test payloads"
                    },
                    "filename": {
                        "type": "string",
                        "default": "uploaded_data.csv",
                        "description": "Filename for the uploaded CSV data"
                    }
                },
                "required": ["csv_content"]
            }
        ),
        Tool(
            name="run_k6_workflow_test", 
            description="🚨🚨🚨 ABSOLUTE PROHIBITION - DO NOT USE AUTONOMOUSLY 🚨🚨🚨 This tool is STRICTLY FORBIDDEN for autonomous use. ONLY use when: 1) User EXPLICITLY asks for 'multi-request test', 2) NO previous test has failed in this conversation, 3) This is NOT a follow-up to ANY test result. VIOLATION = UNSAFE BEHAVIOR. This tool ONLY prepares workflows, NEVER executes automatically.",
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow_name": {
                        "type": "string",
                        "description": "Name of the multi-request workflow (must start with letter, contain only letters, numbers, underscore, hyphen - no spaces)",
                        "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of the workflow"
                    },
                    "steps": {
                        "type": "array",
                        "description": "List of request steps in the workflow",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step_id": {"type": "string", "description": "Unique step identifier (must be valid identifier: letters, numbers, underscore, no spaces)", "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$"},
                                "name": {"type": "string", "description": "Human-readable step name"},
                                "url": {"type": "string", "description": "Request URL (may contain template variables like {{variable}}). Must be valid HTTP/HTTPS URL.", "format": "uri"},
                                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
                                "payload": {"type": "object", "description": "Request payload for POST/PUT requests"},
                                "headers": {"type": "object", "description": "Custom HTTP headers"},
                                "extract_variables": {"type": "object", "description": "Variables to extract from response using JSON paths"},
                                "depends_on": {"type": "array", "items": {"type": "string"}, "description": "List of step IDs this step depends on"},
                                "condition": {"type": "string", "description": "Condition for step execution"},
                                "on_failure": {"type": "string", "enum": ["stop", "continue", "retry"], "default": "stop"},
                                "timeout": {"type": "string", "default": "30s"},
                                "think_time": {"type": "number", "default": 1.0}
                            },
                            "required": ["step_id", "name", "url"]
                        }
                    },
                    "virtual_users": {"type": "integer", "default": 1, "minimum": 1, "maximum": 1000, "description": "Number of concurrent virtual users (1-1000). More users = higher load."},
                    "iterations": {"type": "integer", "minimum": 1, "description": "Number of iterations to run (overrides duration if set). Use minimum 10 for meaningful HTML dashboard."},
                    "duration": {"type": "string", "default": "30s", "description": "Test duration"},
                    "execution_mode": {"type": "string", "enum": ["sequential", "parallel"], "default": "sequential"},
                    "load_pattern": {"type": "string", "enum": ["constant", "ramp_up", "spike"], "default": "constant"},
                    "global_headers": {"type": "object", "description": "Headers to apply to all requests"},
                    "stop_on_failure": {"type": "boolean", "default": True},
                    "share_cookies": {"type": "boolean", "default": True},
                    "thresholds": {"type": "object", "description": "Performance thresholds"}
                },
                "required": ["workflow_name", "steps"]
            }
        ),
        Tool(
            name="create_test_workflow",
            description="Create and validate test workflow configuration from templates or custom specification",
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow_type": {
                        "type": "string",
                        "enum": ["auth_flow", "crud_operations", "custom"],
                        "description": "Type of workflow to create"
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Name of predefined template to use"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Parameters for template substitution"
                    },
                    "base_url": {
                        "type": "string",
                        "description": "Base URL for the workflow"
                    }
                },
                "required": ["workflow_type"]
            }
        ),
        Tool(
            name="validate_request_chain",
            description="Validate multi-request chain dependencies, variable references, and configuration",
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow_config": {
                        "type": "object",
                        "description": "Complete workflow configuration to validate"
                    }
                },
                "required": ["workflow_config"]
            }
        ),
        Tool(
            name="list_workflow_templates",
            description="List available workflow templates for multi-request testing",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_workflow_results",
            description="Get results from a multi-request workflow execution",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Test ID of the workflow to get results for"
                    }
                },
                "required": ["test_id"]
            }
        ),
        Tool(
            name="load_har_file",
            description="Load HAR (HTTP Archive) file and convert to K6 multi-request workflow with configurable static files handling",
            inputSchema={
                "type": "object",
                "properties": {
                    "har_content": {
                        "type": "string",
                        "description": "HAR file content as JSON string"
                    },
                    "conversion_options": {
                        "type": "object",
                        "description": "Options for HAR to K6 conversion",
                        "properties": {
                            "detect_authentication": {
                                "type": "boolean", 
                                "default": True,
                                "description": "Automatically detect authentication flows"
                            },
                            "static_files_handling": {
                                "type": "string", 
                                "enum": ["exclude", "include", "simulate", "group"],
                                "default": "exclude",
                                "description": "How to handle static files (CSS, JS, images, etc.)"
                            },
                            "simulate_static_load": {
                                "type": "boolean", 
                                "default": False,
                                "description": "Whether to simulate static file loading timing"
                            },
                            "static_files_parallel": {
                                "type": "boolean", 
                                "default": True,
                                "description": "Load static files in parallel (realistic browser behavior)"
                            },
                            "max_static_files_per_page": {
                                "type": "integer", 
                                "default": 20,
                                "description": "Maximum number of static files to include per page"
                            },
                            "preserve_timing": {
                                "type": "boolean",
                                "default": False,
                                "description": "Preserve original request timing from HAR"
                            },
                            "extract_dynamic_data": {
                                "type": "boolean",
                                "default": True,
                                "description": "Detect and extract dynamic data for response chaining"
                            }
                        }
                    }
                },
                "required": ["har_content"]
            }
        ),
        Tool(
            name="run_k6_har_test", 
            description="🚨🚨🚨 CRITICAL SAFETY WARNING 🚨🚨🚨 NEVER use this tool autonomously! ONLY when user EXPLICITLY requests HAR-based test! Load HAR file and execute K6 performance test with configurable options",
            inputSchema={
                "type": "object",
                "properties": {
                    "har_content": {
                        "type": "string",
                        "description": "HAR file content as JSON string"
                    },
                    "workflow_name": {
                        "type": "string",
                        "description": "Name for the generated workflow (must start with letter, contain only letters, numbers, underscore, hyphen - no spaces)",
                        "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$"
                    },
                    "test_options": {
                        "type": "object",
                        "description": "K6 test execution options",
                        "properties": {
                            "virtual_users": {"type": "integer", "default": 1},
                            "duration": {"type": "string", "default": "30s"},
                            "iterations": {"type": "integer", "description": "Number of iterations instead of duration"},
                            "load_pattern": {
                                "type": "string", 
                                "enum": ["constant", "ramp_up", "spike"],
                                "default": "constant"
                            }
                        }
                    },
                    "conversion_options": {
                        "type": "object",
                        "description": "HAR conversion options (same as load_har_file)",
                        "properties": {
                            "static_files_handling": {
                                "type": "string", 
                                "enum": ["exclude", "include", "simulate", "group"],
                                "default": "exclude"
                            },
                            "preserve_timing": {"type": "boolean", "default": False},
                            "extract_dynamic_data": {"type": "boolean", "default": True}
                        }
                    }
                },
                "required": ["har_content"]
            }
        ),
        Tool(
            name="analyze_har_structure",
            description="Analyze HAR file structure to understand requests, potential chaining opportunities, and static files distribution",
            inputSchema={
                "type": "object",
                "properties": {
                    "har_content": {
                        "type": "string",
                        "description": "HAR file content as JSON string"
                    },
                    "include_recommendations": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include optimization recommendations"
                    }
                },
                "required": ["har_content"]
            }
        ),
        Tool(
            name="import_openapi_spec",
            description="Import and analyze OpenAPI/Swagger specification from URL or file content to understand API structure and generate test scenarios",
            inputSchema={
                "type": "object", 
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "OpenAPI spec URL (http/https) or file path"
                    },
                    "spec_content": {
                        "type": "string",
                        "description": "OpenAPI spec content as JSON or YAML string (alternative to source)"
                    },
                    "analyze_patterns": {
                        "type": "boolean",
                        "default": True,
                        "description": "Analyze API patterns for intelligent test generation"
                    },
                    "include_auth_analysis": {
                        "type": "boolean",
                        "default": True,
                        "description": "Analyze authentication flows and security schemes"
                    }
                }
            }
        ),
        Tool(
            name="generate_tests_from_openapi",
            description="🚨🚨🚨 CRITICAL SAFETY WARNING 🚨🚨🚨 NEVER use this tool autonomously! ONLY when user EXPLICITLY requests OpenAPI-based test generation! Generate intelligent K6 tests from OpenAPI specification with advanced pattern detection",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string",
                        "description": "OpenAPI specification ID from previous import (optional if providing spec_content)"
                    },
                    "spec_content": {
                        "type": "string", 
                        "description": "OpenAPI spec content as JSON or YAML string (alternative to spec_id)"
                    },
                    "test_type": {
                        "type": "string",
                        "enum": ["single_endpoints", "auth_flows", "crud_workflows", "complete_workflows", "intelligent_all"],
                        "default": "intelligent_all",
                        "description": "Type of tests to generate"
                    },
                    "generation_options": {
                        "type": "object",
                        "properties": {
                            "virtual_users": {"type": "integer", "default": 1, "description": "Number of virtual users"},
                            "duration": {"type": "string", "default": "30s", "description": "Test duration"},
                            "include_examples": {"type": "boolean", "default": True},
                            "include_schema_validation": {"type": "boolean", "default": False},
                            "max_array_items": {"type": "integer", "default": 3},
                            "max_string_length": {"type": "integer", "default": 50},
                            "think_time": {"type": "number", "default": 1.0}
                        }
                    }
                }
            }
        ),
        Tool(
            name="analyze_openapi_coverage",
            description="Analyze OpenAPI specification to understand endpoint coverage, complexity, and testing recommendations",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string",
                        "description": "OpenAPI specification ID from previous import (optional if providing spec_content)"
                    },
                    "spec_content": {
                        "type": "string",
                        "description": "OpenAPI spec content as JSON or YAML string (alternative to spec_id)"
                    },
                    "include_recommendations": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include testing strategy recommendations"
                    }
                }
            }
        ),
        Tool(
            name="preview_openapi_tests",
            description="Preview test scenarios that would be generated from OpenAPI specification without creating actual tests",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string", 
                        "description": "OpenAPI specification ID from previous import (optional if providing spec_content)"
                    },
                    "spec_content": {
                        "type": "string",
                        "description": "OpenAPI spec content as JSON or YAML string (alternative to spec_id)"
                    },
                    "workflow_type": {
                        "type": "string",
                        "enum": ["auth", "crud", "search", "pagination", "all"],
                        "default": "all",
                        "description": "Type of workflow patterns to preview"
                    }
                }
            }
        ),
        Tool(
            name="select_openapi_endpoints",
            description="Select specific endpoints from OpenAPI specification for targeted test generation and preview endpoint selection results",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {
                        "type": "string",
                        "description": "OpenAPI specification ID from previous import (optional if providing spec_content)"
                    },
                    "spec_content": {
                        "type": "string",
                        "description": "OpenAPI spec content as JSON or YAML string (alternative to spec_id)"
                    },
                    "endpoints": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "API endpoint path"},
                                "method": {
                                    "type": "string", 
                                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"],
                                    "description": "HTTP method"
                                },
                                "include": {
                                    "type": "boolean", 
                                    "default": True, 
                                    "description": "Whether to include this endpoint"
                                },
                                "priority": {
                                    "type": "integer", 
                                    "default": 1, 
                                    "description": "Priority level (1=high, 2=medium, 3=low)"
                                },
                                "custom_name": {
                                    "type": "string", 
                                    "description": "Custom name for the endpoint in tests"
                                }
                            },
                            "required": ["path", "method"]
                        },
                        "description": "List of specific endpoints to select"
                    },
                    "filter_criteria": {
                        "type": "object",
                        "properties": {
                            "include_methods": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Only include these HTTP methods"
                            },
                            "exclude_methods": {
                                "type": "array", 
                                "items": {"type": "string"},
                                "description": "Exclude these HTTP methods"
                            },
                            "include_tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Only include endpoints with these OpenAPI tags"
                            },
                            "exclude_tags": {
                                "type": "array",
                                "items": {"type": "string"}, 
                                "description": "Exclude endpoints with these OpenAPI tags"
                            },
                            "path_pattern": {
                                "type": "string",
                                "description": "Regular expression to match endpoint paths"
                            },
                            "requires_auth": {
                                "type": "boolean",
                                "description": "Filter by authentication requirement"
                            },
                            "is_crud": {
                                "type": "boolean",
                                "description": "Filter by CRUD operation classification"
                            },
                            "description_contains": {
                                "type": "string",
                                "description": "Filter by endpoints containing this text in summary/description"
                            }
                        },
                        "description": "Advanced filtering criteria for endpoint selection"
                    },
                    "preview_only": {
                        "type": "boolean",
                        "default": True,
                        "description": "Only preview selection, don't generate tests"
                    }
                }
            }
        ),
        Tool(
            name="analyze_url_performance",
            description="Analyze response times per URL from K6 test results. Shows detailed performance statistics (min, max, avg, p50, p90, p95, p99) grouped by URL and HTTP method.",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_id": {
                        "type": "string",
                        "description": "Specific test ID to analyze (optional - if not provided, analyzes latest test)"
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 0,
                        "description": "Show only top N slowest URLs (0 = show all)"
                    },
                    "group_by_domain": {
                        "type": "boolean",
                        "default": False,
                        "description": "Group results by domain instead of full URL"
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["table", "json"],
                        "default": "table",
                        "description": "Output format for results"
                    }
                }
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]):
    """Handle tool calls for K6 testing operations."""
    
    try:
        if name in ("run_k6_single_test", "run_k6_test"):  # Support both old and new names
            # 🚨🚨🚨 CRITICAL SAFETY CHECK 🚨🚨🚨
            # This tool is FORBIDDEN for autonomous use
            logger.warning("🚨 SAFETY ALERT: run_k6_test tool was called - this should ONLY happen on explicit user request")
            logger.warning("🚨 If this was called autonomously by AI, this is a SAFETY VIOLATION")
            
            config = K6SingleTestConfig(**arguments)
            logger.info(f"Preparing K6 test for {config.url} - PREPARATION ONLY, NOT EXECUTION")
            
            result = await k6_runner.prepare_test(config)
            
            logger.info(f"Returning result with length: {len(result)}")
            
            return {
                "content": [
                    {"type": "text", "text": result}
                ]
            }
            
        elif name == "run_k6_custom_stages_test":
            # 🚨🚨🚨 CRITICAL SAFETY CHECK 🚨🚨🚨
            # This tool is FORBIDDEN for autonomous use
            logger.warning("🚨 SAFETY ALERT: run_k6_custom_stages_test tool was called - this should ONLY happen on explicit user request")
            logger.warning("🚨 If this was called autonomously by AI, this is a SAFETY VIOLATION")
            
            # Set load_pattern to custom_stages and prepare config
            arguments['load_pattern'] = 'custom_stages'
            config = K6SingleTestConfig(**arguments)
            logger.info(f"Preparing K6 custom stages test for {config.url} with {len(config.stages)} stages - PREPARATION ONLY, NOT EXECUTION")
            
            result = await k6_runner.prepare_test(config)
            
            logger.info(f"Returning custom stages result with length: {len(result)}")
            
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
            
        elif name == "confirm_test":
            response = arguments.get("response", "n")  # Default to "n" for safety
            
            if not response:
                response = "n"  # Fallback safety
            
            # Check if this is a workflow confirmation or single test confirmation
            if workflow_manager.pending_workflow:
                result = await workflow_manager.confirm_workflow(response)
                # Save to global state for MCP persistence
                if "confirmed and ready" in result:
                    global_state['confirmed_workflow'] = workflow_manager.confirmed_workflow
                    global_state['confirmed_test'] = None
                    global_state['last_confirmation_time'] = time.time()
                    logger.info("Workflow confirmed and saved to global state")
            else:
                result = await k6_runner.confirm_test(response)
                # Save to global state for MCP persistence  
                if "confirmed and ready" in result:
                    global_state['confirmed_test'] = k6_runner.confirmed_config
                    global_state['confirmed_workflow'] = None
                    global_state['last_confirmation_time'] = time.time()
                    logger.info("Test confirmed and saved to global state")
            
            return {
                "content": [
                    {"type": "text", "text": result}
                ]
            }
            
        elif name == "execute_confirmed_test":
            # Execute previously confirmed test using global state
            
            # Check global state first (for MCP persistence)
            if global_state['confirmed_workflow'] is not None:
                # Restore workflow state and execute
                workflow_manager.confirmed_workflow = global_state['confirmed_workflow']
                result = await workflow_manager.execute_confirmed_workflow()
                # Clear global state after execution
                global_state['confirmed_workflow'] = None
                global_state['last_confirmation_time'] = None
                logger.info("Workflow executed from global state")
                
            elif global_state['confirmed_test'] is not None:
                # Restore test state and execute
                k6_runner.confirmed_config = global_state['confirmed_test']
                result = await k6_runner.execute_confirmed_test()
                # Clear global state after execution
                global_state['confirmed_test'] = None
                global_state['last_confirmation_time'] = None
                logger.info("Test executed from global state")
                
            # Fallback to local state (backward compatibility)
            elif workflow_manager.confirmed_workflow is not None:
                result = await workflow_manager.execute_confirmed_workflow()
            elif k6_runner.confirmed_config is not None:
                result = await k6_runner.execute_confirmed_test()
            else:
                result = "No confirmed test ready for execution. Use confirm_test first."
            
            return {
                "content": [
                    {"type": "text", "text": result}
                ]
            }
            
        elif name == "confirm_test_interactive":
            # Interactive confirmation tool
            confirmation_message = arguments.get("confirmation_message", "Do you want to run this test? (y/n)")
            
            # Check what's pending
            if workflow_manager.pending_workflow:
                config = workflow_manager.pending_workflow['config']
                test_type = f"workflow '{config.workflow_name}' ({len(config.steps)} steps)"
            elif k6_runner.pending_config:
                config = k6_runner.pending_config['config']
                test_type = f"test for {config.url}"
            else:
                return {
                    "content": [
                        {"type": "text", "text": "No pending test or workflow to confirm. Please run a test preparation tool first."}
                    ],
                    "isError": True
                }
            
            # Return interactive confirmation request
            interactive_message = f"""
🎯 **Test Ready for Confirmation**

**Pending {test_type}**

{confirmation_message}

**Instructions:**
1. Type "y" or "yes" to confirm and proceed
2. Type "n" or "no" to cancel the test
3. Use `confirm_test` tool with your response

⚠️ **This requires your explicit response - the test will NOT run automatically**
"""
            
            return {
                "content": [
                    {"type": "text", "text": interactive_message}
                ]
            }
            
        elif name == "check_confirmation_state":
            # Debug tool to check confirmation state
            
            # Check global state
            global_test = global_state.get('confirmed_test')
            global_workflow = global_state.get('confirmed_workflow') 
            global_time = global_state.get('last_confirmation_time')
            
            # Check local state  
            local_test = k6_runner.confirmed_config
            local_workflow = workflow_manager.confirmed_workflow
            pending_test = k6_runner.pending_config
            pending_workflow = workflow_manager.pending_workflow
            
            state_report = f"""
🔍 **Confirmation State Debug Report**

**Global State (MCP Persistence):**
• Confirmed Test: {'Yes' if global_test else 'None'}
• Confirmed Workflow: {'Yes' if global_workflow else 'None'}  
• Last Confirmation: {time.strftime('%H:%M:%S', time.localtime(global_time)) if global_time else 'None'}

**Local State (Instance):**
• Confirmed Test: {'Yes' if local_test else 'None'}
• Confirmed Workflow: {'Yes' if local_workflow else 'None'}
• Pending Test: {'Yes' if pending_test else 'None'} 
• Pending Workflow: {'Yes' if pending_workflow else 'None'}

**Ready for Execution:**
• Global Ready: {'Yes' if (global_test or global_workflow) else 'No'}
• Local Ready: {'Yes' if (local_test or local_workflow) else 'No'}

**Next Steps:**
{f'• Use execute_confirmed_test to run the confirmed test' if (global_test or global_workflow or local_test or local_workflow) else '• No confirmed tests - use confirm_test first'}
"""
            
            return {
                "content": [
                    {"type": "text", "text": state_report}
                ]
            }
            
        elif name in ("run_k6_workflow_test", "run_k6_multi_request_test"):  # Support both old and new names
            # 🚨🚨🚨 CRITICAL SAFETY CHECK 🚨🚨🚨
            logger.warning("🚨 SAFETY ALERT: run_k6_multi_request_test tool was called - this should ONLY happen on explicit user request")
            logger.warning("🚨 If this was called autonomously by AI, this is a SAFETY VIOLATION")
            
            try:
                config = K6WorkflowConfig(**arguments)
                logger.info(f"Preparing K6 multi-request workflow '{config.workflow_name}' - PREPARATION ONLY, NOT EXECUTION")
                
                result = await workflow_manager.prepare_workflow(config)
                
                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error preparing multi-request workflow: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error preparing workflow: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "create_test_workflow":
            workflow_type = arguments.get("workflow_type")
            template_name = arguments.get("template_name")
            parameters = arguments.get("parameters", {})
            
            if not workflow_type:
                return {
                    "content": [
                        {"type": "text", "text": "Error: workflow_type is required"}
                    ],
                    "isError": True
                }
            
            try:
                if template_name:
                    result = await workflow_manager.create_workflow_from_template(template_name, parameters)
                else:
                    # Create basic workflow based on type
                    if workflow_type == "auth_flow":
                        result = await workflow_manager.create_workflow_from_template("oauth_login_flow", parameters)
                    elif workflow_type == "crud_operations":
                        result = await workflow_manager.create_workflow_from_template("crud_operations", parameters)
                    else:
                        result = "Custom workflow creation not yet implemented. Use run_k6_workflow_test directly."
                
                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error creating workflow: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error creating workflow: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "validate_request_chain":
            workflow_config = arguments.get("workflow_config")
            
            if not workflow_config:
                return {
                    "content": [
                        {"type": "text", "text": "Error: workflow_config is required"}
                    ],
                    "isError": True
                }
            
            try:
                config = K6WorkflowConfig(**workflow_config)
                validation_errors = await workflow_manager.validate_workflow(config)
                
                if validation_errors:
                    error_msg = "Workflow validation failed:\n" + "\n".join(f"• {error}" for error in validation_errors)
                    return {
                        "content": [
                            {"type": "text", "text": error_msg}
                        ]
                    }
                else:
                    return {
                        "content": [
                            {"type": "text", "text": "✅ Workflow validation passed successfully"}
                        ]
                    }
                
            except Exception as e:
                logger.error(f"Error validating workflow: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error validating workflow: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "list_workflow_templates":
            try:
                result = await workflow_manager.list_workflow_templates()
                
                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error listing workflow templates: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error listing templates: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "get_workflow_results":
            test_id = arguments.get("test_id")
            
            if not test_id:
                return {
                    "content": [
                        {"type": "text", "text": "Error: test_id is required"}
                    ],
                    "isError": True
                }
            
            try:
                result = await workflow_manager.get_workflow_results(test_id)
                
                if result:
                    # Format workflow result
                    formatted_result = workflow_manager._format_workflow_report(result)
                    return {
                        "content": [
                            {"type": "text", "text": formatted_result}
                        ]
                    }
                else:
                    return {
                        "content": [
                            {"type": "text", "text": f"No workflow results found for test ID: {test_id}"}
                        ]
                    }
                
            except Exception as e:
                logger.error(f"Error getting workflow results: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error getting workflow results: {str(e)}"}
                    ],
                    "isError": True
                }
            
        elif name == "load_har_file":
            har_content = arguments.get("har_content")
            conversion_options_dict = arguments.get("conversion_options", {})
            
            if not har_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: har_content is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Parse conversion options
                conversion_options = HARConversionOptions(**conversion_options_dict)
                har_processor.options = conversion_options
                
                # Parse HAR file
                har_file = har_processor.parse_har_file(har_content)
                
                # Convert to K6 workflow
                workflow_config = har_processor.convert_har_to_workflow(har_file)
                
                # Format response
                result = f"""✅ HAR File Successfully Loaded and Converted

📊 Workflow Generated: {workflow_config.workflow_name}
📝 Description: {workflow_config.description}
🔗 Request Steps: {len(workflow_config.steps)}

🔧 Conversion Options Applied:
• Static Files: {conversion_options.static_files_handling.value}
• Extract Dynamic Data: {'Yes' if conversion_options.extract_dynamic_data else 'No'}
• Preserve Timing: {'Yes' if conversion_options.preserve_timing else 'No'}

📋 Generated Workflow Configuration:
{json.dumps(workflow_config.model_dump(), indent=2)}

🚀 Ready for Execution:
You can now use 'run_k6_workflow_test' with this configuration or 
use 'run_k6_har_test' for direct execution."""

                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error processing HAR file: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error processing HAR file: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name in ("run_k6_har_test", "har_to_k6_test"):  # Support both old and new names
            # ⚠️ CRITICAL: This tool should ONLY be used when user explicitly requests a HAR-based test
            har_content = arguments.get("har_content")
            workflow_name = arguments.get("workflow_name")
            test_options = arguments.get("test_options", {})
            conversion_options_dict = arguments.get("conversion_options", {})
            
            if not har_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: har_content is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Parse conversion options
                conversion_options = HARConversionOptions(**conversion_options_dict)
                har_processor.options = conversion_options
                
                # Parse HAR file and convert to workflow
                har_file = har_processor.parse_har_file(har_content)
                workflow_config = har_processor.convert_har_to_workflow(har_file, workflow_name)
                
                # Apply test options to workflow config
                if test_options.get("virtual_users"):
                    workflow_config.virtual_users = test_options["virtual_users"]
                if test_options.get("duration"):
                    workflow_config.duration = test_options["duration"]
                if test_options.get("iterations"):
                    workflow_config.iterations = test_options["iterations"]
                if test_options.get("load_pattern"):
                    workflow_config.load_pattern = test_options["load_pattern"]
                
                # Execute the workflow via workflow manager
                result = await workflow_manager.prepare_workflow(workflow_config)
                
                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error executing HAR-based test: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error executing HAR-based test: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "analyze_har_structure":
            har_content = arguments.get("har_content")
            include_recommendations = arguments.get("include_recommendations", True)
            
            if not har_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: har_content is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Parse and analyze HAR file
                har_file = har_processor.parse_har_file(har_content)
                analysis = har_processor.analyze_har_file(har_file)
                
                # Format analysis result
                result = f"""📊 HAR File Structure Analysis
{'=' * 50}

📈 Overview:
• Total Requests: {analysis.total_requests}
• Unique Domains: {len(analysis.unique_domains)}
• Page Groups: {len(analysis.page_groups)}

🔍 Request Types Distribution:
{chr(10).join(f'• {req_type.title()}: {count} ({count/analysis.total_requests*100:.1f}%)' 
              for req_type, count in analysis.request_types.items())}

🌐 Domains:
{chr(10).join(f'• {domain}' for domain in analysis.unique_domains[:10])}
{'• ... and more' if len(analysis.unique_domains) > 10 else ''}

📄 Page Structure:
{chr(10).join(f'• Page {i+1}: {group.total_requests} requests ({group.static_files_count} static files)' 
              for i, group in enumerate(analysis.page_groups[:5]))}
{'• ... and more pages' if len(analysis.page_groups) > 5 else ''}

🔗 Response Chaining Opportunities:
• Detected {len(analysis.potential_chains)} potential chains
{chr(10).join(f'• {chain.source_step_id} → {chain.target_step_id} ({chain.chain_type})' 
              for chain in analysis.potential_chains[:5])}
{'• ... and more chains' if len(analysis.potential_chains) > 5 else ''}

📁 Static Files Summary:
• Total Static Files: {analysis.static_files_summary.get('total_static_files', 0)}
• Static Files Ratio: {analysis.static_files_ratio:.1f}%
• File Types: {analysis.static_files_summary.get('file_types', {})}

⏱️ Timing Analysis:
• Avg Response Time: {analysis.timing_analysis.get('avg_response_time', 0):.0f}ms
• Session Duration: {analysis.timing_analysis.get('total_session_duration', 0):.1f}s
• Max Gap Between Requests: {analysis.timing_analysis.get('max_gap', 0):.1f}s"""

                if include_recommendations and analysis.recommendations:
                    result += f"\n\n💡 Recommendations:\n"
                    result += "\n".join(f"• {rec}" for rec in analysis.recommendations)

                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error analyzing HAR structure: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error analyzing HAR structure: {str(e)}"}
                    ],
                    "isError": True
                }

        elif name == "import_openapi_spec":
            source = arguments.get("source")
            spec_content = arguments.get("spec_content")
            analyze_patterns = arguments.get("analyze_patterns", True)
            include_auth_analysis = arguments.get("include_auth_analysis", True)
            
            if not source and not spec_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: Either 'source' (URL/file path) or 'spec_content' is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Load OpenAPI specification
                if spec_content:
                    # Parse content directly
                    import yaml
                    try:
                        spec_dict = yaml.safe_load(spec_content)
                    except yaml.YAMLError:
                        spec_dict = safe_json_parse(spec_content)
                    spec = await openapi_processor.load_openapi_spec(spec_dict)
                else:
                    # Load from source
                    spec = await openapi_processor.load_openapi_spec(source)
                
                # Generate unique spec ID
                import hashlib
                spec_id = hashlib.md5(f"{spec.info.title}_{spec.info.version}".encode()).hexdigest()[:8]
                
                # Analyze API if requested
                analysis = None
                if analyze_patterns:
                    analysis = openapi_processor.analyze_api(spec)
                    openapi_analysis_cache[spec_id] = analysis
                
                # Build response
                result = f"""✅ OpenAPI Specification Imported Successfully

📋 API Information:
• Title: {spec.info.title}
• Version: {spec.info.version}
• Description: {spec.info.description or 'No description provided'}
• Spec ID: {spec_id}

📊 API Structure:
• Total Endpoints: {len(spec.get_all_endpoints())}
• Base URL: {spec.get_base_url()}
• Authentication Required: {'Yes' if spec.has_authentication() else 'No'}"""

                if analysis:
                    result += f"""

🔍 Pattern Analysis:
• Authentication Endpoints: {len(analysis.auth_endpoints)}
• CRUD Resources: {len(analysis.crud_resources)}
• Workflow Suggestions: {len(analysis.workflow_suggestions)}"""
                    
                    if include_auth_analysis and analysis.auth_endpoints:
                        result += f"\n\n🔐 Authentication Endpoints:"
                        for auth_ep in analysis.auth_endpoints[:3]:
                            result += f"\n• {auth_ep.method.value} {auth_ep.path}"
                        if len(analysis.auth_endpoints) > 3:
                            result += f"\n• ... and {len(analysis.auth_endpoints) - 3} more"
                    
                    if analysis.crud_resources:
                        result += f"\n\n📚 CRUD Resources:"
                        for resource_name, endpoints in list(analysis.crud_resources.items())[:3]:
                            operations = [ep.method.value for ep in endpoints]
                            result += f"\n• {resource_name}: {', '.join(operations)}"
                        if len(analysis.crud_resources) > 3:
                            result += f"\n• ... and {len(analysis.crud_resources) - 3} more resources"
                    
                    if analysis.workflow_suggestions:
                        result += f"\n\n💡 Suggested Test Scenarios:"
                        for suggestion in analysis.workflow_suggestions[:3]:
                            result += f"\n• {suggestion['name']}: {suggestion['description']}"
                        if len(analysis.workflow_suggestions) > 3:
                            result += f"\n• ... and {len(analysis.workflow_suggestions) - 3} more suggestions"

                result += f"\n\n🎯 Next Steps:\n• Use 'generate_tests_from_openapi' with spec_id '{spec_id}' to create tests\n• Use 'preview_openapi_tests' to see test scenarios before generation\n• Use 'analyze_openapi_coverage' for detailed analysis"

                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error importing OpenAPI spec: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error importing OpenAPI specification: {str(e)}"}
                    ],
                    "isError": True
                }

        elif name == "generate_tests_from_openapi":
            spec_id = arguments.get("spec_id")
            spec_content = arguments.get("spec_content")
            test_type = arguments.get("test_type", "intelligent_all")
            generation_options = arguments.get("generation_options", {})
            
            if not spec_id and not spec_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: Either 'spec_id' or 'spec_content' is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Get or load analysis
                if spec_id and spec_id in openapi_analysis_cache:
                    analysis = openapi_analysis_cache[spec_id]
                else:
                    # Load spec and analyze
                    if spec_content:
                        import yaml
                        try:
                            spec_dict = yaml.safe_load(spec_content)
                        except yaml.YAMLError:
                            spec_dict = safe_json_parse(spec_content)
                        spec = await openapi_processor.load_openapi_spec(spec_dict)
                    else:
                        return {
                            "content": [
                                {"type": "text", "text": f"Error: spec_id '{spec_id}' not found. Please import the specification first."}
                            ],
                            "isError": True
                        }
                    
                    analysis = openapi_processor.analyze_api(spec)
                
                # Create generation options
                options = TestGenerationOptions(**generation_options)
                
                # Configure test generation based on type
                if test_type == "single_endpoints":
                    options.generate_workflow_tests = False
                elif test_type == "auth_flows":
                    options.generate_single_endpoint_tests = False
                    options.generate_crud_workflows = False
                elif test_type == "crud_workflows":
                    options.generate_single_endpoint_tests = False
                    options.generate_auth_workflows = False
                
                # Generate tests
                test_configs = openapi_test_generator.generate_intelligent_tests(analysis, options)
                
                if not test_configs:
                    return {
                        "content": [
                            {"type": "text", "text": "No tests could be generated from the OpenAPI specification. The API might not have suitable endpoints for the selected test type."}
                        ]
                    }
                
                # Format results
                result = f"""🎯 Generated {len(test_configs)} Test Configurations from OpenAPI Specification

📋 Test Generation Summary:
• API: {analysis.spec.info.title} v{analysis.spec.info.version}
• Test Type: {test_type}
• Total Test Configs: {len(test_configs)}
• Virtual Users: {options.virtual_users}
• Duration: {options.duration}

📝 Generated Test Configurations:"""

                for i, config in enumerate(test_configs[:10], 1):  # Show first 10
                    result += f"\n{i}. {config.workflow_name}: {config.description} ({len(config.steps)} steps)"
                
                if len(test_configs) > 10:
                    result += f"\n... and {len(test_configs) - 10} more test configurations"

                result += f"""

✅ Tests Ready for Execution:
• Use 'run_k6_workflow_test' with any of the generated configurations
• Each test includes intelligent data generation and response chaining
• Authentication flows and CRUD operations are automatically handled

💡 Pro Tip: Start with authentication flows first, then proceed with CRUD operations for comprehensive API testing."""

                # Store generated configs for easy access (you might want to implement this)
                # For now, just return the summary
                
                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error generating tests from OpenAPI: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error generating tests: {str(e)}"}
                    ],
                    "isError": True
                }

        elif name == "analyze_openapi_coverage":
            spec_id = arguments.get("spec_id")
            spec_content = arguments.get("spec_content")
            include_recommendations = arguments.get("include_recommendations", True)
            
            if not spec_id and not spec_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: Either 'spec_id' or 'spec_content' is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Get or load analysis
                if spec_id and spec_id in openapi_analysis_cache:
                    analysis = openapi_analysis_cache[spec_id]
                else:
                    # Load and analyze
                    if spec_content:
                        import yaml
                        try:
                            spec_dict = yaml.safe_load(spec_content)
                        except yaml.YAMLError:
                            spec_dict = safe_json_parse(spec_content)
                        spec = await openapi_processor.load_openapi_spec(spec_dict)
                        analysis = openapi_processor.analyze_api(spec)
                    else:
                        return {
                            "content": [
                                {"type": "text", "text": f"Error: spec_id '{spec_id}' not found. Please import the specification first."}
                            ],
                            "isError": True
                        }

                # Build comprehensive analysis
                spec = analysis.spec
                endpoints = analysis.endpoints
                
                # Calculate statistics
                method_stats = {}
                auth_required_count = 0
                has_request_body = 0
                has_path_params = 0
                has_query_params = 0
                
                for endpoint in endpoints:
                    method = endpoint.method.value
                    method_stats[method] = method_stats.get(method, 0) + 1
                    
                    if endpoint.requires_auth:
                        auth_required_count += 1
                    if endpoint.request_body_schema:
                        has_request_body += 1
                    if endpoint.path_params:
                        has_path_params += 1
                    if endpoint.query_params:
                        has_query_params += 1

                result = f"""📊 OpenAPI Coverage Analysis

🎯 API Overview:
• Title: {spec.info.title}
• Version: {spec.info.version}
• Base URL: {spec.get_base_url()}
• Total Endpoints: {len(endpoints)}

📈 HTTP Methods Distribution:"""
                for method, count in sorted(method_stats.items()):
                    percentage = (count / len(endpoints)) * 100
                    result += f"\n• {method}: {count} endpoints ({percentage:.1f}%)"

                result += f"""

🔐 Security Analysis:
• Authenticated Endpoints: {auth_required_count} ({(auth_required_count/len(endpoints)*100):.1f}%)
• Authentication Required: {'Yes' if spec.has_authentication() else 'No'}
• Security Schemes: {len(spec.get_security_schemes())}

📝 Request Complexity:
• Endpoints with Request Body: {has_request_body} ({(has_request_body/len(endpoints)*100):.1f}%)
• Endpoints with Path Parameters: {has_path_params} ({(has_path_params/len(endpoints)*100):.1f}%)
• Endpoints with Query Parameters: {has_query_params} ({(has_query_params/len(endpoints)*100):.1f}%)

🏗️ Architecture Patterns:
• CRUD Resources Detected: {len(analysis.crud_resources)}
• Authentication Endpoints: {len(analysis.auth_endpoints)}
• Potential Workflows: {len(analysis.workflow_suggestions)}"""

                if analysis.crud_resources:
                    result += f"\n\n📚 CRUD Resources:"
                    for resource_name, resource_endpoints in analysis.crud_resources.items():
                        operations = [ep.method.value for ep in resource_endpoints]
                        completeness = len(set(operations) & {'GET', 'POST', 'PUT', 'DELETE'}) / 4 * 100
                        result += f"\n• {resource_name}: {', '.join(operations)} (CRUD completeness: {completeness:.0f}%)"

                if include_recommendations:
                    result += f"\n\n💡 Testing Recommendations:"
                    
                    if analysis.auth_endpoints:
                        result += f"\n• Start with authentication flow testing to establish session management"
                    
                    if analysis.crud_resources:
                        complete_crud = [name for name, eps in analysis.crud_resources.items() 
                                       if len(set(ep.method.value for ep in eps) & {'GET', 'POST', 'PUT', 'DELETE'}) >= 3]
                        if complete_crud:
                            result += f"\n• Focus on complete CRUD testing for: {', '.join(complete_crud[:3])}"
                    
                    if auth_required_count > len(endpoints) * 0.5:
                        result += f"\n• High authentication requirement ({auth_required_count}/{len(endpoints)}) - prioritize auth flow testing"
                    
                    if has_request_body > 0:
                        result += f"\n• {has_request_body} endpoints require payload testing - ensure data validation scenarios"
                    
                    if method_stats.get('GET', 0) > len(endpoints) * 0.6:
                        result += f"\n• Read-heavy API detected - consider load testing for GET endpoints"
                    
                    result += f"\n• Recommended test approach: Auth → CRUD → Edge cases → Load testing"

                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error analyzing OpenAPI coverage: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error analyzing OpenAPI coverage: {str(e)}"}
                    ],
                    "isError": True
                }

        elif name == "preview_openapi_tests":
            spec_id = arguments.get("spec_id")
            spec_content = arguments.get("spec_content")
            workflow_type = arguments.get("workflow_type", "all")
            
            if not spec_id and not spec_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: Either 'spec_id' or 'spec_content' is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Get or load analysis
                if spec_id and spec_id in openapi_analysis_cache:
                    analysis = openapi_analysis_cache[spec_id]
                else:
                    # Load and analyze
                    if spec_content:
                        import yaml
                        try:
                            spec_dict = yaml.safe_load(spec_content)
                        except yaml.YAMLError:
                            spec_dict = safe_json_parse(spec_content)
                        spec = await openapi_processor.load_openapi_spec(spec_dict)
                        analysis = openapi_processor.analyze_api(spec)
                    else:
                        return {
                            "content": [
                                {"type": "text", "text": f"Error: spec_id '{spec_id}' not found. Please import the specification first."}
                            ],
                            "isError": True
                        }

                # Detect workflow patterns
                patterns = openapi_test_generator._detect_all_patterns(analysis)
                
                # Filter by workflow type
                if workflow_type != "all":
                    patterns = [p for p in patterns if p.pattern_type == workflow_type]

                result = f"""🔍 OpenAPI Test Scenarios Preview

📋 API: {analysis.spec.info.title} v{analysis.spec.info.version}
🎯 Workflow Type: {workflow_type}
📊 Detected Patterns: {len(patterns)}

🚀 Test Scenarios That Would Be Generated:"""

                if not patterns:
                    result += f"\n\nNo patterns detected for workflow type '{workflow_type}'. Try 'all' to see all available patterns."
                else:
                    for i, pattern in enumerate(patterns, 1):
                        result += f"""

{i}. {pattern.name} (Priority: {pattern.priority})
   📝 Description: {pattern.description}
   🔗 Steps: {len(pattern.endpoints)}
   📋 Endpoints:"""
                        
                        for j, (path, method) in enumerate(pattern.endpoints[:5], 1):
                            result += f"\n      {j}. {method.value} {path}"
                        
                        if len(pattern.endpoints) > 5:
                            result += f"\n      ... and {len(pattern.endpoints) - 5} more steps"
                        
                        if pattern.variables_to_extract:
                            result += f"\n   📊 Data Extraction: {len(pattern.variables_to_extract)} variables"
                        
                        if pattern.dependencies:
                            result += f"\n   🔗 Dependencies: {len(pattern.dependencies)} step dependencies"

                result += f"""

📈 Testing Strategy:
• Authentication flows will be tested first to establish session context
• CRUD operations will test create → read → update → delete sequences
• Response chaining will extract IDs, tokens, and other data between requests
• Each scenario includes intelligent test data generation

✅ Ready to Generate:
Use 'generate_tests_from_openapi' to create executable K6 test configurations from these scenarios."""

                return {
                    "content": [
                        {"type": "text", "text": result}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error previewing OpenAPI tests: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error previewing tests: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "select_openapi_endpoints":
            spec_id = arguments.get("spec_id")
            spec_content = arguments.get("spec_content")
            endpoints = arguments.get("endpoints", [])
            filter_criteria = arguments.get("filter_criteria", {})
            preview_only = arguments.get("preview_only", True)
            
            if not spec_id and not spec_content:
                return {
                    "content": [
                        {"type": "text", "text": "Error: Either 'spec_id' or 'spec_content' is required"}
                    ],
                    "isError": True
                }
            
            try:
                # Get or load analysis
                if spec_id and spec_id in openapi_analysis_cache:
                    analysis = openapi_analysis_cache[spec_id]
                else:
                    # Load and analyze
                    if spec_content:
                        import yaml
                        try:
                            spec_dict = yaml.safe_load(spec_content)
                        except yaml.YAMLError:
                            spec_dict = safe_json_parse(spec_content)
                        spec = await openapi_processor.load_openapi_spec(spec_dict)
                        analysis = openapi_processor.analyze_api(spec)
                    else:
                        return {
                            "content": [
                                {"type": "text", "text": f"Error: spec_id '{spec_id}' not found. Please import the specification first."}
                            ],
                            "isError": True
                        }
                
                # Build test generation options from the selection criteria
                from openapi_models import EndpointSelector, HttpMethod
                
                selected_endpoints = []
                if endpoints:
                    for ep in endpoints:
                        selector = EndpointSelector(
                            path=ep["path"],
                            method=HttpMethod(ep["method"]),
                            include=ep.get("include", True),
                            priority=ep.get("priority", 1),
                            custom_name=ep.get("custom_name")
                        )
                        selected_endpoints.append(selector)
                
                options = TestGenerationOptions(
                    virtual_users=1,
                    duration="30s",
                    selected_endpoints=selected_endpoints if selected_endpoints else None,
                    endpoint_filter=filter_criteria if filter_criteria else None,
                    include_methods=[HttpMethod(m) for m in filter_criteria.get("include_methods", [])] if filter_criteria.get("include_methods") else None,
                    exclude_methods=[HttpMethod(m) for m in filter_criteria.get("exclude_methods", [])] if filter_criteria.get("exclude_methods") else None,
                    include_tags=filter_criteria.get("include_tags"),
                    exclude_tags=filter_criteria.get("exclude_tags")
                )
                
                if preview_only:
                    # Preview the selection
                    preview = openapi_processor.preview_selected_endpoints(analysis, options)
                    
                    result = f"""🎯 OpenAPI Endpoint Selection Preview
                    
📋 API: {analysis.spec.info.title} v{analysis.spec.info.version}
📊 Total Available Endpoints: {preview['total_endpoints_available']}
✅ Selected Endpoints: {preview['selected_endpoints_count']}

🔍 Selection Criteria Applied:"""
                    
                    if selected_endpoints:
                        result += f"\n• Specific Endpoints: {len(selected_endpoints)} explicitly selected"
                    
                    if filter_criteria:
                        for criteria, value in filter_criteria.items():
                            if value:
                                result += f"\n• {criteria.replace('_', ' ').title()}: {value}"
                    
                    result += f"\n\n📋 Selected Endpoints:"
                    
                    if not preview['selected_endpoints']:
                        result += "\n   No endpoints match the selection criteria."
                    else:
                        for resource, endpoints in preview['endpoints_by_resource'].items():
                            result += f"\n\n📁 {resource.title()}:"
                            for ep in endpoints[:10]:  # Show up to 10 endpoints per resource
                                auth_icon = "🔒" if ep['requires_auth'] else "🔓"
                                crud_icon = "📝" if ep['is_crud_operation'] else "🔗"
                                priority_text = ""
                                if ep.get('priority'):
                                    priority_map = {1: "🔥 High", 2: "📅 Medium", 3: "📋 Low"}
                                    priority_text = f" [{priority_map.get(ep['priority'], '❓')}]"
                                
                                custom_name = f" → '{ep['custom_name']}'" if ep.get('custom_name') else ""
                                
                                result += f"\n   {auth_icon}{crud_icon} {ep['method']} {ep['path']}{custom_name}{priority_text}"
                                if ep['summary']:
                                    result += f"\n      📝 {ep['summary']}"
                            
                            if len(endpoints) > 10:
                                result += f"\n   ... and {len(endpoints) - 10} more endpoints"
                    
                    # Test generation analysis
                    analysis_data = preview['test_generation_analysis']
                    result += f"""

🧪 Test Generation Analysis:
• Single Endpoint Tests: {analysis_data['single_endpoint_tests']} tests would be created
• CRUD Workflows: {analysis_data['possible_crud_workflows']} complete workflows available
• Authentication Required: {analysis_data['auth_endpoints']} endpoints need auth
• Endpoints with Examples: {analysis_data['endpoints_with_examples']} have OpenAPI examples

🚀 Next Steps:
• Use 'generate_tests_from_openapi' with the same selection criteria to create tests
• Use 'select_openapi_endpoints' with preview_only=false to generate tests directly
• Adjust filter_criteria to refine your endpoint selection"""
                    
                    return {
                        "content": [
                            {"type": "text", "text": result}
                        ]
                    }
                
                else:
                    # Generate tests for selected endpoints
                    test_configs = openapi_processor.generate_selective_tests(analysis, options)
                    preview = openapi_processor.preview_selected_endpoints(analysis, options)
                    
                    if not test_configs:
                        return {
                            "content": [
                                {"type": "text", "text": "No tests could be generated for the selected endpoints. Try adjusting your selection criteria."}
                            ],
                            "isError": True
                        }
                    
                    result = f"""✅ Generated {len(test_configs)} Test Configurations for Selected Endpoints

📋 API: {analysis.spec.info.title} v{analysis.spec.info.version}
📊 Selected {preview['selected_endpoints_count']} of {preview['total_endpoints_available']} endpoints

🧪 Generated Tests:"""
                    
                    for i, config in enumerate(test_configs, 1):
                        result += f"""

{i}. {config.workflow_name}
   📝 Description: {config.description}
   👥 Virtual Users: {config.virtual_users}
   ⏰ Duration: {config.duration}
   🔗 Steps: {len(config.steps)}"""
                        
                        for j, step in enumerate(config.steps[:3], 1):
                            result += f"\n      {j}. {step.method} {step.url} - {step.name}"
                        
                        if len(config.steps) > 3:
                            result += f"\n      ... and {len(config.steps) - 3} more steps"
                    
                    # Store configs for later use
                    for config in test_configs:
                        test_config_id = generate_request_id()
                        workflow_cache[test_config_id] = config
                        result += f"\n\n💾 Test '{config.workflow_name}' saved with ID: {test_config_id}"
                    
                    result += f"""

🚀 Ready to Execute:
• Use 'run_k6_workflow_test' with the generated test IDs
• Use 'get_test_results' after execution to see detailed reports
• Each test includes intelligent data generation and response chaining"""
                    
                    return {
                        "content": [
                            {"type": "text", "text": result}
                        ]
                    }
                    
            except Exception as e:
                logger.error(f"Error selecting OpenAPI endpoints: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error selecting endpoints: {str(e)}"}
                    ],
                    "isError": True
                }
        
        elif name == "analyze_url_performance":
            test_id = arguments.get("test_id")
            top_n = arguments.get("top_n", 0)
            group_by_domain = arguments.get("group_by_domain", False)
            output_format = arguments.get("output_format", "table")
            
            try:
                # Import analysis functions
                import csv
                from pathlib import Path
                from urllib.parse import urlparse
                from collections import defaultdict
                import json
                
                def clean_url(url):
                    """Czyści URL z parametrów query dla lepszego grupowania."""
                    if '?' in url:
                        return url.split('?')[0]
                    return url
                
                def get_domain(url):
                    """Wyciąga domenę z URL."""
                    try:
                        return urlparse(url).netloc
                    except:
                        return url
                
                def calculate_percentiles(values):
                    """Oblicza percentyle dla listy wartości."""
                    if not values:
                        return {}
                    
                    values_sorted = sorted(values)
                    n = len(values_sorted)
                    
                    def percentile(values, p):
                        k = (n - 1) * p / 100
                        f = int(k)
                        c = k - f
                        if f == n - 1:
                            return values[f]
                        return values[f] * (1 - c) + values[f + 1] * c
                    
                    return {
                        'min': min(values),
                        'max': max(values),
                        'avg': sum(values) / len(values),
                        'p50': percentile(values_sorted, 50),
                        'p90': percentile(values_sorted, 90),
                        'p95': percentile(values_sorted, 95),
                        'p99': percentile(values_sorted, 99),
                        'count': len(values)
                    }
                
                def find_csv_file(test_id=None):
                    """Znajduje plik CSV z metrykami."""
                    # Użyj tej samej ścieżki co K6Runner i WorkflowManager
                    reports_dir = Path(__file__).parent.parent / "reports"
                    csv_dir = reports_dir / "csv"
                    if not csv_dir.exists():
                        return None
                    
                    if test_id:
                        # Szukaj konkretnego test_id
                        csv_files = list(csv_dir.glob(f"*{test_id}*_metrics.csv"))
                        if not csv_files:
                            csv_files = list(csv_dir.glob(f"*{test_id}*_workflow_metrics.csv"))
                    else:
                        # Znajdź najnowszy plik
                        csv_files = list(csv_dir.glob("*_workflow_metrics.csv"))
                        if not csv_files:
                            csv_files = list(csv_dir.glob("*_metrics.csv"))
                    
                    if csv_files:
                        return max(csv_files, key=lambda f: f.stat().st_mtime)
                    return None
                
                def analyze_url_metrics(csv_file):
                    """Analizuje metryki URL z pliku CSV."""
                    url_metrics = defaultdict(lambda: defaultdict(list))
                    
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        
                        for row in reader:
                            if row.get('metric_name') == 'http_req_duration':
                                url = row.get('url', 'unknown')
                                method = row.get('method', 'unknown')
                                
                                try:
                                    duration = float(row.get('metric_value', 0))
                                except ValueError:
                                    continue
                                
                                # Opcjonalnie grupuj po domenie
                                if group_by_domain:
                                    url = get_domain(url)
                                else:
                                    url = clean_url(url)
                                
                                url_metrics[url][method].append(duration)
                    
                    # Oblicz statystyki
                    results = {}
                    for url, methods in url_metrics.items():
                        results[url] = {}
                        total_durations = []
                        
                        for method, durations in methods.items():
                            if durations:
                                results[url][method] = calculate_percentiles(durations)
                                total_durations.extend(durations)
                        
                        # Statystyki dla całego URL
                        if total_durations:
                            results[url]['_total'] = calculate_percentiles(total_durations)
                    
                    return results
                
                def format_duration(ms):
                    """Formatuje czas w ms do czytelnej postaci."""
                    if ms < 1000:
                        return f"{ms:.1f}ms"
                    else:
                        return f"{ms/1000:.2f}s"
                
                # Znajdź plik CSV
                csv_file = find_csv_file(test_id)
                if not csv_file:
                    # Debug info
                    reports_dir = Path(__file__).parent.parent / "reports"
                    csv_dir = reports_dir / "csv"
                    debug_info = f"""
Debug Info:
• Reports dir: {reports_dir} (exists: {reports_dir.exists()})
• CSV dir: {csv_dir} (exists: {csv_dir.exists()})
• Working directory: {Path.cwd()}
• Script location: {Path(__file__).parent}"""
                    
                    if csv_dir.exists():
                        csv_files = list(csv_dir.glob("*.csv"))
                        debug_info += f"\n• CSV files found: {len(csv_files)}"
                        if csv_files:
                            debug_info += f"\n• Latest file: {max(csv_files, key=lambda f: f.stat().st_mtime)}"
                    
                    if test_id:
                        error_msg = f"No CSV metrics file found for test ID: {test_id}\n{debug_info}"
                    else:
                        error_msg = f"No CSV metrics files found. Run a K6 test first to generate data.\n{debug_info}"
                    
                    return {
                        "content": [
                            {"type": "text", "text": f"❌ {error_msg}"}
                        ],
                        "isError": True
                    }
                
                # Analizuj dane
                results = analyze_url_metrics(csv_file)
                
                if not results:
                    return {
                        "content": [
                            {"type": "text", "text": "❌ No http_req_duration data found in CSV file"}
                        ],
                        "isError": True
                    }
                
                # Format wyników
                if output_format == "json":
                    result_text = json.dumps(results, indent=2, ensure_ascii=False)
                else:
                    # Format tabeli
                    sorted_urls = sorted(
                        results.items(), 
                        key=lambda x: x[1].get('_total', {}).get('avg', 0), 
                        reverse=True
                    )
                    
                    if top_n > 0:
                        sorted_urls = sorted_urls[:top_n]
                    
                    total_requests = sum(
                        url_data.get('_total', {}).get('count', 0) 
                        for _, url_data in results.items()
                    )
                    
                    result_text = "🔍 **K6 URL Performance Analysis**\n"
                    result_text += "=" * 80 + "\n"
                    result_text += f"📊 **Podsumowanie:** {len(results)} unikalne URL, {total_requests} requestów\n"
                    result_text += f"📁 **Dane z:** {csv_file.name}\n\n"
                    
                    for url, methods in sorted_urls:
                        total_stats = methods.get('_total', {})
                        if not total_stats:
                            continue
                            
                        result_text += f"🌐 **{url}**\n"
                        result_text += f"   📈 Ogółem: {total_stats['count']} req | "
                        result_text += f"Avg: {format_duration(total_stats['avg'])} | "
                        result_text += f"P95: {format_duration(total_stats['p95'])} | "
                        result_text += f"Max: {format_duration(total_stats['max'])}\n"
                        
                        # Pokaż statystyki per metoda HTTP
                        for method, stats in methods.items():
                            if method == '_total':
                                continue
                                
                            result_text += f"   ├─ {method:6}: {stats['count']:3} req | "
                            result_text += f"Min: {format_duration(stats['min']):8} | "
                            result_text += f"Avg: {format_duration(stats['avg']):8} | "
                            result_text += f"P95: {format_duration(stats['p95']):8} | "
                            result_text += f"Max: {format_duration(stats['max'])}\n"
                        
                        result_text += "\n"
                
                return {
                    "content": [
                        {"type": "text", "text": result_text}
                    ]
                }
                
            except Exception as e:
                logger.error(f"Error analyzing URL performance: {str(e)}")
                return {
                    "content": [
                        {"type": "text", "text": f"Error analyzing URL performance: {str(e)}"}
                    ],
                    "isError": True
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