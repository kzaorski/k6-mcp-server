"""
Pytest configuration and fixtures for K6 MCP Server tests.

Provides shared fixtures and test configuration for all test modules.
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from typing import Generator, AsyncGenerator

from core.config import AppConfig, Environment
from core.container import DIContainer
from domain.models import K6TestConfig, LoadPattern, HttpMethod
from repositories.test_repository import TestRepository
from repositories.result_repository import ResultRepository
from services.k6_service import K6TestService


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


@pytest.fixture
def test_config(temp_dir: Path) -> AppConfig:
    """Create test configuration."""
    config = AppConfig(
        environment=Environment.TESTING,
        debug=True,
        base_dir=temp_dir,
        templates_dir=temp_dir / "templates",
        reports_dir=temp_dir / "reports",
        csv_data_dir=temp_dir / "csv_data"
    )
    
    # Create required directories
    config.templates_dir.mkdir(parents=True, exist_ok=True)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    config.csv_data_dir.mkdir(parents=True, exist_ok=True)
    
    return config


@pytest.fixture
def container(test_config: AppConfig) -> DIContainer:
    """Create dependency injection container for tests."""
    container = DIContainer()
    
    # Register test configuration
    container.register_instance(AppConfig, test_config)
    
    # Register repositories
    container.register_singleton(TestRepository)
    container.register_singleton(ResultRepository)
    
    # Register services
    container.register_singleton(K6TestService)
    
    return container


@pytest.fixture
async def test_repository(container: DIContainer) -> TestRepository:
    """Create test repository."""
    return container.resolve(TestRepository)


@pytest.fixture
async def result_repository(container: DIContainer) -> ResultRepository:
    """Create result repository."""
    return container.resolve(ResultRepository)


@pytest.fixture
async def k6_service(container: DIContainer) -> AsyncGenerator[K6TestService, None]:
    """Create and initialize K6 service."""
    service = container.resolve(K6TestService)
    await service.initialize()
    yield service
    await service.dispose()


@pytest.fixture
def sample_test_config() -> K6TestConfig:
    """Create sample test configuration."""
    return K6TestConfig(
        url="https://httpbin.org/get",
        method=HttpMethod.GET,
        virtual_users=1,
        duration="5s",
        load_pattern=LoadPattern.CONSTANT
    )


@pytest.fixture
def sample_test_config_with_payload() -> K6TestConfig:
    """Create sample test configuration with payload."""
    return K6TestConfig(
        url="https://httpbin.org/post",
        method=HttpMethod.POST,
        virtual_users=2,
        iterations=3,
        load_pattern=LoadPattern.CONSTANT,
        payload={"test": "data", "number": 42},
        headers={"Content-Type": "application/json", "User-Agent": "K6-MCP-Test"}
    )


@pytest.fixture
def complex_test_config() -> K6TestConfig:
    """Create complex test configuration."""
    return K6TestConfig(
        url="https://httpbin.org/delay/1",
        method=HttpMethod.GET,
        virtual_users=5,
        duration="10s",
        load_pattern=LoadPattern.RAMP_UP,
        timeout="30s",
        think_time=0.5,
        headers={"Authorization": "Bearer test-token"},
        query_params={"param1": "value1", "param2": "value2"}
    )


@pytest.mark.asyncio
class AsyncTestCase:
    """Base class for async test cases."""
    pass


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers."""
    for item in items:
        # Add async marker to all async tests
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)
        
        # Add integration marker to integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        
        # Add slow marker to tests that might be slow
        if any(keyword in item.nodeid.lower() for keyword in ["k6", "execution", "workflow"]):
            item.add_marker(pytest.mark.slow)


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "unit: mark test as unit test")
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Cleanup after each test."""
    yield
    # Cleanup logic here if needed
    pass