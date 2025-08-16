"""
Test Repository.

Handles persistence and retrieval of test configurations and metadata.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from core.config import AppConfig
from domain.models import K6TestConfig
from .base_repository import FileBasedRepository

logger = logging.getLogger(__name__)


class TestRepository(FileBasedRepository[K6TestConfig]):
    """
    Repository for managing test configurations and metadata.
    
    Provides CRUD operations for test configurations with file-based
    persistence and retention policies.
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config, K6TestConfig, "tests")
    
    def _extract_entity_id(self, entity: K6TestConfig) -> str:
        """Extract test ID from test configuration."""
        return self._generate_test_id()
    
    async def get_test(self, test_id: str) -> Optional[K6TestConfig]:
        """Alias for get_by_id for backward compatibility."""
        return await self.get_by_id(test_id)
    
    async def create_test(self, test_id: str, config: K6TestConfig):
        """Create test configuration with specific ID."""
        return await self.create_with_id(test_id, config)
    
    async def list_recent_tests(self, days: int = 7, limit: int = 50) -> List[dict]:
        """List recent tests with metadata."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        recent_tests = []
        
        test_files = sorted(
            self.storage_dir.glob(f"*{self.file_extension}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for test_file in test_files[:limit]:
            try:
                # Check file modification time
                file_time = datetime.fromtimestamp(test_file.stat().st_mtime)
                if file_time < cutoff_date:
                    continue
                
                raw_data = await self._load_raw_data_from_file(test_file)
                config_data = raw_data.get("data", {})
                
                test_info = {
                    "test_id": raw_data.get("id", test_file.stem),
                    "created_at": raw_data.get("created_at"),
                    "updated_at": raw_data.get("updated_at"),
                    "url": config_data.get("url"),
                    "method": config_data.get("method"),
                    "virtual_users": config_data.get("virtual_users"),
                    "load_pattern": config_data.get("load_pattern")
                }
                
                recent_tests.append(test_info)
                
            except Exception as e:
                self.logger.warning(f"Error reading test file {test_file}: {e}")
                continue
        
        return recent_tests
    
    async def cleanup_old_tests(self, retention_days: int = None) -> int:
        """Clean up old test configurations."""
        retention_days = retention_days or self.config.k6.results_retention_days
        return await self.cleanup_old_entities(retention_days)
    
    async def search_tests(self, 
                          url_pattern: str = None,
                          method: str = None,
                          load_pattern: str = None,
                          limit: int = 100) -> List[dict]:
        """Search tests by criteria."""
        criteria = {}
        if url_pattern:
            criteria["url"] = url_pattern
        if method:
            criteria["method"] = method
        if load_pattern:
            criteria["load_pattern"] = load_pattern
        
        # Search using base repository method
        tests = await self.search(criteria, limit)
        
        # Convert to dict format for backward compatibility
        result = []
        for test in tests:
            test_info = {
                "test_id": getattr(test, "test_id", "unknown"),
                "url": test.url,
                "method": test.method.value,
                "virtual_users": test.virtual_users,
                "load_pattern": test.load_pattern.value
            }
            result.append(test_info)
        
        return result
    
    def _generate_test_id(self) -> str:
        """Generate unique test ID."""
        import uuid
        timestamp = int(datetime.utcnow().timestamp())
        return f"test_{timestamp}_{uuid.uuid4().hex[:8]}"