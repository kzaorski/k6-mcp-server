"""
Security Manager for K6 MCP Server.

This module provides comprehensive security features including OAuth2/OIDC authentication,
Role-Based Access Control (RBAC), audit logging, and advanced security policies.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import jwt
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import secrets
import aiohttp

from error_handler import (
    ErrorHandler, ErrorContext, ErrorCategory, ErrorSeverity,
    EnhancedError, with_error_handling
)

logger = logging.getLogger(__name__)


class AuthenticationMethod(Enum):
    """Supported authentication methods."""
    BEARER_TOKEN = "bearer"
    OAUTH2_AUTHORIZATION_CODE = "oauth2_auth_code"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
    OIDC = "oidc"
    API_KEY = "api_key"
    BASIC_AUTH = "basic"


class Permission(Enum):
    """System permissions for RBAC."""
    # Test execution permissions
    RUN_TESTS = "run_tests"
    RUN_WORKFLOWS = "run_workflows"
    VIEW_RESULTS = "view_results"
    DELETE_RESULTS = "delete_results"
    
    # Configuration permissions
    MANAGE_TEMPLATES = "manage_templates"
    MANAGE_CONFIG = "manage_config"
    UPLOAD_DATA = "upload_data"
    
    # Administrative permissions
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_SYSTEM = "manage_system"
    
    # Advanced features
    ACCESS_PLUGINS = "access_plugins"
    MANAGE_INTEGRATIONS = "manage_integrations"


class AuditEventType(Enum):
    """Types of audit events."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    TEST_EXECUTION = "test_execution"
    CONFIGURATION_CHANGE = "configuration_change"
    DATA_ACCESS = "data_access"
    SECURITY_VIOLATION = "security_violation"
    SYSTEM_EVENT = "system_event"


@dataclass
class Role:
    """Role definition with permissions."""
    name: str
    description: str
    permissions: Set[Permission] = field(default_factory=set)
    is_system_role: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class User:
    """User account with roles and metadata."""
    user_id: str
    username: str
    email: Optional[str] = None
    roles: Set[str] = field(default_factory=set)
    is_active: bool = True
    is_service_account: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEvent:
    """Audit log event."""
    event_id: str
    timestamp: datetime
    event_type: AuditEventType
    user_id: Optional[str]
    action: str
    resource: Optional[str]
    result: str  # success, failure, denied
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


@dataclass
class SecurityPolicy:
    """Security policy configuration."""
    max_failed_login_attempts: int = 5
    account_lockout_duration: timedelta = timedelta(minutes=30)
    session_timeout: timedelta = timedelta(hours=8)
    token_expiry: timedelta = timedelta(hours=1)
    require_mfa: bool = False
    allowed_ip_ranges: List[str] = field(default_factory=list)
    blocked_ip_ranges: List[str] = field(default_factory=list)
    min_password_length: int = 12
    password_complexity_required: bool = True


class SecurityViolationError(EnhancedError):
    """Security violation error."""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            **kwargs
        )


class SecurityManager:
    """
    Comprehensive security manager with authentication, authorization, and auditing.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.error_handler = ErrorHandler()
        
        # Security components
        self.security_policy = SecurityPolicy()
        self.roles: Dict[str, Role] = {}
        self.users: Dict[str, User] = {}
        self.audit_events: List[AuditEvent] = []
        
        # Authentication state
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.failed_login_attempts: Dict[str, int] = {}
        self.locked_accounts: Dict[str, datetime] = {}
        
        # OAuth2/OIDC configuration
        self.oauth_config = self.config.get('oauth', {})
        self.oidc_config = self.config.get('oidc', {})
        
        # Initialize default roles and system user
        self._initialize_default_roles()
        self._initialize_system_user()
    
    def _initialize_default_roles(self):
        """Initialize default system roles."""
        # Admin role - full access
        admin_role = Role(
            name="admin",
            description="Full system administrator access",
            permissions={perm for perm in Permission},
            is_system_role=True
        )
        
        # User role - basic test execution
        user_role = Role(
            name="user",
            description="Basic user with test execution privileges",
            permissions={
                Permission.RUN_TESTS,
                Permission.RUN_WORKFLOWS,
                Permission.VIEW_RESULTS,
                Permission.UPLOAD_DATA
            },
            is_system_role=True
        )
        
        # Viewer role - read-only access
        viewer_role = Role(
            name="viewer",
            description="Read-only access to test results",
            permissions={Permission.VIEW_RESULTS},
            is_system_role=True
        )
        
        # Service role - for automated systems
        service_role = Role(
            name="service",
            description="Service account with automation privileges",
            permissions={
                Permission.RUN_TESTS,
                Permission.RUN_WORKFLOWS,
                Permission.VIEW_RESULTS,
                Permission.UPLOAD_DATA,
                Permission.ACCESS_PLUGINS
            },
            is_system_role=True
        )
        
        self.roles = {
            "admin": admin_role,
            "user": user_role,
            "viewer": viewer_role,
            "service": service_role
        }
    
    def _initialize_system_user(self):
        """Initialize system user account."""
        system_user = User(
            user_id="system",
            username="system",
            email="system@k6-mcp-server.local",
            roles={"admin"},
            is_service_account=True
        )
        self.users["system"] = system_user
    
    @with_error_handling(component="security", operation="authenticate_user")
    async def authenticate_user(
        self,
        method: AuthenticationMethod,
        credentials: Dict[str, Any],
        request_context: Optional[Dict[str, Any]] = None
    ) -> Optional[User]:
        """
        Authenticate user with various authentication methods.
        
        Args:
            method: Authentication method to use
            credentials: Authentication credentials
            request_context: Additional request context (IP, user agent, etc.)
        
        Returns:
            Authenticated User object or None if authentication fails
        """
        context = ErrorContext(
            operation="authenticate_user",
            component="security",
            metadata={"method": method.value, "context": request_context}
        )
        
        # Check for account lockout
        user_identifier = credentials.get('username') or credentials.get('user_id')
        if user_identifier and self._is_account_locked(user_identifier):
            await self._log_audit_event(
                AuditEventType.AUTHENTICATION,
                user_identifier,
                "login_attempt_locked_account",
                None,
                "failure",
                {"reason": "account_locked", "method": method.value},
                request_context
            )
            raise SecurityViolationError(
                f"Account {user_identifier} is locked due to excessive failed login attempts",
                context=context
            )
        
        try:
            user = None
            
            if method == AuthenticationMethod.BEARER_TOKEN:
                user = await self._authenticate_bearer_token(credentials)
            elif method == AuthenticationMethod.OAUTH2_AUTHORIZATION_CODE:
                user = await self._authenticate_oauth2_auth_code(credentials)
            elif method == AuthenticationMethod.OAUTH2_CLIENT_CREDENTIALS:
                user = await self._authenticate_oauth2_client_credentials(credentials)
            elif method == AuthenticationMethod.OIDC:
                user = await self._authenticate_oidc(credentials)
            elif method == AuthenticationMethod.API_KEY:
                user = await self._authenticate_api_key(credentials)
            elif method == AuthenticationMethod.BASIC_AUTH:
                user = await self._authenticate_basic_auth(credentials)
            else:
                raise SecurityViolationError(
                    f"Unsupported authentication method: {method.value}",
                    context=context
                )
            
            if user:
                # Successful authentication
                user.last_login = datetime.utcnow()
                self._reset_failed_login_attempts(user_identifier)
                
                await self._log_audit_event(
                    AuditEventType.AUTHENTICATION,
                    user.user_id,
                    "successful_login",
                    None,
                    "success",
                    {"method": method.value},
                    request_context
                )
                
                return user
            else:
                # Failed authentication
                if user_identifier:
                    self._record_failed_login_attempt(user_identifier)
                
                await self._log_audit_event(
                    AuditEventType.AUTHENTICATION,
                    user_identifier,
                    "failed_login",
                    None,
                    "failure",
                    {"method": method.value, "reason": "invalid_credentials"},
                    request_context
                )
                
                return None
                
        except Exception as e:
            await self._log_audit_event(
                AuditEventType.AUTHENTICATION,
                user_identifier,
                "authentication_error",
                None,
                "failure",
                {"method": method.value, "error": str(e)},
                request_context
            )
            raise
    
    async def _authenticate_bearer_token(self, credentials: Dict[str, Any]) -> Optional[User]:
        """Authenticate using Bearer token (JWT)."""
        token = credentials.get('token')
        if not token:
            return None
        
        try:
            # Decode and verify JWT token
            secret = self.config.get('jwt_secret', 'default_secret_change_me')
            payload = jwt.decode(token, secret, algorithms=['HS256'])
            
            user_id = payload.get('user_id')
            if not user_id or user_id not in self.users:
                return None
            
            # Check token expiry
            exp = payload.get('exp')
            if exp and datetime.utcfromtimestamp(exp) < datetime.utcnow():
                return None
            
            return self.users[user_id]
            
        except jwt.InvalidTokenError:
            return None
    
    async def _authenticate_oauth2_auth_code(self, credentials: Dict[str, Any]) -> Optional[User]:
        """Authenticate using OAuth2 authorization code flow."""
        auth_code = credentials.get('code')
        redirect_uri = credentials.get('redirect_uri')
        
        if not auth_code or not self.oauth_config:
            return None
        
        try:
            # Exchange authorization code for access token
            token_url = self.oauth_config['token_url']
            client_id = self.oauth_config['client_id']
            client_secret = self.oauth_config['client_secret']
            
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data={
                    'grant_type': 'authorization_code',
                    'code': auth_code,
                    'redirect_uri': redirect_uri,
                    'client_id': client_id,
                    'client_secret': client_secret
                }) as response:
                    if response.status != 200:
                        return None
                    
                    token_data = await response.json()
                    access_token = token_data.get('access_token')
                    
                    if not access_token:
                        return None
                    
                    # Get user info using access token
                    return await self._get_user_from_oauth_token(access_token)
        
        except Exception as e:
            logger.error(f"OAuth2 authentication error: {e}")
            return None
    
    async def _authenticate_oidc(self, credentials: Dict[str, Any]) -> Optional[User]:
        """Authenticate using OpenID Connect."""
        id_token = credentials.get('id_token')
        
        if not id_token or not self.oidc_config:
            return None
        
        try:
            # Verify ID token
            # In production, you'd fetch and verify with the OIDC provider's public keys
            payload = jwt.decode(
                id_token, 
                options={"verify_signature": False}  # For demo purposes
            )
            
            user_id = payload.get('sub')
            email = payload.get('email')
            username = payload.get('preferred_username') or email
            
            if not user_id:
                return None
            
            # Create or update user
            if user_id not in self.users:
                self.users[user_id] = User(
                    user_id=user_id,
                    username=username,
                    email=email,
                    roles={"user"}  # Default role
                )
            
            return self.users[user_id]
            
        except Exception as e:
            logger.error(f"OIDC authentication error: {e}")
            return None
    
    async def _authenticate_api_key(self, credentials: Dict[str, Any]) -> Optional[User]:
        """Authenticate using API key."""
        api_key = credentials.get('api_key')
        
        if not api_key:
            return None
        
        # Hash the API key for comparison
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        # Find user with matching API key hash
        for user in self.users.values():
            if user.metadata.get('api_key_hash') == api_key_hash:
                return user
        
        return None
    
    async def _authenticate_basic_auth(self, credentials: Dict[str, Any]) -> Optional[User]:
        """Authenticate using basic authentication."""
        username = credentials.get('username')
        password = credentials.get('password')
        
        if not username or not password:
            return None
        
        # Find user and verify password
        for user in self.users.values():
            if (user.username == username and 
                self._verify_password(password, user.metadata.get('password_hash', ''))):
                return user
        
        return None
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against hash."""
        if not password_hash:
            return False
        
        # In production, use proper password hashing like bcrypt
        return hashlib.sha256(password.encode()).hexdigest() == password_hash
    
    def authorize_action(
        self,
        user: User,
        permission: Permission,
        resource: Optional[str] = None
    ) -> bool:
        """
        Check if user is authorized to perform an action.
        
        Args:
            user: User requesting authorization
            permission: Required permission
            resource: Optional resource identifier
        
        Returns:
            True if authorized, False otherwise
        """
        if not user.is_active:
            return False
        
        # Collect all permissions from user's roles
        user_permissions = set()
        for role_name in user.roles:
            if role_name in self.roles:
                user_permissions.update(self.roles[role_name].permissions)
        
        # Check if user has required permission
        authorized = permission in user_permissions
        
        # Log authorization attempt
        asyncio.create_task(self._log_audit_event(
            AuditEventType.AUTHORIZATION,
            user.user_id,
            f"check_permission_{permission.value}",
            resource,
            "success" if authorized else "denied",
            {"permission": permission.value, "resource": resource}
        ))
        
        return authorized
    
    def create_session(self, user: User, request_context: Optional[Dict[str, Any]] = None) -> str:
        """Create a new user session."""
        session_id = secrets.token_urlsafe(32)
        
        session_data = {
            'user_id': user.user_id,
            'created_at': datetime.utcnow(),
            'expires_at': datetime.utcnow() + self.security_policy.session_timeout,
            'ip_address': request_context.get('ip_address') if request_context else None,
            'user_agent': request_context.get('user_agent') if request_context else None
        }
        
        self.active_sessions[session_id] = session_data
        
        # Clean up expired sessions
        self._cleanup_expired_sessions()
        
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[User]:
        """Validate session and return associated user."""
        if session_id not in self.active_sessions:
            return None
        
        session = self.active_sessions[session_id]
        
        # Check if session has expired
        if datetime.utcnow() > session['expires_at']:
            del self.active_sessions[session_id]
            return None
        
        user_id = session['user_id']
        return self.users.get(user_id)
    
    def invalidate_session(self, session_id: str):
        """Invalidate a session."""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
    
    def _cleanup_expired_sessions(self):
        """Clean up expired sessions."""
        current_time = datetime.utcnow()
        expired_sessions = [
            session_id for session_id, session in self.active_sessions.items()
            if current_time > session['expires_at']
        ]
        
        for session_id in expired_sessions:
            del self.active_sessions[session_id]
    
    def _is_account_locked(self, user_identifier: str) -> bool:
        """Check if account is locked."""
        if user_identifier in self.locked_accounts:
            lock_time = self.locked_accounts[user_identifier]
            if datetime.utcnow() - lock_time < self.security_policy.account_lockout_duration:
                return True
            else:
                # Lock expired, remove it
                del self.locked_accounts[user_identifier]
        
        return False
    
    def _record_failed_login_attempt(self, user_identifier: str):
        """Record failed login attempt and lock account if threshold exceeded."""
        if user_identifier not in self.failed_login_attempts:
            self.failed_login_attempts[user_identifier] = 0
        
        self.failed_login_attempts[user_identifier] += 1
        
        if (self.failed_login_attempts[user_identifier] >= 
            self.security_policy.max_failed_login_attempts):
            self.locked_accounts[user_identifier] = datetime.utcnow()
            logger.warning(f"Account {user_identifier} locked due to excessive failed login attempts")
    
    def _reset_failed_login_attempts(self, user_identifier: str):
        """Reset failed login attempts counter."""
        if user_identifier in self.failed_login_attempts:
            del self.failed_login_attempts[user_identifier]
        
        if user_identifier in self.locked_accounts:
            del self.locked_accounts[user_identifier]
    
    async def _log_audit_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[str],
        action: str,
        resource: Optional[str],
        result: str,
        details: Optional[Dict[str, Any]] = None,
        request_context: Optional[Dict[str, Any]] = None
    ):
        """Log an audit event."""
        event = AuditEvent(
            event_id=secrets.token_urlsafe(16),
            timestamp=datetime.utcnow(),
            event_type=event_type,
            user_id=user_id,
            action=action,
            resource=resource,
            result=result,
            details=details or {},
            ip_address=request_context.get('ip_address') if request_context else None,
            user_agent=request_context.get('user_agent') if request_context else None
        )
        
        self.audit_events.append(event)
        
        # Log to standard logger as well
        logger.info(
            f"AUDIT: {event_type.value} | {user_id} | {action} | {resource} | {result} | {details}"
        )
        
        # Keep only recent audit events in memory (last 10000)
        if len(self.audit_events) > 10000:
            self.audit_events = self.audit_events[-10000:]
    
    def get_audit_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_type: Optional[AuditEventType] = None,
        user_id: Optional[str] = None,
        limit: int = 1000
    ) -> List[AuditEvent]:
        """Retrieve audit events with filtering."""
        events = self.audit_events
        
        # Apply filters
        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        
        # Sort by timestamp (newest first) and limit
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]
    
    def create_user(
        self,
        user_id: str,
        username: str,
        email: Optional[str] = None,
        roles: Optional[Set[str]] = None,
        is_service_account: bool = False,
        password: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> User:
        """Create a new user account."""
        if user_id in self.users:
            raise ValueError(f"User {user_id} already exists")
        
        # Validate roles
        roles = roles or {"user"}
        invalid_roles = roles - set(self.roles.keys())
        if invalid_roles:
            raise ValueError(f"Invalid roles: {invalid_roles}")
        
        # Create user
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            roles=roles,
            is_service_account=is_service_account
        )
        
        # Set password hash if provided
        if password:
            user.metadata['password_hash'] = hashlib.sha256(password.encode()).hexdigest()
        
        # Set API key hash if provided
        if api_key:
            user.metadata['api_key_hash'] = hashlib.sha256(api_key.encode()).hexdigest()
        
        self.users[user_id] = user
        
        logger.info(f"Created user: {user_id} with roles: {roles}")
        return user
    
    def create_role(
        self,
        name: str,
        description: str,
        permissions: Set[Permission]
    ) -> Role:
        """Create a new role."""
        if name in self.roles:
            raise ValueError(f"Role {name} already exists")
        
        role = Role(
            name=name,
            description=description,
            permissions=permissions
        )
        
        self.roles[name] = role
        
        logger.info(f"Created role: {name} with {len(permissions)} permissions")
        return role
    
    def get_security_metrics(self) -> Dict[str, Any]:
        """Get security-related metrics."""
        return {
            'total_users': len(self.users),
            'active_sessions': len(self.active_sessions),
            'locked_accounts': len(self.locked_accounts),
            'failed_login_attempts': len(self.failed_login_attempts),
            'audit_events_count': len(self.audit_events),
            'roles_count': len(self.roles),
            'system_roles_count': len([r for r in self.roles.values() if r.is_system_role]),
            'service_accounts_count': len([u for u in self.users.values() if u.is_service_account])
        }


# Global security manager instance
global_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Get the global security manager instance."""
    global global_security_manager
    if global_security_manager is None:
        global_security_manager = SecurityManager()
    return global_security_manager


def require_permission(permission: Permission):
    """Decorator to require specific permission for a function."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs or context
            user = kwargs.get('user') or kwargs.get('current_user')
            if not user:
                raise SecurityViolationError("Authentication required")
            
            security_manager = get_security_manager()
            if not security_manager.authorize_action(user, permission):
                raise SecurityViolationError(
                    f"Permission denied: {permission.value} required"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator