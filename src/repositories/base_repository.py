"""
Base repository implementation with common functionality.

Provides common repository patterns including caching, pagination,
and error handling.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from core.base import BaseRepository, OperationResult
from core.config import AppConfig
from core.exceptions import RepositoryError, ResourceNotFoundError, ResourceExistsError
from utils.performance import LRUCache

T = TypeVar('T')

logger = logging.getLogger(__name__)


class FileBasedRepository(BaseRepository[T], Generic[T]):
    """
    Base implementation for file-based repositories.
    
    Provides common functionality for storing entities in JSON files
    with caching, validation, and error handling.
    """
    
    def __init__(self, config: AppConfig, entity_type: type, storage_dir: str):
        super().__init__(config)
        self.entity_type = entity_type
        self.storage_dir = Path(config.base_dir) / storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup caching
        self._cache = LRUCache(max_size=1000, ttl_seconds=3600)
        self._lock = asyncio.Lock()
        
        # File extension for entities
        self.file_extension = ".json"
    
    async def get_by_id(self, entity_id: str) -> Optional[T]:
        """Get entity by ID with caching."""
        # Check cache first
        cached_entity = await self._cache.get(entity_id)
        if cached_entity is not None:
            return cached_entity
        
        # Load from file
        entity_file = self._get_entity_file(entity_id)
        if not entity_file.exists():
            return None
        
        try:
            entity = await self._load_entity_from_file(entity_file)
            if entity:
                # Cache the loaded entity
                await self._cache.set(entity_id, entity)
            return entity
        except Exception as e:
            self.logger.error(f"Error loading entity {entity_id}: {e}")
            return None
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Get all entities with pagination."""
        entity_files = sorted(
            self.storage_dir.glob(f"*{self.file_extension}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        entities = []
        start_idx = offset
        end_idx = offset + limit
        
        for entity_file in entity_files[start_idx:end_idx]:
            try:
                entity = await self._load_entity_from_file(entity_file)
                if entity:
                    entities.append(entity)
            except Exception as e:
                self.logger.warning(f"Error loading entity file {entity_file}: {e}")
                continue
        
        return entities
    
    async def create(self, entity: T) -> OperationResult[T]:
        """Create new entity."""
        entity_id = self._extract_entity_id(entity)
        return await self.create_with_id(entity_id, entity)
    
    async def create_with_id(self, entity_id: str, entity: T) -> OperationResult[T]:
        """Create entity with specific ID."""
        async with self._lock:
            entity_file = self._get_entity_file(entity_id)
            
            # Check if entity already exists
            if entity_file.exists():
                return OperationResult.error_result(
                    f"Entity {entity_id} already exists",
                    error_code="RESOURCE_EXISTS"
                )
            
            try:
                # Prepare entity data
                entity_data = await self._prepare_entity_data(entity_id, entity)
                
                # Save to file
                await self._save_entity_to_file(entity_file, entity_data)
                
                # Cache the entity
                await self._cache.set(entity_id, entity)
                
                self.logger.info(f"Created entity {entity_id}")
                return OperationResult.success_result(entity)
                
            except Exception as e:
                self.logger.error(f"Error creating entity {entity_id}: {e}")
                return OperationResult.error_result(
                    f"Failed to create entity: {str(e)}",
                    error_code="CREATE_FAILED"
                )
    
    async def update(self, entity_id: str, entity: T) -> OperationResult[T]:
        """Update existing entity."""
        async with self._lock:
            entity_file = self._get_entity_file(entity_id)
            
            if not entity_file.exists():
                return OperationResult.error_result(
                    f"Entity {entity_id} not found",
                    error_code="RESOURCE_NOT_FOUND"
                )
            
            try:
                # Load existing data to preserve metadata
                existing_data = await self._load_raw_data_from_file(entity_file)
                
                # Update entity data
                entity_data = await self._prepare_entity_data(entity_id, entity)
                entity_data.update({
                    "created_at": existing_data.get("created_at"),
                    "updated_at": datetime.utcnow().isoformat()
                })
                
                # Save updated data
                await self._save_entity_to_file(entity_file, entity_data)
                
                # Update cache
                await self._cache.set(entity_id, entity)
                
                self.logger.info(f"Updated entity {entity_id}")
                return OperationResult.success_result(entity)
                
            except Exception as e:
                self.logger.error(f"Error updating entity {entity_id}: {e}")
                return OperationResult.error_result(
                    f"Failed to update entity: {str(e)}",
                    error_code="UPDATE_FAILED"
                )
    
    async def delete(self, entity_id: str) -> OperationResult[bool]:
        """Delete entity."""
        async with self._lock:
            entity_file = self._get_entity_file(entity_id)
            
            if not entity_file.exists():
                return OperationResult.error_result(
                    f"Entity {entity_id} not found",
                    error_code="RESOURCE_NOT_FOUND"
                )
            
            try:
                # Remove file
                entity_file.unlink()
                
                # Remove from cache
                await self._cache.delete(entity_id)
                
                # Clean up related files
                await self._cleanup_related_files(entity_id)
                
                self.logger.info(f"Deleted entity {entity_id}")
                return OperationResult.success_result(True)
                
            except Exception as e:
                self.logger.error(f"Error deleting entity {entity_id}: {e}")
                return OperationResult.error_result(
                    f"Failed to delete entity: {str(e)}",
                    error_code="DELETE_FAILED"
                )
    
    async def exists(self, entity_id: str) -> bool:
        """Check if entity exists."""
        # Check cache first
        cached_entity = await self._cache.get(entity_id)
        if cached_entity is not None:
            return True
        
        # Check file system
        entity_file = self._get_entity_file(entity_id)
        return entity_file.exists()
    
    async def count(self) -> int:
        """Count total number of entities."""
        entity_files = list(self.storage_dir.glob(f"*{self.file_extension}"))
        return len(entity_files)
    
    async def search(self, criteria: Dict[str, Any], limit: int = 100) -> List[T]:
        """Search entities by criteria."""
        matching_entities = []
        
        entity_files = sorted(
            self.storage_dir.glob(f"*{self.file_extension}"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for entity_file in entity_files:
            if len(matching_entities) >= limit:
                break
            
            try:
                raw_data = await self._load_raw_data_from_file(entity_file)
                
                # Apply search criteria
                if self._matches_criteria(raw_data, criteria):
                    entity = await self._load_entity_from_file(entity_file)
                    if entity:
                        matching_entities.append(entity)
                        
            except Exception as e:
                self.logger.warning(f"Error processing entity file {entity_file}: {e}")
                continue
        
        return matching_entities
    
    async def cleanup_old_entities(self, retention_days: int) -> int:
        """Clean up old entities."""
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        deleted_count = 0
        
        for entity_file in self.storage_dir.glob(f"*{self.file_extension}"):
            try:
                file_time = datetime.fromtimestamp(entity_file.stat().st_mtime)
                if file_time < cutoff_date:
                    entity_id = entity_file.stem
                    
                    # Remove file
                    entity_file.unlink()
                    
                    # Remove from cache
                    await self._cache.delete(entity_id)
                    
                    # Clean up related files
                    await self._cleanup_related_files(entity_id)
                    
                    deleted_count += 1
                    self.logger.debug(f"Deleted old entity {entity_id}")
                    
            except Exception as e:
                self.logger.warning(f"Error deleting old entity file {entity_file}: {e}")
                continue
        
        if deleted_count > 0:
            self.logger.info(f"Cleaned up {deleted_count} old entities")
        
        return deleted_count
    
    def _get_entity_file(self, entity_id: str) -> Path:
        """Get file path for entity."""
        safe_id = self._sanitize_filename(entity_id)
        return self.storage_dir / f"{safe_id}{self.file_extension}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for safe storage."""
        import re
        return re.sub(r'[^\w\-_.]', '_', filename)
    
    async def _load_entity_from_file(self, entity_file: Path) -> Optional[T]:
        """Load entity from file."""
        try:
            raw_data = await self._load_raw_data_from_file(entity_file)
            return self._parse_entity_data(raw_data)
        except Exception as e:
            self.logger.error(f"Error loading entity from {entity_file}: {e}")
            return None
    
    async def _load_raw_data_from_file(self, entity_file: Path) -> Dict[str, Any]:
        """Load raw data from file."""
        with open(entity_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    async def _save_entity_to_file(self, entity_file: Path, entity_data: Dict[str, Any]) -> None:
        """Save entity data to file."""
        with open(entity_file, 'w', encoding='utf-8') as f:
            json.dump(entity_data, f, indent=2, default=str, ensure_ascii=False)
    
    async def _prepare_entity_data(self, entity_id: str, entity: T) -> Dict[str, Any]:
        """Prepare entity data for storage."""
        data = {
            "id": entity_id,
            "created_at": datetime.utcnow().isoformat(),
            "entity_type": self.entity_type.__name__
        }
        
        # Convert entity to dict
        if hasattr(entity, 'model_dump'):
            data["data"] = entity.model_dump()
        elif hasattr(entity, 'dict'):
            data["data"] = entity.dict()
        else:
            data["data"] = entity.__dict__ if hasattr(entity, '__dict__') else str(entity)
        
        return data
    
    def _parse_entity_data(self, raw_data: Dict[str, Any]) -> Optional[T]:
        """Parse entity data from storage format."""
        try:
            entity_data = raw_data.get("data", {})
            if not entity_data:
                return None
            
            # Create entity instance
            if hasattr(self.entity_type, 'model_validate'):
                return self.entity_type.model_validate(entity_data)
            elif hasattr(self.entity_type, 'parse_obj'):
                return self.entity_type.parse_obj(entity_data)
            else:
                return self.entity_type(**entity_data)
                
        except Exception as e:
            self.logger.error(f"Error parsing entity data: {e}")
            return None
    
    def _matches_criteria(self, raw_data: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
        """Check if entity data matches search criteria."""
        entity_data = raw_data.get("data", {})
        
        for key, value in criteria.items():
            if key not in entity_data:
                continue
            
            entity_value = entity_data[key]
            
            # Simple matching logic - can be extended
            if isinstance(value, str) and isinstance(entity_value, str):
                if value.lower() not in entity_value.lower():
                    return False
            elif entity_value != value:
                return False
        
        return True
    
    async def _cleanup_related_files(self, entity_id: str) -> None:
        """Clean up files related to the entity (override in subclasses)."""
        pass
    
    @abstractmethod
    def _extract_entity_id(self, entity: T) -> str:
        """Extract entity ID from entity instance."""
        pass