"""
Security configuration for K6 MCP Server.

This module contains security settings and configurations for the server.
"""

import os
from typing import Dict, List, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class SecurityConfig:
    """Central security configuration for K6 MCP Server."""
    
    # Rate limiting settings
    RATE_LIMIT_ENABLED = os.getenv('K6_MCP_RATE_LIMIT_ENABLED', 'true').lower() == 'true'
    RATE_LIMIT_MAX_REQUESTS = int(os.getenv('K6_MCP_RATE_LIMIT_MAX_REQUESTS', '100'))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('K6_MCP_RATE_LIMIT_WINDOW', '60'))
    
    # Authentication settings (for future implementation)
    AUTH_ENABLED = os.getenv('K6_MCP_AUTH_ENABLED', 'false').lower() == 'true'
    AUTH_TOKEN = os.getenv('K6_MCP_AUTH_TOKEN', '')
    
    # Resource limits
    MAX_CONCURRENT_TESTS = int(os.getenv('K6_MCP_MAX_CONCURRENT_TESTS', '5'))
    MAX_TEST_DURATION_SECONDS = int(os.getenv('K6_MCP_MAX_TEST_DURATION', '3600'))
    MAX_MEMORY_MB = int(os.getenv('K6_MCP_MAX_MEMORY_MB', '2048'))
    MAX_CPU_SECONDS = int(os.getenv('K6_MCP_MAX_CPU_SECONDS', '1800'))
    
    # File size limits
    MAX_JSON_SIZE = int(os.getenv('K6_MCP_MAX_JSON_SIZE', '10000000'))  # 10MB
    MAX_CSV_SIZE = int(os.getenv('K6_MCP_MAX_CSV_SIZE', '50000000'))  # 50MB
    MAX_HAR_SIZE = int(os.getenv('K6_MCP_MAX_HAR_SIZE', '100000000'))  # 100MB
    MAX_PAYLOAD_SIZE = int(os.getenv('K6_MCP_MAX_PAYLOAD_SIZE', '1000000'))  # 1MB
    
    # Path restrictions
    ALLOWED_BASE_DIRS = {
        'reports': Path(__file__).parent.parent / 'reports',
        'csv_data': Path(__file__).parent.parent / 'csv_data',
        'templates': Path(__file__).parent / 'templates'
    }
    
    # URL restrictions
    ALLOWED_URL_SCHEMES = ['http', 'https']
    BLOCKED_DOMAINS = os.getenv('K6_MCP_BLOCKED_DOMAINS', '').split(',') if os.getenv('K6_MCP_BLOCKED_DOMAINS') else []
    
    # Sensitive data patterns
    SENSITIVE_KEYS = [
        'password', 'passwd', 'pwd', 'secret', 'token', 'api_key', 'apikey',
        'auth', 'authorization', 'credential', 'private', 'session', 'cookie'
    ]
    
    # Logging settings
    LOG_SENSITIVE_DATA = os.getenv('K6_MCP_LOG_SENSITIVE_DATA', 'false').lower() == 'true'
    AUDIT_LOG_ENABLED = os.getenv('K6_MCP_AUDIT_LOG_ENABLED', 'true').lower() == 'true'
    
    # Test execution settings
    ALLOW_EXTERNAL_CSV = os.getenv('K6_MCP_ALLOW_EXTERNAL_CSV', 'false').lower() == 'true'
    REQUIRE_TEST_CONFIRMATION = os.getenv('K6_MCP_REQUIRE_CONFIRMATION', 'true').lower() == 'true'
    
    # Security headers (for future HTTP interface)
    SECURITY_HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'X-XSS-Protection': '1; mode=block',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self'"
    }
    
    @classmethod
    def validate_configuration(cls) -> List[str]:
        """Validate security configuration and return any warnings."""
        warnings = []
        
        # Check if authentication is properly configured
        if cls.AUTH_ENABLED and not cls.AUTH_TOKEN:
            warnings.append("Authentication is enabled but no token is configured")
        
        # Check rate limiting
        if not cls.RATE_LIMIT_ENABLED:
            warnings.append("Rate limiting is disabled - this may allow abuse")
        
        # Check resource limits
        if cls.MAX_CONCURRENT_TESTS > 10:
            warnings.append(f"High concurrent test limit ({cls.MAX_CONCURRENT_TESTS}) may cause resource exhaustion")
        
        # Check file size limits
        if cls.MAX_JSON_SIZE > 100_000_000:  # 100MB
            warnings.append(f"Very large JSON size limit ({cls.MAX_JSON_SIZE} bytes) may cause memory issues")
        
        # Check audit logging
        if not cls.AUDIT_LOG_ENABLED:
            warnings.append("Audit logging is disabled - security events won't be tracked")
        
        # Ensure required directories exist
        for name, path in cls.ALLOWED_BASE_DIRS.items():
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created required directory: {path}")
                except Exception as e:
                    warnings.append(f"Could not create required directory {name}: {e}")
        
        return warnings
    
    @classmethod
    def get_safe_config_display(cls) -> Dict[str, any]:
        """Get configuration for display (with sensitive values masked)."""
        return {
            'rate_limiting': {
                'enabled': cls.RATE_LIMIT_ENABLED,
                'max_requests': cls.RATE_LIMIT_MAX_REQUESTS,
                'window_seconds': cls.RATE_LIMIT_WINDOW_SECONDS
            },
            'authentication': {
                'enabled': cls.AUTH_ENABLED,
                'token_configured': bool(cls.AUTH_TOKEN)
            },
            'resource_limits': {
                'max_concurrent_tests': cls.MAX_CONCURRENT_TESTS,
                'max_test_duration': cls.MAX_TEST_DURATION_SECONDS,
                'max_memory_mb': cls.MAX_MEMORY_MB,
                'max_cpu_seconds': cls.MAX_CPU_SECONDS
            },
            'file_limits': {
                'max_json_size': cls.MAX_JSON_SIZE,
                'max_csv_size': cls.MAX_CSV_SIZE,
                'max_har_size': cls.MAX_HAR_SIZE,
                'max_payload_size': cls.MAX_PAYLOAD_SIZE
            },
            'security': {
                'audit_logging': cls.AUDIT_LOG_ENABLED,
                'external_csv_allowed': cls.ALLOW_EXTERNAL_CSV,
                'test_confirmation_required': cls.REQUIRE_TEST_CONFIRMATION
            }
        }


class AuditLogger:
    """Audit logger for security events."""
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.logger = logging.getLogger('k6-mcp-audit')
        
        if self.enabled:
            # Set up dedicated audit log handler
            handler = logging.FileHandler('k6_mcp_audit.log')
            handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def log_test_execution(self, test_id: str, config: Dict, user_id: Optional[str] = None):
        """Log test execution event."""
        if not self.enabled:
            return
        
        self.logger.info(
            f"TEST_EXECUTION: test_id={test_id}, user={user_id or 'anonymous'}, "
            f"url={config.get('url', 'N/A')}, method={config.get('method', 'N/A')}"
        )
    
    def log_security_event(self, event_type: str, details: str, severity: str = 'INFO'):
        """Log security event."""
        if not self.enabled:
            return
        
        self.logger.log(
            getattr(logging, severity),
            f"SECURITY_EVENT: type={event_type}, details={details}"
        )
    
    def log_authentication_attempt(self, success: bool, user_id: Optional[str] = None):
        """Log authentication attempt."""
        if not self.enabled:
            return
        
        status = 'SUCCESS' if success else 'FAILURE'
        self.logger.info(
            f"AUTH_ATTEMPT: status={status}, user={user_id or 'unknown'}"
        )
    
    def log_rate_limit_exceeded(self, identifier: str):
        """Log rate limit exceeded event."""
        if not self.enabled:
            return
        
        self.logger.warning(
            f"RATE_LIMIT_EXCEEDED: identifier={identifier}"
        )
    
    def log_file_upload(self, filename: str, size: int, file_type: str):
        """Log file upload event."""
        if not self.enabled:
            return
        
        self.logger.info(
            f"FILE_UPLOAD: filename={filename}, size={size}, type={file_type}"
        )
    
    def log_error(self, error_type: str, error_message: str, test_id: Optional[str] = None):
        """Log error event."""
        if not self.enabled:
            return
        
        self.logger.error(
            f"ERROR: type={error_type}, test_id={test_id or 'N/A'}, message={error_message}"
        )