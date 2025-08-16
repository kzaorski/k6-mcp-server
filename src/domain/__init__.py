"""
Domain layer for K6 MCP Server.

Contains domain models, entities, and business rules that represent
the core concepts of the K6 testing system.
"""

from .models import (
    K6TestConfig,
    K6TestResult,
    WorkflowConfig,
    WorkflowResult,
    TestStatus,
    LoadPattern,
    HttpMethod
)

__all__ = [
    'K6TestConfig',
    'K6TestResult', 
    'WorkflowConfig',
    'WorkflowResult',
    'TestStatus',
    'LoadPattern',
    'HttpMethod'
]