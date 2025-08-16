"""
Result Repository.

Handles persistence and retrieval of test results and metrics.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from core.base import BaseRepository, OperationResult
from core.config import AppConfig
from domain.models import K6TestResult

logger = logging.getLogger(__name__)


class ResultRepository(BaseRepository[K6TestResult]):
    """
    Repository for managing test results and metrics.
    
    Provides CRUD operations for test results with file-based
    persistence and retention policies.
    """
    
    def __init__(self, config: AppConfig):
        super().__init__(config)
        self.results_dir = config.reports_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache for recent results
        self._result_cache: dict[str, K6TestResult] = {}
    
    async def get_by_id(self, test_id: str) -> Optional[K6TestResult]:
        """Get test result by ID."""
        # Check cache first
        if test_id in self._result_cache:
            return self._result_cache[test_id]
        
        # Load from file
        result_file = self.results_dir / f"test_{test_id}_results.json"
        if not result_file.exists():
            return None
        
        try:
            with open(result_file, 'r') as f:
                data = json.load(f)
            
            result = K6TestResult(**data)
            
            # Cache for future access
            self._result_cache[test_id] = result
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error loading result {test_id}: {e}")
            return None
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[K6TestResult]:
        """Get all test results with pagination."""
        result_files = sorted(
            self.results_dir.glob("test_*_results.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        results = []
        start_idx = offset
        end_idx = offset + limit
        
        for result_file in result_files[start_idx:end_idx]:
            try:
                with open(result_file, 'r') as f:
                    data = json.load(f)
                
                result = K6TestResult(**data)
                results.append(result)
                
            except Exception as e:
                self.logger.warning(f"Error loading result file {result_file}: {e}")
                continue
        
        return results
    
    async def create(self, entity: K6TestResult) -> OperationResult[K6TestResult]:
        """Create new test result."""
        return await self.save_result(entity.test_id, entity)
    
    async def save_result(self, test_id: str, result: K6TestResult) -> OperationResult[K6TestResult]:
        """Save test result with specific ID."""
        try:
            result_file = self.results_dir / f"test_{test_id}_results.json"
            
            # Save to file
            with open(result_file, 'w') as f:
                json.dump(result.model_dump(), f, indent=2, default=str)
            
            # Cache the result
            self._result_cache[test_id] = result
            
            self.logger.info(f"Saved test result {test_id}")
            return OperationResult.success_result(result)
            
        except Exception as e:
            self.logger.error(f"Error saving result {test_id}: {e}")
            return OperationResult.error_result(f"Failed to save result: {str(e)}")
    
    async def update(self, test_id: str, entity: K6TestResult) -> OperationResult[K6TestResult]:
        """Update existing test result."""
        return await self.save_result(test_id, entity)
    
    async def delete(self, test_id: str) -> OperationResult[bool]:
        """Delete test result."""
        try:
            result_file = self.results_dir / f"test_{test_id}_results.json"
            
            if not result_file.exists():
                return OperationResult.error_result(f"Result {test_id} not found")
            
            # Remove file
            result_file.unlink()
            
            # Remove from cache
            self._result_cache.pop(test_id, None)
            
            # Also clean up related files
            related_files = [
                self.results_dir / f"test_{test_id}_summary.json",
                self.results_dir / "csv" / f"test_{test_id}_metrics.csv",
                self.results_dir / "html" / f"html-report_{test_id}.html",
                self.results_dir / f"k6_test_{test_id}.js"
            ]
            
            for file_path in related_files:
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception:
                        pass  # Ignore errors for cleanup files
            
            self.logger.info(f"Deleted test result {test_id}")
            return OperationResult.success_result(True)
            
        except Exception as e:
            self.logger.error(f"Error deleting result {test_id}: {e}")
            return OperationResult.error_result(f"Failed to delete result: {str(e)}")
    
    async def get_result(self, test_id: str) -> Optional[K6TestResult]:
        """Alias for get_by_id for backward compatibility."""
        return await self.get_by_id(test_id)
    
    async def list_recent_results(self, days: int = 7, limit: int = 50) -> List[dict]:
        """List recent test results with metadata."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        recent_results = []
        
        result_files = sorted(
            self.results_dir.glob("test_*_results.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for result_file in result_files[:limit]:
            try:
                # Check file modification time
                file_time = datetime.fromtimestamp(result_file.stat().st_mtime)
                if file_time < cutoff_date:
                    continue
                
                with open(result_file, 'r') as f:
                    data = json.load(f)
                
                result_info = {
                    "test_id": data.get("test_id"),
                    "start_time": data.get("start_time"),
                    "end_time": data.get("end_time"),
                    "success": data.get("success"),
                    "duration_seconds": data.get("duration_seconds"),
                    "exit_code": data.get("exit_code"),
                    "config": {
                        "url": data.get("config", {}).get("url"),
                        "method": data.get("config", {}).get("method"),
                        "virtual_users": data.get("config", {}).get("virtual_users")
                    }
                }
                
                recent_results.append(result_info)
                
            except Exception as e:
                self.logger.warning(f"Error reading result file {result_file}: {e}")
                continue
        
        return recent_results
    
    async def get_results_summary(self, days: int = 30) -> dict:
        """Get summary statistics for results."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        total_tests = 0
        successful_tests = 0
        failed_tests = 0
        total_duration = 0.0
        
        result_files = self.results_dir.glob("test_*_results.json")
        
        for result_file in result_files:
            try:
                file_time = datetime.fromtimestamp(result_file.stat().st_mtime)
                if file_time < cutoff_date:
                    continue
                
                with open(result_file, 'r') as f:
                    data = json.load(f)
                
                total_tests += 1
                
                if data.get("success", False):
                    successful_tests += 1
                else:
                    failed_tests += 1
                
                duration = data.get("duration_seconds")
                if duration:
                    total_duration += duration
                
            except Exception as e:
                self.logger.warning(f"Error processing result file {result_file}: {e}")
                continue
        
        avg_duration = total_duration / total_tests if total_tests > 0 else 0
        success_rate = successful_tests / total_tests if total_tests > 0 else 0
        
        return {
            "period_days": days,
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "failed_tests": failed_tests,
            "success_rate": success_rate,
            "average_duration_seconds": avg_duration,
            "total_duration_seconds": total_duration
        }
    
    async def cleanup_old_results(self, retention_days: int = None) -> int:
        """Clean up old test results."""
        retention_days = retention_days or self.config.k6.results_retention_days
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        deleted_count = 0
        
        # Find all result-related files
        patterns = [
            "test_*_results.json",
            "test_*_summary.json", 
            "csv/test_*_metrics.csv",
            "html/html-report_*.html",
            "k6_test_*.js"
        ]
        
        for pattern in patterns:
            for file_path in self.results_dir.glob(pattern):
                try:
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff_date:
                        # Extract test ID from filename
                        if pattern.startswith("test_") and "_results.json" in pattern:
                            test_id = file_path.stem.replace("test_", "").replace("_results", "")
                            self._result_cache.pop(test_id, None)
                        
                        file_path.unlink()
                        deleted_count += 1
                        self.logger.debug(f"Deleted old result file {file_path}")
                        
                except Exception as e:
                    self.logger.warning(f"Error deleting old result file {file_path}: {e}")
                    continue
        
        if deleted_count > 0:
            self.logger.info(f"Cleaned up {deleted_count} old result files")
        
        return deleted_count
    
    async def search_results(self, 
                           success: bool = None,
                           url_pattern: str = None,
                           min_duration: float = None,
                           max_duration: float = None,
                           limit: int = 100) -> List[dict]:
        """Search results by criteria."""
        matching_results = []
        
        result_files = sorted(
            self.results_dir.glob("test_*_results.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for result_file in result_files:
            try:
                with open(result_file, 'r') as f:
                    data = json.load(f)
                
                # Apply filters
                if success is not None and data.get("success") != success:
                    continue
                
                config = data.get("config", {})
                if url_pattern and url_pattern.lower() not in config.get("url", "").lower():
                    continue
                
                duration = data.get("duration_seconds")
                if min_duration is not None and (duration is None or duration < min_duration):
                    continue
                
                if max_duration is not None and (duration is None or duration > max_duration):
                    continue
                
                result_info = {
                    "test_id": data.get("test_id"),
                    "start_time": data.get("start_time"),
                    "success": data.get("success"),
                    "duration_seconds": duration,
                    "exit_code": data.get("exit_code"),
                    "url": config.get("url"),
                    "method": config.get("method"),
                    "virtual_users": config.get("virtual_users")
                }
                
                matching_results.append(result_info)
                
                if len(matching_results) >= limit:
                    break
                    
            except Exception as e:
                self.logger.warning(f"Error processing result file {result_file}: {e}")
                continue
        
        return matching_results