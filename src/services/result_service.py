"""
Result Service.

Business logic for test result processing, analysis, and reporting.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from pathlib import Path

from core.config import AppConfig
from core.base import OperationResult
from core.events import EventType
from domain.models import K6TestResult, WorkflowResult, TestMetrics
from repositories.result_repository import ResultRepository
from utils.performance import performance_monitor, global_health
from .base_service import EnhancedBaseService

logger = logging.getLogger(__name__)


class ResultService(EnhancedBaseService):
    """
    Service for managing test results and generating reports.
    
    Provides result processing, analysis, formatting, and
    cleanup with proper error handling and validation.
    """
    
    def __init__(
        self,
        config: AppConfig,
        result_repository: ResultRepository
    ):
        super().__init__(config)
        self.result_repository = result_repository
    
    async def _initialize_impl(self) -> None:
        """Initialize the result service."""
        await super()._initialize_impl()
        
        # Ensure report directories exist
        self.config.reports_dir.mkdir(parents=True, exist_ok=True)
        (self.config.reports_dir / "html").mkdir(exist_ok=True)
        (self.config.reports_dir / "csv").mkdir(exist_ok=True)
        
        # Register health check
        global_health.register_check("result_service", self.health_check_impl)
        
        self.logger.info("Result service initialized")
    
    @performance_monitor("result_service.get_test_results")
    async def get_test_results(self, test_id: str) -> OperationResult[Dict[str, Any]]:
        """
        Get formatted test results.
        
        Args:
            test_id: Test identifier
            
        Returns:
            Operation result with formatted test results
        """
        return await self.safe_execute(self._get_test_results_internal, test_id)
    
    @performance_monitor("result_service.get_workflow_results")
    async def get_workflow_results(self, workflow_id: str) -> OperationResult[Dict[str, Any]]:
        """
        Get formatted workflow results.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Operation result with formatted workflow results
        """
        return await self.safe_execute(self._get_workflow_results_internal, workflow_id)
    
    @performance_monitor("result_service.generate_summary_report")
    async def generate_summary_report(self, test_ids: List[str]) -> OperationResult[Dict[str, Any]]:
        """
        Generate summary report for multiple tests.
        
        Args:
            test_ids: List of test identifiers
            
        Returns:
            Operation result with summary report
        """
        return await self.execute_with_tracking(
            "generate_summary_report",
            lambda: self._generate_summary_report_internal(test_ids),
            test_count=len(test_ids)
        )
    
    async def list_recent_results(self, days: int = 7, limit: int = 50) -> OperationResult[List[Dict[str, Any]]]:
        """
        List recent test results.
        
        Args:
            days: Number of days to look back
            limit: Maximum number of results
            
        Returns:
            Operation result with recent results list
        """
        return await self.safe_execute(self._list_recent_results_internal, days, limit)
    
    async def analyze_performance_trends(self, test_pattern: str = None, days: int = 30) -> OperationResult[Dict[str, Any]]:
        """
        Analyze performance trends over time.
        
        Args:
            test_pattern: Optional pattern to filter tests
            days: Number of days to analyze
            
        Returns:
            Operation result with trend analysis
        """
        return await self.execute_with_tracking(
            "analyze_performance_trends",
            lambda: self._analyze_performance_trends_internal(test_pattern, days),
            days=days
        )
    
    @performance_monitor("result_service.export_results")
    async def export_results(self, test_id: str, format: str = "json") -> OperationResult[str]:
        """
        Export test results in specified format.
        
        Args:
            test_id: Test identifier
            format: Export format (json, csv, html)
            
        Returns:
            Operation result with export file path
        """
        return await self.safe_execute(self._export_results_internal, test_id, format)
    
    async def cleanup_old_results(self, retention_days: int = None) -> OperationResult[Dict[str, int]]:
        """
        Clean up old test results.
        
        Args:
            retention_days: Number of days to retain results
            
        Returns:
            Operation result with cleanup statistics
        """
        retention_days = retention_days or self.config.k6.results_retention_days
        
        return await self.execute_with_tracking(
            "cleanup_old_results",
            lambda: self._cleanup_old_results_internal(retention_days),
            retention_days=retention_days
        )
    
    # Private methods
    
    async def _get_test_results_internal(self, test_id: str) -> Dict[str, Any]:
        """Internal test results retrieval logic."""
        # Jeśli nie podano test_id, pokaż dostępne raporty
        if not test_id or test_id.lower() in ["list", "available", ""]:
            return await self._list_available_reports()
        
        result = await self.result_repository.get_result(test_id)
        if not result:
            # Sprawdź czy mamy pliki dla tego test_id mimo braku wpisu w repozytorium
            file_paths = await self._get_result_file_paths(test_id)
            if file_paths["summary"]["total_files"] > 0:
                return {
                    "test_id": test_id,
                    "message": "Found files for this test ID but no database record",
                    "files": file_paths,
                    "status": "files_only"
                }
            
            raise ValueError(f"Test results not found for ID: {test_id}")
        
        # Format results for display
        formatted_result = self._format_test_result(result)
        
        # Add file paths if they exist
        file_paths = await self._get_result_file_paths(test_id)
        formatted_result["files"] = file_paths
        
        return formatted_result
    
    async def _get_workflow_results_internal(self, workflow_id: str) -> Dict[str, Any]:
        """Internal workflow results retrieval logic."""
        # For now, return a placeholder since workflow results need special handling
        # In a real implementation, this would work with WorkflowRepository
        return {
            "workflow_id": workflow_id,
            "message": "Workflow results retrieval not implemented yet",
            "status": "pending_implementation"
        }
    
    async def _generate_summary_report_internal(self, test_ids: List[str]) -> Dict[str, Any]:
        """Internal summary report generation logic."""
        if not test_ids:
            raise ValueError("No test IDs provided for summary report")
        
        results = []
        for test_id in test_ids:
            try:
                result = await self.result_repository.get_result(test_id)
                if result:
                    results.append(result)
            except Exception as e:
                self.logger.warning(f"Failed to load result for test {test_id}: {e}")
        
        if not results:
            raise ValueError("No valid test results found")
        
        # Generate summary statistics
        summary = {
            "total_tests": len(results),
            "successful_tests": sum(1 for r in results if r.success),
            "failed_tests": sum(1 for r in results if not r.success),
            "total_duration": sum(r.get_duration() or 0 for r in results),
            "average_duration": 0,
            "metrics_summary": {},
            "test_summaries": []
        }
        
        # Calculate averages
        if summary["total_tests"] > 0:
            summary["average_duration"] = summary["total_duration"] / summary["total_tests"]
            summary["success_rate"] = summary["successful_tests"] / summary["total_tests"]
        
        # Aggregate metrics
        total_requests = 0
        total_failed_requests = 0
        response_times = []
        
        for result in results:
            if result.metrics:
                if result.metrics.http_reqs:
                    total_requests += result.metrics.http_reqs
                
                if result.metrics.http_req_failed:
                    total_failed_requests += result.metrics.http_req_failed * (result.metrics.http_reqs or 0)
                
                if result.metrics.http_req_duration:
                    if "avg" in result.metrics.http_req_duration:
                        response_times.append(result.metrics.http_req_duration["avg"])
            
            # Add individual test summary
            summary["test_summaries"].append({
                "test_id": result.test_id,
                "success": result.success,
                "duration": result.get_duration(),
                "start_time": result.start_time.isoformat() if result.start_time else None,
                "requests": result.metrics.http_reqs if result.metrics else 0,
                "url": result.config.get("url", "Unknown") if result.config else "Unknown"
            })
        
        # Aggregate metrics summary
        summary["metrics_summary"] = {
            "total_requests": total_requests,
            "total_failed_requests": int(total_failed_requests),
            "overall_failure_rate": total_failed_requests / total_requests if total_requests > 0 else 0,
            "average_response_time": sum(response_times) / len(response_times) if response_times else 0
        }
        
        return summary
    
    async def _list_recent_results_internal(self, days: int, limit: int) -> List[Dict[str, Any]]:
        """Internal recent results listing logic."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        # Get recent results from repository
        recent_results = await self.result_repository.list_recent_results(days, limit)
        
        # Format for display
        formatted_results = []
        for result in recent_results:
            formatted_result = {
                "test_id": result.get("test_id", "unknown"),
                "start_time": result.get("start_time"),
                "duration": result.get("duration_seconds"),
                "success": result.get("success", False),
                "url": result.get("url", "Unknown"),
                "virtual_users": result.get("virtual_users", 0),
                "requests": result.get("http_reqs", 0),
                "failure_rate": result.get("failure_rate", 0)
            }
            formatted_results.append(formatted_result)
        
        return formatted_results
    
    async def _analyze_performance_trends_internal(self, test_pattern: str, days: int) -> Dict[str, Any]:
        """Internal performance trend analysis logic."""
        # Get historical data
        historical_results = await self.result_repository.list_recent_results(days, 1000)
        
        if not historical_results:
            return {
                "message": "No historical data available for trend analysis",
                "trends": {}
            }
        
        # Filter by pattern if provided
        if test_pattern:
            filtered_results = []
            for result in historical_results:
                url = result.get("url", "")
                if test_pattern.lower() in url.lower():
                    filtered_results.append(result)
            historical_results = filtered_results
        
        if not historical_results:
            return {
                "message": f"No data found matching pattern: {test_pattern}",
                "trends": {}
            }
        
        # Analyze trends
        trends = {
            "total_tests": len(historical_results),
            "date_range": {
                "start": min(r.get("start_time", "") for r in historical_results if r.get("start_time")),
                "end": max(r.get("start_time", "") for r in historical_results if r.get("start_time"))
            },
            "success_rate_trend": self._calculate_success_rate_trend(historical_results),
            "response_time_trend": self._calculate_response_time_trend(historical_results),
            "throughput_trend": self._calculate_throughput_trend(historical_results),
            "recommendations": []
        }
        
        # Generate recommendations
        avg_success_rate = trends["success_rate_trend"]["average"]
        if avg_success_rate < 0.95:
            trends["recommendations"].append("Success rate is below 95%. Consider investigating error patterns.")
        
        avg_response_time = trends["response_time_trend"]["average"]
        if avg_response_time > 1000:  # 1 second
            trends["recommendations"].append("Average response time is high. Consider performance optimization.")
        
        return trends
    
    def _calculate_success_rate_trend(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate success rate trend from historical results."""
        success_rates = []
        for result in results:
            success = result.get("success", False)
            success_rates.append(1.0 if success else 0.0)
        
        if not success_rates:
            return {"average": 0, "trend": "stable", "data_points": 0}
        
        avg_success_rate = sum(success_rates) / len(success_rates)
        
        # Simple trend calculation (comparing first and last half)
        mid_point = len(success_rates) // 2
        if mid_point > 0:
            first_half_avg = sum(success_rates[:mid_point]) / mid_point
            second_half_avg = sum(success_rates[mid_point:]) / (len(success_rates) - mid_point)
            
            if second_half_avg > first_half_avg + 0.05:
                trend = "improving"
            elif second_half_avg < first_half_avg - 0.05:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        return {
            "average": avg_success_rate,
            "trend": trend,
            "data_points": len(success_rates)
        }
    
    def _calculate_response_time_trend(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate response time trend from historical results."""
        response_times = []
        for result in results:
            duration = result.get("avg_response_time", 0)
            if duration > 0:
                response_times.append(duration)
        
        if not response_times:
            return {"average": 0, "trend": "stable", "data_points": 0}
        
        avg_response_time = sum(response_times) / len(response_times)
        
        # Simple trend calculation
        mid_point = len(response_times) // 2
        if mid_point > 0:
            first_half_avg = sum(response_times[:mid_point]) / mid_point
            second_half_avg = sum(response_times[mid_point:]) / (len(response_times) - mid_point)
            
            change_threshold = first_half_avg * 0.1  # 10% change threshold
            
            if second_half_avg > first_half_avg + change_threshold:
                trend = "increasing"
            elif second_half_avg < first_half_avg - change_threshold:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        return {
            "average": avg_response_time,
            "trend": trend,
            "data_points": len(response_times)
        }
    
    def _calculate_throughput_trend(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate throughput trend from historical results."""
        throughputs = []
        for result in results:
            requests = result.get("http_reqs", 0)
            duration = result.get("duration_seconds", 0)
            if duration > 0:
                throughput = requests / duration  # requests per second
                throughputs.append(throughput)
        
        if not throughputs:
            return {"average": 0, "trend": "stable", "data_points": 0}
        
        avg_throughput = sum(throughputs) / len(throughputs)
        
        # Simple trend calculation
        mid_point = len(throughputs) // 2
        if mid_point > 0:
            first_half_avg = sum(throughputs[:mid_point]) / mid_point
            second_half_avg = sum(throughputs[mid_point:]) / (len(throughputs) - mid_point)
            
            change_threshold = first_half_avg * 0.1  # 10% change threshold
            
            if second_half_avg > first_half_avg + change_threshold:
                trend = "increasing"
            elif second_half_avg < first_half_avg - change_threshold:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        return {
            "average": avg_throughput,
            "trend": trend,
            "data_points": len(throughputs)
        }
    
    async def _export_results_internal(self, test_id: str, format: str) -> str:
        """Internal result export logic."""
        result = await self.result_repository.get_result(test_id)
        if not result:
            raise ValueError(f"Test results not found for ID: {test_id}")
        
        if format.lower() == "json":
            return await self._export_json(test_id, result)
        elif format.lower() == "csv":
            return await self._export_csv(test_id, result)
        elif format.lower() == "html":
            return await self._export_html(test_id, result)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    async def _export_json(self, test_id: str, result: K6TestResult) -> str:
        """Export results as JSON."""
        export_path = self.config.reports_dir / f"export_{test_id}.json"
        
        export_data = {
            "test_id": test_id,
            "exported_at": datetime.utcnow().isoformat(),
            "result": result.model_dump()
        }
        
        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        return str(export_path)
    
    async def _export_csv(self, test_id: str, result: K6TestResult) -> str:
        """Export results as CSV."""
        export_path = self.config.reports_dir / "csv" / f"export_{test_id}.csv"
        
        # Create CSV content (simplified)
        csv_content = "metric,value\n"
        csv_content += f"test_id,{test_id}\n"
        csv_content += f"success,{result.success}\n"
        csv_content += f"start_time,{result.start_time}\n"
        csv_content += f"duration_seconds,{result.get_duration()}\n"
        
        if result.metrics:
            if result.metrics.http_reqs:
                csv_content += f"http_reqs,{result.metrics.http_reqs}\n"
            if result.metrics.http_req_failed:
                csv_content += f"http_req_failed,{result.metrics.http_req_failed}\n"
        
        with open(export_path, 'w') as f:
            f.write(csv_content)
        
        return str(export_path)
    
    async def _export_html(self, test_id: str, result: K6TestResult) -> str:
        """Export results as HTML."""
        export_path = self.config.reports_dir / "html" / f"export_{test_id}.html"
        
        formatted_result = self._format_test_result(result)
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Results - {test_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ background: #f4f4f4; padding: 20px; border-radius: 5px; }}
                .metrics {{ margin: 20px 0; }}
                .metric {{ margin: 10px 0; }}
                .success {{ color: green; }}
                .failure {{ color: red; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Test Results: {test_id}</h1>
                <p class="{'success' if result.success else 'failure'}">
                    Status: {'SUCCESS' if result.success else 'FAILED'}
                </p>
            </div>
            
            <div class="metrics">
                <h2>Test Metrics</h2>
                <div class="metric">Duration: {result.get_duration():.2f} seconds</div>
                <div class="metric">Start Time: {result.start_time}</div>
        """
        
        if result.metrics:
            if result.metrics.http_reqs:
                html_content += f'<div class="metric">Total Requests: {result.metrics.http_reqs}</div>'
            if result.metrics.http_req_failed:
                html_content += f'<div class="metric">Failed Requests: {result.metrics.http_req_failed:.2%}</div>'
        
        html_content += """
            </div>
        </body>
        </html>
        """
        
        with open(export_path, 'w') as f:
            f.write(html_content)
        
        return str(export_path)
    
    async def _cleanup_old_results_internal(self, retention_days: int) -> Dict[str, int]:
        """Internal cleanup logic."""
        # Cleanup from repository
        deleted_results = await self.result_repository.cleanup_old_results(retention_days)
        
        # Cleanup file system
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        deleted_files = 0
        
        for file_path in self.config.reports_dir.rglob("*"):
            if file_path.is_file():
                try:
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff_date:
                        file_path.unlink()
                        deleted_files += 1
                except Exception as e:
                    self.logger.warning(f"Error deleting file {file_path}: {e}")
        
        return {
            "deleted_results": deleted_results,
            "deleted_files": deleted_files,
            "retention_days": retention_days
        }
    
    def _format_test_result(self, result: K6TestResult) -> Dict[str, Any]:
        """Format test result for display."""
        formatted = {
            "test_id": result.test_id,
            "success": result.success,
            "start_time": result.start_time.isoformat() if result.start_time else None,
            "end_time": result.end_time.isoformat() if result.end_time else None,
            "duration_seconds": result.get_duration(),
            "config": result.config,
            "metrics": {}
        }
        
        if result.metrics:
            formatted["metrics"] = {
                "http_requests": result.metrics.http_reqs,
                "failed_request_rate": result.metrics.http_req_failed,
                "response_time": result.metrics.http_req_duration,
                "virtual_users": result.metrics.vus,
                "data_received": result.metrics.data_received,
                "data_sent": result.metrics.data_sent
            }
        
        return formatted
    
    def _format_workflow_result(self, result: WorkflowResult) -> Dict[str, Any]:
        """Format workflow result for display."""
        formatted = {
            "workflow_id": result.workflow_id,
            "success": result.success,
            "start_time": result.start_time.isoformat() if result.start_time else None,
            "end_time": result.end_time.isoformat() if result.end_time else None,
            "duration_seconds": result.get_duration(),
            "step_summary": result.get_step_summary(),
            "success_rate": result.get_success_rate(),
            "total_requests": result.total_requests,
            "successful_requests": result.successful_requests,
            "failed_requests": result.failed_requests,
            "global_variables": result.global_variables,
            "step_results": []
        }
        
        for step in result.step_results:
            formatted["step_results"].append({
                "step_id": step.step_id,
                "success": step.success,
                "duration_seconds": step.get_duration(),
                "status_code": step.status_code,
                "extracted_variables": step.extracted_variables,
                "error_message": step.error_message
            })
        
        return formatted
    
    async def _get_result_file_paths(self, test_id: str) -> Dict[str, Optional[str]]:
        """Get available result file paths for a test."""
        file_paths = {
            "html_reports": [],
            "csv_files": [],
            "json_files": [],
            "script_files": []
        }
        
        # Skanuj wszystkie pliki zawierające test_id w nazwie
        reports_dir = self.config.reports_dir
        
        # HTML raporty - sprawdź oba lokalizacje
        html_patterns = [
            f"html-report_{test_id}.html",  # stara lokalizacja
            f"html/html-report_{test_id}.html"  # nowa lokalizacja
        ]
        
        for pattern in html_patterns:
            html_path = reports_dir / pattern
            if html_path.exists():
                file_paths["html_reports"].append(str(html_path))
        
        # CSV pliki - zarówno metrics jak i workflow_metrics
        csv_patterns = [
            f"test_{test_id}_metrics.csv",
            f"csv/test_{test_id}_metrics.csv",
            f"csv/test_{test_id}_workflow_metrics.csv"
        ]
        
        for pattern in csv_patterns:
            csv_path = reports_dir / pattern
            if csv_path.exists():
                file_paths["csv_files"].append(str(csv_path))
        
        # JSON pliki - wszystkie typy
        json_patterns = [
            f"test_{test_id}_results.json",
            f"test_{test_id}_summary.json",
            f"test_{test_id}_workflow_results.json",
            f"test_{test_id}_workflow_summary.json",
            f"test_{test_id}_detailed_summary.json",
            f"{test_id}_k6_summary.json"
        ]
        
        for pattern in json_patterns:
            json_path = reports_dir / pattern
            if json_path.exists():
                file_paths["json_files"].append(str(json_path))
        
        # Script pliki - K6 JS files
        script_patterns = [
            f"k6_test_{test_id}.js",
            f"k6_workflow_{test_id}.js"
        ]
        
        for pattern in script_patterns:
            script_path = reports_dir / pattern
            if script_path.exists():
                file_paths["script_files"].append(str(script_path))
        
        # Dodaj summary z ilością znalezionych plików
        total_files = (len(file_paths["html_reports"]) + 
                      len(file_paths["csv_files"]) + 
                      len(file_paths["json_files"]) + 
                      len(file_paths["script_files"]))
        
        file_paths["summary"] = {
            "total_files": total_files,
            "test_id": test_id,
            "reports_directory": str(reports_dir)
        }
        
        return file_paths
    
    async def _list_available_reports(self) -> Dict[str, Any]:
        """List all available test reports in the file system."""
        reports_dir = self.config.reports_dir
        
        if not reports_dir.exists():
            return {
                "message": "Reports directory does not exist",
                "available_reports": [],
                "summary": {"total_reports": 0}
            }
        
        # Skanuj wszystkie pliki w katalogu reports
        all_files = []
        for file_path in reports_dir.rglob("*"):
            if file_path.is_file():
                all_files.append(file_path)
        
        # Grupuj pliki według test_id (wyciągaj z nazw plików)
        test_reports = {}
        
        for file_path in all_files:
            filename = file_path.name
            relative_path = file_path.relative_to(reports_dir)
            
            # Próbuj wyciągnąć test_id z różnych wzorców nazw
            test_id = None
            
            # Wzorce dla test_id
            patterns = [
                r'test_([^_]+)_',  # test_ID_xxx
                r'html-report_([^.]+)\.html',  # html-report_ID.html
                r'k6_test_([^.]+)\.js',  # k6_test_ID.js
                r'k6_workflow_([^.]+)\.js',  # k6_workflow_ID.js
                r'([^_/]+)_k6_summary\.json'  # ID_k6_summary.json
            ]
            
            import re
            for pattern in patterns:
                match = re.search(pattern, filename)
                if match:
                    test_id = match.group(1)
                    break
            
            if test_id:
                if test_id not in test_reports:
                    test_reports[test_id] = {
                        "test_id": test_id,
                        "files": [],
                        "file_types": {"html": 0, "csv": 0, "json": 0, "js": 0}
                    }
                
                file_info = {
                    "path": str(relative_path),
                    "name": filename,
                    "size_bytes": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                }
                
                test_reports[test_id]["files"].append(file_info)
                
                # Aktualizuj liczniki typów plików
                if filename.endswith('.html'):
                    test_reports[test_id]["file_types"]["html"] += 1
                elif filename.endswith('.csv'):
                    test_reports[test_id]["file_types"]["csv"] += 1
                elif filename.endswith('.json'):
                    test_reports[test_id]["file_types"]["json"] += 1
                elif filename.endswith('.js'):
                    test_reports[test_id]["file_types"]["js"] += 1
        
        # Sortuj według czasu modyfikacji (najnowsze pierwsze)
        sorted_reports = sorted(
            test_reports.values(),
            key=lambda r: max(f["modified"] for f in r["files"]) if r["files"] else 0,
            reverse=True
        )
        
        return {
            "message": f"Found {len(sorted_reports)} test reports in {reports_dir}",
            "available_reports": sorted_reports,
            "summary": {
                "total_reports": len(sorted_reports),
                "total_files": len(all_files),
                "reports_directory": str(reports_dir)
            }
        }
    
    async def health_check_impl(self) -> Dict[str, Any]:
        """Implementation-specific health check."""
        # Check file system access
        try:
            test_file = self.config.reports_dir / "health_check_test.tmp"
            test_file.write_text("test")
            test_file.unlink()
            file_access = True
        except Exception:
            file_access = False
        
        # Get storage usage
        try:
            total_files = len(list(self.config.reports_dir.rglob("*")))
        except Exception:
            total_files = 0
        
        healthy = file_access and total_files <= 10000
        status = "healthy" if healthy else ("unhealthy" if not file_access else "degraded")
        message = f"File access: {'OK' if file_access else 'FAILED'}, Files: {total_files}"
        
        if not file_access:
            message += " (file system access denied)"
        elif total_files > 10000:
            message += " (high file count)"
        
        return {
            "healthy": healthy,
            "component": "result_service",
            "status": status,
            "message": message,
            "file_system_access": file_access,
            "total_result_files": total_files,
            "reports_directory": str(self.config.reports_dir),
            "warning": "File system issues" if not healthy else None
        }