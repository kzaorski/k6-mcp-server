"""
Workflow Repository.

Handles persistence and retrieval of workflow configurations and results.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from core.base import BaseRepository, OperationResult
from core.config import AppConfig
from domain.models import WorkflowConfig, WorkflowResult

logger = logging.getLogger(__name__)


class WorkflowRepository(BaseRepository[WorkflowConfig]):
    """
    Repository for managing workflow configurations and results.
    
    Provides CRUD operations for workflow configurations with file-based
    persistence and retention policies.
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.workflows_dir = config.base_dir / "workflows"
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache for active workflows
        self._workflow_cache: dict[str, WorkflowConfig] = {}
        self._result_cache: dict[str, WorkflowResult] = {}
    
    async def get_by_id(self, workflow_id: str) -> Optional[WorkflowConfig]:
        """Get workflow configuration by ID."""
        # Check cache first
        if workflow_id in self._workflow_cache:
            return self._workflow_cache[workflow_id]
        
        # Load from file
        workflow_file = self.workflows_dir / f"{workflow_id}.json"
        if not workflow_file.exists():
            return None
        
        try:
            with open(workflow_file, 'r') as f:
                data = json.load(f)
            
            config = WorkflowConfig(**data['config'])
            
            # Cache for future access
            self._workflow_cache[workflow_id] = config
            
            return config
            
        except Exception as e:
            self.logger.error(f"Error loading workflow {workflow_id}: {e}")
            return None
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[WorkflowConfig]:
        """Get all workflow configurations with pagination."""
        workflow_files = sorted(
            self.workflows_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        configs = []
        start_idx = offset
        end_idx = offset + limit
        
        for workflow_file in workflow_files[start_idx:end_idx]:
            try:
                with open(workflow_file, 'r') as f:
                    data = json.load(f)
                
                config = WorkflowConfig(**data['config'])
                configs.append(config)
                
            except Exception as e:
                self.logger.warning(f"Error loading workflow file {workflow_file}: {e}")
                continue
        
        return configs
    
    async def create(self, entity: WorkflowConfig) -> OperationResult[WorkflowConfig]:
        """Create new workflow configuration."""
        # Generate workflow ID if not provided
        workflow_id = self._generate_workflow_id(entity.workflow_name)
        return await self.create_workflow(workflow_id, entity)
    
    async def create_with_id(self, workflow_id: str, config: WorkflowConfig) -> OperationResult[WorkflowConfig]:
        """Create workflow configuration with specific ID."""
        return await self.create_workflow(workflow_id, config)
    
    async def create_workflow(self, workflow_id: str, config: WorkflowConfig) -> OperationResult[WorkflowConfig]:
        """Create workflow configuration with specific ID."""
        try:
            workflow_file = self.workflows_dir / f"{workflow_id}.json"
            
            # Check if workflow already exists
            if workflow_file.exists():
                return OperationResult.error_result(f"Workflow {workflow_id} already exists")
            
            # Prepare workflow data
            workflow_data = {
                "workflow_id": workflow_id,
                "created_at": datetime.utcnow().isoformat(),
                "config": config.model_dump()
            }
            
            # Save to file
            with open(workflow_file, 'w') as f:
                json.dump(workflow_data, f, indent=2)
            
            # Cache the config
            self._workflow_cache[workflow_id] = config
            
            self.logger.info(f"Created workflow configuration {workflow_id}")
            return OperationResult.success_result(config)
            
        except Exception as e:
            self.logger.error(f"Error creating workflow {workflow_id}: {e}")
            return OperationResult.error_result(f"Failed to create workflow: {str(e)}")
    
    async def update(self, workflow_id: str, entity: WorkflowConfig) -> OperationResult[WorkflowConfig]:
        """Update existing workflow configuration."""
        try:
            workflow_file = self.workflows_dir / f"{workflow_id}.json"
            
            if not workflow_file.exists():
                return OperationResult.error_result(f"Workflow {workflow_id} not found")
            
            # Load existing data
            with open(workflow_file, 'r') as f:
                existing_data = json.load(f)
            
            # Update config
            existing_data['config'] = entity.model_dump()
            existing_data['updated_at'] = datetime.utcnow().isoformat()
            
            # Save updated data
            with open(workflow_file, 'w') as f:
                json.dump(existing_data, f, indent=2)
            
            # Update cache
            self._workflow_cache[workflow_id] = entity
            
            self.logger.info(f"Updated workflow configuration {workflow_id}")
            return OperationResult.success_result(entity)
            
        except Exception as e:
            self.logger.error(f"Error updating workflow {workflow_id}: {e}")
            return OperationResult.error_result(f"Failed to update workflow: {str(e)}")
    
    async def delete(self, workflow_id: str) -> OperationResult[bool]:
        """Delete workflow configuration."""
        try:
            workflow_file = self.workflows_dir / f"{workflow_id}.json"
            
            if not workflow_file.exists():
                return OperationResult.error_result(f"Workflow {workflow_id} not found")
            
            # Remove file
            workflow_file.unlink()
            
            # Remove from cache
            self._workflow_cache.pop(workflow_id, None)
            
            self.logger.info(f"Deleted workflow configuration {workflow_id}")
            return OperationResult.success_result(True)
            
        except Exception as e:
            self.logger.error(f"Error deleting workflow {workflow_id}: {e}")
            return OperationResult.error_result(f"Failed to delete workflow: {str(e)}")
    
    async def save_workflow_result(self, workflow_id: str, result: WorkflowResult) -> OperationResult[WorkflowResult]:
        """Save workflow execution result."""
        try:
            result_file = self.workflows_dir / f"workflow_{workflow_id}_result.json"
            
            # Save to file
            with open(result_file, 'w') as f:
                json.dump(result.model_dump(), f, indent=2, default=str)
            
            # Cache the result
            self._result_cache[workflow_id] = result
            
            self.logger.info(f"Saved workflow result {workflow_id}")
            return OperationResult.success_result(result)
            
        except Exception as e:
            self.logger.error(f"Error saving workflow result {workflow_id}: {e}")
            return OperationResult.error_result(f"Failed to save workflow result: {str(e)}")
    
    async def get_workflow_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        """Get workflow execution result by ID."""
        # Check cache first
        if workflow_id in self._result_cache:
            return self._result_cache[workflow_id]
        
        # Load from file
        result_file = self.workflows_dir / f"workflow_{workflow_id}_result.json"
        if not result_file.exists():
            return None
        
        try:
            with open(result_file, 'r') as f:
                data = json.load(f)
            
            result = WorkflowResult(**data)
            
            # Cache for future access
            self._result_cache[workflow_id] = result
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error loading workflow result {workflow_id}: {e}")
            return None
    
    async def list_recent_workflows(self, days: int = 7, limit: int = 50) -> List[dict]:
        """List recent workflows with metadata."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        recent_workflows = []
        
        workflow_files = sorted(
            self.workflows_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for workflow_file in workflow_files[:limit]:
            try:
                # Skip result files
                if "_result.json" in workflow_file.name:
                    continue
                
                # Check file modification time
                file_time = datetime.fromtimestamp(workflow_file.stat().st_mtime)
                if file_time < cutoff_date:
                    continue
                
                with open(workflow_file, 'r') as f:
                    data = json.load(f)
                
                config = data.get("config", {})
                workflow_info = {
                    "workflow_id": data.get("workflow_id", workflow_file.stem),
                    "workflow_name": config.get("workflow_name"),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "steps_count": len(config.get("steps", [])),
                    "virtual_users": config.get("virtual_users"),
                    "execution_mode": config.get("execution_mode")
                }
                
                recent_workflows.append(workflow_info)
                
            except Exception as e:
                self.logger.warning(f"Error reading workflow file {workflow_file}: {e}")
                continue
        
        return recent_workflows
    
    async def search_workflows(self, 
                             name_pattern: str = None,
                             execution_mode: str = None,
                             min_steps: int = None,
                             max_steps: int = None,
                             limit: int = 100) -> List[dict]:
        """Search workflows by criteria."""
        matching_workflows = []
        
        workflow_files = sorted(
            self.workflows_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for workflow_file in workflow_files:
            try:
                # Skip result files
                if "_result.json" in workflow_file.name:
                    continue
                
                with open(workflow_file, 'r') as f:
                    data = json.load(f)
                
                config = data.get("config", {})
                
                # Apply filters
                if name_pattern and name_pattern.lower() not in config.get("workflow_name", "").lower():
                    continue
                
                if execution_mode and config.get("execution_mode") != execution_mode:
                    continue
                
                steps_count = len(config.get("steps", []))
                if min_steps is not None and steps_count < min_steps:
                    continue
                
                if max_steps is not None and steps_count > max_steps:
                    continue
                
                workflow_info = {
                    "workflow_id": data.get("workflow_id", workflow_file.stem),
                    "workflow_name": config.get("workflow_name"),
                    "created_at": data.get("created_at"),
                    "steps_count": steps_count,
                    "virtual_users": config.get("virtual_users"),
                    "execution_mode": config.get("execution_mode"),
                    "description": config.get("description")
                }
                
                matching_workflows.append(workflow_info)
                
                if len(matching_workflows) >= limit:
                    break
                    
            except Exception as e:
                self.logger.warning(f"Error processing workflow file {workflow_file}: {e}")
                continue
        
        return matching_workflows
    
    async def cleanup_old_workflows(self, retention_days: int = None) -> int:
        """Clean up old workflow configurations and results."""
        retention_days = retention_days or self.config.k6.results_retention_days
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        deleted_count = 0
        
        # Find all workflow-related files
        patterns = ["*.json", "workflow_*_result.json"]
        
        for pattern in patterns:
            for file_path in self.workflows_dir.glob(pattern):
                try:
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff_date:
                        # Extract workflow ID from filename
                        if not "_result.json" in file_path.name:
                            workflow_id = file_path.stem
                            self._workflow_cache.pop(workflow_id, None)
                        else:
                            workflow_id = file_path.stem.replace("workflow_", "").replace("_result", "")
                            self._result_cache.pop(workflow_id, None)
                        
                        file_path.unlink()
                        deleted_count += 1
                        self.logger.debug(f"Deleted old workflow file {file_path}")
                        
                except Exception as e:
                    self.logger.warning(f"Error deleting old workflow file {file_path}: {e}")
                    continue
        
        if deleted_count > 0:
            self.logger.info(f"Cleaned up {deleted_count} old workflow files")
        
        return deleted_count
    
    def _generate_workflow_id(self, workflow_name: str) -> str:
        """Generate unique workflow ID from name."""
        import uuid
        import re
        
        # Clean workflow name for use in ID
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', workflow_name.lower())
        timestamp = int(datetime.utcnow().timestamp())
        
        return f"{clean_name}_{timestamp}_{uuid.uuid4().hex[:8]}"