"""
Unit tests for configuration management.
"""

import os
import pytest
import tempfile
from pathlib import Path

from core.config import (
    AppConfig, ServerConfig, SecurityConfig, K6Config, 
    LoggingConfig, DatabaseConfig, Environment, LogLevel
)


class TestServerConfig:
    """Test ServerConfig validation and functionality."""
    
    def test_valid_config(self):
        """Test valid server configuration."""
        config = ServerConfig(
            host="localhost",
            port=8080,
            max_connections=100,
            request_timeout=30
        )
        
        assert config.host == "localhost"
        assert config.port == 8080
        assert config.max_connections == 100
        assert config.request_timeout == 30
    
    def test_invalid_port_raises_error(self):
        """Test that invalid port raises ValueError."""
        with pytest.raises(ValueError, match="Invalid port number"):
            ServerConfig(port=0)
        
        with pytest.raises(ValueError, match="Invalid port number"):
            ServerConfig(port=70000)
    
    def test_invalid_max_connections_raises_error(self):
        """Test that invalid max_connections raises ValueError."""
        with pytest.raises(ValueError, match="Invalid max_connections"):
            ServerConfig(max_connections=0)


class TestSecurityConfig:
    """Test SecurityConfig validation and functionality."""
    
    def test_default_config(self):
        """Test default security configuration."""
        config = SecurityConfig()
        
        assert config.audit_log_enabled is True
        assert config.rate_limit_enabled is True
        assert config.rate_limit_max_requests == 100
        assert config.rate_limit_window_seconds == 60
        assert config.max_payload_size == 10 * 1024 * 1024
        assert "localhost" in config.allowed_hosts
    
    def test_validate_configuration_returns_warnings(self):
        """Test configuration validation warnings."""
        config = SecurityConfig(
            audit_log_enabled=False,
            rate_limit_enabled=False,
            rate_limit_max_requests=2000,
            max_payload_size=100 * 1024 * 1024
        )
        
        warnings = config.validate_configuration()
        
        assert len(warnings) == 4
        assert any("Audit logging is disabled" in w for w in warnings)
        assert any("Rate limiting is disabled" in w for w in warnings)
        assert any("High rate limit" in w for w in warnings)
        assert any("Large max payload size" in w for w in warnings)


class TestK6Config:
    """Test K6Config validation and functionality."""
    
    def test_valid_config(self):
        """Test valid K6 configuration."""
        config = K6Config(
            k6_binary_path="k6",
            default_timeout="30s",
            max_virtual_users=1000,
            max_duration="24h",
            results_retention_days=30
        )
        
        assert config.k6_binary_path == "k6"
        assert config.default_timeout == "30s"
        assert config.max_virtual_users == 1000
        assert config.max_duration == "24h"
        assert config.results_retention_days == 30
    
    def test_invalid_max_virtual_users_raises_error(self):
        """Test that invalid max_virtual_users raises ValueError."""
        with pytest.raises(ValueError, match="Invalid max_virtual_users"):
            K6Config(max_virtual_users=0)


class TestAppConfig:
    """Test AppConfig functionality."""
    
    def test_default_config(self):
        """Test default application configuration."""
        config = AppConfig()
        
        assert config.environment == Environment.DEVELOPMENT
        assert config.debug is False
        assert isinstance(config.server, ServerConfig)
        assert isinstance(config.security, SecurityConfig)
        assert isinstance(config.k6, K6Config)
        assert isinstance(config.logging, LoggingConfig)
        assert isinstance(config.database, DatabaseConfig)
    
    def test_from_environment_variables(self):
        """Test configuration from environment variables."""
        # Set environment variables
        env_vars = {
            "K6_MCP_ENVIRONMENT": "production",
            "K6_MCP_DEBUG": "true",
            "K6_MCP_HOST": "0.0.0.0",
            "K6_MCP_PORT": "9090",
            "K6_MCP_MAX_CONNECTIONS": "500",
            "K6_MCP_AUDIT_LOG": "false",
            "K6_MCP_RATE_LIMIT": "false",
            "K6_MCP_K6_BINARY": "/usr/local/bin/k6",
            "K6_MCP_MAX_VUS": "5000",
            "K6_MCP_LOG_LEVEL": "ERROR",
            "K6_MCP_STRUCTURED_LOGGING": "true"
        }
        
        # Mock environment
        original_env = {}
        for key, value in env_vars.items():
            original_env[key] = os.environ.get(key)
            os.environ[key] = value
        
        try:
            config = AppConfig.from_environment("K6_MCP")
            
            assert config.environment == Environment.PRODUCTION
            assert config.debug is True
            assert config.server.host == "0.0.0.0"
            assert config.server.port == 9090
            assert config.server.max_connections == 500
            assert config.security.audit_log_enabled is False
            assert config.security.rate_limit_enabled is False
            assert config.k6.k6_binary_path == "/usr/local/bin/k6"
            assert config.k6.max_virtual_users == 5000
            assert config.logging.level == LogLevel.ERROR
            assert config.logging.enable_structured_logging is True
            
        finally:
            # Restore original environment
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    
    def test_from_file_json(self):
        """Test configuration from JSON file."""
        config_data = {
            "environment": "testing",
            "debug": True,
            "server": {
                "host": "test.example.com",
                "port": 3333,
                "max_connections": 25
            },
            "k6": {
                "max_virtual_users": 50,
                "results_retention_days": 7
            },
            "logging": {
                "level": "DEBUG",
                "enable_structured_logging": True
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            import json
            json.dump(config_data, f)
            config_file = Path(f.name)
        
        try:
            config = AppConfig.from_file(config_file)
            
            assert config.environment == Environment.TESTING
            assert config.debug is True
            assert config.server.host == "test.example.com"
            assert config.server.port == 3333
            assert config.server.max_connections == 25
            assert config.k6.max_virtual_users == 50
            assert config.k6.results_retention_days == 7
            assert config.logging.level == LogLevel.DEBUG
            assert config.logging.enable_structured_logging is True
            
        finally:
            config_file.unlink()
    
    def test_from_dict(self):
        """Test configuration from dictionary."""
        config_data = {
            "environment": "production",
            "debug": False,
            "server": {
                "host": "prod.example.com",
                "port": 8443,
                "max_connections": 1000,
                "request_timeout": 60
            },
            "security": {
                "audit_log_enabled": True,
                "rate_limit_enabled": True,
                "rate_limit_max_requests": 50,
                "max_payload_size": 5242880,
                "allowed_hosts": ["prod.example.com", "api.example.com"]
            }
        }
        
        config = AppConfig.from_dict(config_data)
        
        assert config.environment == Environment.PRODUCTION
        assert config.debug is False
        assert config.server.host == "prod.example.com"
        assert config.server.port == 8443
        assert config.server.max_connections == 1000
        assert config.server.request_timeout == 60
        assert config.security.audit_log_enabled is True
        assert config.security.rate_limit_max_requests == 50
        assert config.security.max_payload_size == 5242880
        assert "prod.example.com" in config.security.allowed_hosts
    
    def test_validate_returns_warnings(self):
        """Test configuration validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AppConfig(
                environment=Environment.PRODUCTION,
                debug=True,  # Debug in production
                base_dir=Path(temp_dir),
                templates_dir=Path(temp_dir) / "nonexistent",  # Non-existent dir
                reports_dir=Path(temp_dir) / "reports",
                csv_data_dir=Path(temp_dir) / "csv_data"
            )
            config.logging.level = LogLevel.DEBUG  # Debug logging in production
            
            warnings = config.validate()
            
            assert len(warnings) >= 2
            assert any("Debug mode enabled in production" in w for w in warnings)
            assert any("Debug logging enabled in production" in w for w in warnings)
            assert any("Templates directory does not exist" in w for w in warnings)
            
            # Check that directories were created
            assert config.reports_dir.exists()
            assert config.csv_data_dir.exists()
    
    def test_to_dict(self):
        """Test configuration serialization to dictionary."""
        config = AppConfig()
        config_dict = config.to_dict()
        
        assert isinstance(config_dict, dict)
        assert "environment" in config_dict
        assert "server" in config_dict
        assert "security" in config_dict
        assert "k6" in config_dict
        assert "logging" in config_dict
        assert "database" in config_dict
        
        # Check nested structures
        assert isinstance(config_dict["server"], dict)
        assert "host" in config_dict["server"]
        assert "port" in config_dict["server"]
        
        assert isinstance(config_dict["k6"], dict)
        assert "k6_binary_path" in config_dict["k6"]
        assert "max_virtual_users" in config_dict["k6"]