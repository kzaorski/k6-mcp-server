"""
Configuration management for K6 MCP Server.

Provides centralized configuration with environment variable support,
validation, and type safety.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class LogLevel(Enum):
    """Logging levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Environment(Enum):
    """Application environments."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


@dataclass
class ServerConfig:
    """Server configuration settings."""
    host: str = field(default="localhost")
    port: int = field(default=8080)
    max_connections: int = field(default=100)
    request_timeout: int = field(default=30)
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port number: {self.port}")
        if self.max_connections < 1:
            raise ValueError(f"Invalid max_connections: {self.max_connections}")


@dataclass 
class SecurityConfig:
    """Security configuration settings."""
    audit_log_enabled: bool = field(default=True)
    rate_limit_enabled: bool = field(default=True)
    rate_limit_max_requests: int = field(default=100)
    rate_limit_window_seconds: int = field(default=60)
    max_payload_size: int = field(default=10 * 1024 * 1024)  # 10MB
    allowed_hosts: List[str] = field(default_factory=lambda: ["localhost", "127.0.0.1"])
    
    def validate_configuration(self) -> List[str]:
        """Validate security configuration and return warnings."""
        warnings = []
        
        if not self.audit_log_enabled:
            warnings.append("Audit logging is disabled")
        
        if not self.rate_limit_enabled:
            warnings.append("Rate limiting is disabled")
        
        if self.rate_limit_max_requests > 1000:
            warnings.append(f"High rate limit: {self.rate_limit_max_requests}")
        
        if self.max_payload_size > 50 * 1024 * 1024:  # 50MB
            warnings.append(f"Large max payload size: {self.max_payload_size}")
        
        return warnings


@dataclass
class K6Config:
    """K6-specific configuration settings."""
    k6_binary_path: str = field(default="k6")
    default_timeout: str = field(default="30s")
    max_virtual_users: int = field(default=1000)
    max_duration: str = field(default="24h")
    results_retention_days: int = field(default=30)
    enable_html_reports: bool = field(default=True)
    enable_csv_export: bool = field(default=True)
    
    def __post_init__(self):
        """Validate K6 configuration."""
        if self.max_virtual_users < 1:
            raise ValueError(f"Invalid max_virtual_users: {self.max_virtual_users}")


@dataclass
class LoggingConfig:
    """Logging configuration settings."""
    level: LogLevel = field(default=LogLevel.INFO)
    format: str = field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    file_path: Optional[str] = field(default=None)
    max_file_size: int = field(default=10 * 1024 * 1024)  # 10MB
    backup_count: int = field(default=5)
    enable_structured_logging: bool = field(default=False)


@dataclass
class DatabaseConfig:
    """Database configuration settings."""
    url: Optional[str] = field(default=None)
    pool_size: int = field(default=5)
    max_overflow: int = field(default=10)
    pool_timeout: int = field(default=30)
    enable_query_logging: bool = field(default=False)


@dataclass
class AppConfig:
    """
    Main application configuration.
    
    Aggregates all configuration sections and provides environment-aware defaults.
    """
    environment: Environment = field(default=Environment.DEVELOPMENT)
    debug: bool = field(default=False)
    
    server: ServerConfig = field(default_factory=ServerConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    k6: K6Config = field(default_factory=K6Config)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    
    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)
    templates_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "templates")
    reports_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "reports")
    csv_data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "csv_data")
    
    @classmethod
    def from_environment(cls, env_prefix: str = "K6_MCP") -> 'AppConfig':
        """
        Create configuration from environment variables.
        
        Args:
            env_prefix: Prefix for environment variables (e.g., K6_MCP_DEBUG)
        """
        config = cls()
        
        # Environment
        env_name = os.getenv(f"{env_prefix}_ENVIRONMENT", "development").lower()
        try:
            config.environment = Environment(env_name)
        except ValueError:
            logger.warning(f"Invalid environment '{env_name}', defaulting to development")
            config.environment = Environment.DEVELOPMENT
        
        # Debug mode
        config.debug = os.getenv(f"{env_prefix}_DEBUG", "false").lower() in ("true", "1", "yes")
        
        # Server configuration
        config.server.host = os.getenv(f"{env_prefix}_HOST", config.server.host)
        config.server.port = int(os.getenv(f"{env_prefix}_PORT", str(config.server.port)))
        config.server.max_connections = int(os.getenv(f"{env_prefix}_MAX_CONNECTIONS", str(config.server.max_connections)))
        
        # Security configuration
        config.security.audit_log_enabled = os.getenv(f"{env_prefix}_AUDIT_LOG", "true").lower() in ("true", "1", "yes")
        config.security.rate_limit_enabled = os.getenv(f"{env_prefix}_RATE_LIMIT", "true").lower() in ("true", "1", "yes")
        config.security.rate_limit_max_requests = int(os.getenv(f"{env_prefix}_RATE_LIMIT_MAX", str(config.security.rate_limit_max_requests)))
        
        # K6 configuration
        config.k6.k6_binary_path = os.getenv(f"{env_prefix}_K6_BINARY", config.k6.k6_binary_path)
        config.k6.max_virtual_users = int(os.getenv(f"{env_prefix}_MAX_VUS", str(config.k6.max_virtual_users)))
        config.k6.results_retention_days = int(os.getenv(f"{env_prefix}_RETENTION_DAYS", str(config.k6.results_retention_days)))
        
        # Logging configuration
        log_level = os.getenv(f"{env_prefix}_LOG_LEVEL", config.logging.level.value).upper()
        try:
            config.logging.level = LogLevel(log_level)
        except ValueError:
            logger.warning(f"Invalid log level '{log_level}', defaulting to INFO")
            config.logging.level = LogLevel.INFO
        
        config.logging.file_path = os.getenv(f"{env_prefix}_LOG_FILE")
        config.logging.enable_structured_logging = os.getenv(f"{env_prefix}_STRUCTURED_LOGGING", "false").lower() in ("true", "1", "yes")
        
        # Database configuration  
        config.database.url = os.getenv(f"{env_prefix}_DATABASE_URL")
        
        # Paths
        if base_dir := os.getenv(f"{env_prefix}_BASE_DIR"):
            config.base_dir = Path(base_dir)
        if templates_dir := os.getenv(f"{env_prefix}_TEMPLATES_DIR"):
            config.templates_dir = Path(templates_dir)
        if reports_dir := os.getenv(f"{env_prefix}_REPORTS_DIR"):
            config.reports_dir = Path(reports_dir)
        
        return config
    
    @classmethod
    def from_file(cls, config_file: Path) -> 'AppConfig':
        """Load configuration from JSON or YAML file."""
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        import json
        try:
            with open(config_file, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            # Try YAML
            try:
                import yaml
                with open(config_file, 'r') as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                raise ValueError(f"Could not parse configuration file: {e}")
        
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AppConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        # Environment
        if 'environment' in data:
            config.environment = Environment(data['environment'])
        
        config.debug = data.get('debug', config.debug)
        
        # Server configuration
        if 'server' in data:
            server_data = data['server']
            config.server = ServerConfig(
                host=server_data.get('host', config.server.host),
                port=server_data.get('port', config.server.port),
                max_connections=server_data.get('max_connections', config.server.max_connections),
                request_timeout=server_data.get('request_timeout', config.server.request_timeout)
            )
        
        # Security configuration
        if 'security' in data:
            security_data = data['security']
            config.security = SecurityConfig(
                audit_log_enabled=security_data.get('audit_log_enabled', config.security.audit_log_enabled),
                rate_limit_enabled=security_data.get('rate_limit_enabled', config.security.rate_limit_enabled),
                rate_limit_max_requests=security_data.get('rate_limit_max_requests', config.security.rate_limit_max_requests),
                rate_limit_window_seconds=security_data.get('rate_limit_window_seconds', config.security.rate_limit_window_seconds),
                max_payload_size=security_data.get('max_payload_size', config.security.max_payload_size),
                allowed_hosts=security_data.get('allowed_hosts', config.security.allowed_hosts)
            )
        
        # K6 configuration
        if 'k6' in data:
            k6_data = data['k6']
            config.k6 = K6Config(
                k6_binary_path=k6_data.get('k6_binary_path', config.k6.k6_binary_path),
                default_timeout=k6_data.get('default_timeout', config.k6.default_timeout),
                max_virtual_users=k6_data.get('max_virtual_users', config.k6.max_virtual_users),
                max_duration=k6_data.get('max_duration', config.k6.max_duration),
                results_retention_days=k6_data.get('results_retention_days', config.k6.results_retention_days),
                enable_html_reports=k6_data.get('enable_html_reports', config.k6.enable_html_reports),
                enable_csv_export=k6_data.get('enable_csv_export', config.k6.enable_csv_export)
            )
        
        # Logging configuration
        if 'logging' in data:
            logging_data = data['logging']
            config.logging = LoggingConfig(
                level=LogLevel(logging_data.get('level', config.logging.level.value)),
                format=logging_data.get('format', config.logging.format),
                file_path=logging_data.get('file_path', config.logging.file_path),
                max_file_size=logging_data.get('max_file_size', config.logging.max_file_size),
                backup_count=logging_data.get('backup_count', config.logging.backup_count),
                enable_structured_logging=logging_data.get('enable_structured_logging', config.logging.enable_structured_logging)
            )
        
        # Database configuration
        if 'database' in data:
            db_data = data['database']
            config.database = DatabaseConfig(
                url=db_data.get('url', config.database.url),
                pool_size=db_data.get('pool_size', config.database.pool_size),
                max_overflow=db_data.get('max_overflow', config.database.max_overflow),
                pool_timeout=db_data.get('pool_timeout', config.database.pool_timeout),
                enable_query_logging=db_data.get('enable_query_logging', config.database.enable_query_logging)
            )
        
        return config
    
    def validate(self) -> List[str]:
        """
        Validate the entire configuration.
        
        Returns:
            List of validation warnings/errors
        """
        warnings = []
        
        # Validate security configuration
        security_warnings = self.security.validate_configuration()
        warnings.extend([f"Security: {w}" for w in security_warnings])
        
        # Environment-specific validations
        if self.environment == Environment.PRODUCTION:
            if self.debug:
                warnings.append("Debug mode enabled in production")
            if self.logging.level == LogLevel.DEBUG:
                warnings.append("Debug logging enabled in production")
        
        # Path validations
        if not self.templates_dir.exists():
            warnings.append(f"Templates directory does not exist: {self.templates_dir}")
        
        # Create directories if they don't exist
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.csv_data_dir.mkdir(parents=True, exist_ok=True)
        
        return warnings
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'environment': self.environment.value,
            'debug': self.debug,
            'server': {
                'host': self.server.host,
                'port': self.server.port,
                'max_connections': self.server.max_connections,
                'request_timeout': self.server.request_timeout
            },
            'security': {
                'audit_log_enabled': self.security.audit_log_enabled,
                'rate_limit_enabled': self.security.rate_limit_enabled,
                'rate_limit_max_requests': self.security.rate_limit_max_requests,
                'rate_limit_window_seconds': self.security.rate_limit_window_seconds,
                'max_payload_size': self.security.max_payload_size,
                'allowed_hosts': self.security.allowed_hosts
            },
            'k6': {
                'k6_binary_path': self.k6.k6_binary_path,
                'default_timeout': self.k6.default_timeout,
                'max_virtual_users': self.k6.max_virtual_users,
                'max_duration': self.k6.max_duration,
                'results_retention_days': self.k6.results_retention_days,
                'enable_html_reports': self.k6.enable_html_reports,
                'enable_csv_export': self.k6.enable_csv_export
            },
            'logging': {
                'level': self.logging.level.value,
                'format': self.logging.format,
                'file_path': self.logging.file_path,
                'max_file_size': self.logging.max_file_size,
                'backup_count': self.logging.backup_count,
                'enable_structured_logging': self.logging.enable_structured_logging
            },
            'database': {
                'url': self.database.url,
                'pool_size': self.database.pool_size,
                'max_overflow': self.database.max_overflow,
                'pool_timeout': self.database.pool_timeout,
                'enable_query_logging': self.database.enable_query_logging
            }
        }