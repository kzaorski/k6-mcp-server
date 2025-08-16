"""
Result Handler.

Handles MCP tool calls for test result operations including retrieval,
analysis, and export functionality.
"""

import logging
from typing import Any, Dict

from core.base import BaseHandler
from core.config import AppConfig
from services.result_service import ResultService

logger = logging.getLogger(__name__)


class ResultHandler(BaseHandler):
    """
    Handler for result-related MCP tool calls.
    
    Processes requests for result retrieval, analysis, export,
    and cleanup with proper validation and error handling.
    """
    
    def __init__(self, config: AppConfig, result_service: ResultService):
        super().__init__(config)
        self.result_service = result_service
    
    async def handle(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle result tool calls."""
        
        try:
            if name == "get_test_results":
                return await self._handle_get_test_results(arguments)
            
            elif name == "get_workflow_results":
                return await self._handle_get_workflow_results(arguments)
            
            elif name == "generate_summary_report":
                return await self._handle_generate_summary_report(arguments)
            
            elif name == "list_recent_results":
                return await self._handle_list_recent_results(arguments)
            
            elif name == "analyze_performance_trends":
                return await self._handle_analyze_performance_trends(arguments)
            
            elif name == "export_results":
                return await self._handle_export_results(arguments)
            
            elif name == "cleanup_old_results":
                return await self._handle_cleanup_old_results(arguments)
            
            else:
                return self.create_error_response(f"Unknown result tool: {name}")
                
        except Exception as e:
            self.logger.error(f"Error handling result {name}: {e}", exc_info=True)
            return self.create_error_response(f"Result handler error: {str(e)}")
    
    async def _handle_get_test_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle test results retrieval."""
        test_id = arguments.get("test_id", "")  # Allow empty test_id to list available reports
        
        operation_id = self.log_operation_start("get_test_results", test_id=test_id or "list_available")
        
        try:
            result = await self.result_service.get_test_results(test_id)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                # Jeśli to lista dostępnych raportów, użyj specjalnego formatowania
                if not test_id or "available_reports" in result.data:
                    formatted_result = self._format_available_reports_display(result.data)
                else:
                    formatted_result = self._format_test_results_display(result.data)
                    
                return self.create_success_response(formatted_result)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to get test results: {str(e)}")
    
    async def _handle_get_workflow_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow results retrieval."""
        workflow_id = arguments.get("workflow_id")
        if not workflow_id:
            return self.create_error_response("workflow_id is required")
        
        operation_id = self.log_operation_start("get_workflow_results", workflow_id=workflow_id)
        
        try:
            result = await self.result_service.get_workflow_results(workflow_id)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                formatted_result = self._format_workflow_results_display(result.data)
                return self.create_success_response(formatted_result)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to get workflow results: {str(e)}")
    
    async def _handle_generate_summary_report(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle summary report generation."""
        test_ids = arguments.get("test_ids", [])
        if not test_ids:
            return self.create_error_response("test_ids list is required")
        
        operation_id = self.log_operation_start("generate_summary_report", test_count=len(test_ids))
        
        try:
            result = await self.result_service.generate_summary_report(test_ids)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                formatted_report = self._format_summary_report(result.data)
                return self.create_success_response(formatted_report)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to generate summary report: {str(e)}")
    
    async def _handle_list_recent_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle recent results listing."""
        days = arguments.get("days", 7)
        limit = arguments.get("limit", 50)
        
        try:
            result = await self.result_service.list_recent_results(days, limit)
            
            if result.success:
                if not result.data:
                    return self.create_success_response("No recent test results found.")
                
                formatted_list = self._format_recent_results_list(result.data, days)
                return self.create_success_response(formatted_list)
            else:
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            return self.create_error_response(f"Failed to list recent results: {str(e)}")
    
    async def _handle_analyze_performance_trends(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle performance trend analysis."""
        test_pattern = arguments.get("test_pattern")
        days = arguments.get("days", 30)
        
        operation_id = self.log_operation_start("analyze_performance_trends", days=days, pattern=test_pattern)
        
        try:
            result = await self.result_service.analyze_performance_trends(test_pattern, days)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                formatted_analysis = self._format_trend_analysis(result.data)
                return self.create_success_response(formatted_analysis)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to analyze performance trends: {str(e)}")
    
    async def _handle_export_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle results export."""
        test_id = arguments.get("test_id")
        format_type = arguments.get("format", "json").lower()
        
        if not test_id:
            return self.create_error_response("test_id is required")
        
        if format_type not in ["json", "csv", "html"]:
            return self.create_error_response("format must be one of: json, csv, html")
        
        operation_id = self.log_operation_start("export_results", test_id=test_id, format=format_type)
        
        try:
            result = await self.result_service.export_results(test_id, format_type)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                export_message = f"""✅ **Results Exported Successfully**

📁 **Export Information:**
• Test ID: {test_id}
• Format: {format_type.upper()}
• File Path: {result.data}

📊 **File Details:**
• Export completed successfully
• File ready for download or analysis
• Format: {format_type.upper()} format

💡 **Usage Tips:**
• JSON: Machine-readable data for further processing
• CSV: Spreadsheet-compatible for data analysis
• HTML: Human-readable report for viewing"""
                
                return self.create_success_response(export_message)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to export results: {str(e)}")
    
    async def _handle_cleanup_old_results(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle old results cleanup."""
        retention_days = arguments.get("retention_days")
        
        operation_id = self.log_operation_start("cleanup_old_results", retention_days=retention_days)
        
        try:
            result = await self.result_service.cleanup_old_results(retention_days)
            
            if result.success:
                self.log_operation_end(operation_id, True)
                
                cleanup_stats = result.data
                cleanup_message = f"""🧹 **Cleanup Completed Successfully**

📊 **Cleanup Statistics:**
• Deleted Results: {cleanup_stats['deleted_results']}
• Deleted Files: {cleanup_stats['deleted_files']}
• Retention Period: {cleanup_stats['retention_days']} days

💾 **Storage Impact:**
• Result database entries cleaned
• Report files removed
• Storage space freed

✅ **System Maintenance:**
• Old data successfully purged
• System performance optimized
• Storage efficiency improved"""
                
                return self.create_success_response(cleanup_message)
            else:
                self.log_operation_end(operation_id, False)
                return self.create_error_response(result.error_message)
                
        except Exception as e:
            self.log_operation_error(operation_id, e)
            return self.create_error_response(f"Failed to cleanup old results: {str(e)}")
    
    def _format_test_results_display(self, result_data: Dict[str, Any]) -> str:
        """Format test results for display."""
        success_icon = "✅" if result_data.get("success") else "❌"
        
        display_text = f"""{success_icon} **Test Results - {result_data.get('test_id')}**

🎯 **Test Information:**
• Success: {'Yes' if result_data.get('success') else 'No'}
• Duration: {result_data.get('duration_seconds', 0):.2f}s
• Start Time: {result_data.get('start_time', 'Unknown')}
• End Time: {result_data.get('end_time', 'Unknown')}

📊 **Performance Metrics:**"""
        
        metrics = result_data.get("metrics", {})
        if metrics.get("http_requests"):
            display_text += f"\n• Total Requests: {metrics['http_requests']}"
        if metrics.get("failed_request_rate") is not None:
            display_text += f"\n• Failed Request Rate: {metrics['failed_request_rate']:.2%}"
        if metrics.get("response_time"):
            response_time = metrics["response_time"]
            if isinstance(response_time, dict):
                if "avg" in response_time:
                    display_text += f"\n• Average Response Time: {response_time['avg']:.2f}ms"
                if "p95" in response_time:
                    display_text += f"\n• 95th Percentile: {response_time['p95']:.2f}ms"
        if metrics.get("virtual_users"):
            display_text += f"\n• Virtual Users: {metrics['virtual_users']}"
        
        # Add configuration details
        config = result_data.get("config", {})
        if config:
            display_text += f"\n\n🔧 **Test Configuration:**"
            display_text += f"\n• URL: {config.get('url', 'Unknown')}"
            display_text += f"\n• Method: {config.get('method', 'Unknown')}"
            display_text += f"\n• Load Pattern: {config.get('load_pattern', 'Unknown')}"
        
        # Add file information
        files = result_data.get("files", {})
        summary = files.get("summary", {})
        
        if summary and summary.get("total_files", 0) > 0:
            display_text += f"\n\n📁 **Generated Files ({summary['total_files']} total):**"
            
            # HTML reports
            html_reports = files.get("html_reports", [])
            if html_reports:
                display_text += f"\n📊 **HTML Reports ({len(html_reports)}):**"
                for html_file in html_reports:
                    display_text += f"\n• {html_file}"
            
            # CSV files
            csv_files = files.get("csv_files", [])
            if csv_files:
                display_text += f"\n📈 **CSV Metrics ({len(csv_files)}):**"
                for csv_file in csv_files:
                    display_text += f"\n• {csv_file}"
            
            # JSON files
            json_files = files.get("json_files", [])
            if json_files:
                display_text += f"\n📋 **JSON Results ({len(json_files)}):**"
                for json_file in json_files:
                    display_text += f"\n• {json_file}"
            
            # Script files
            script_files = files.get("script_files", [])
            if script_files:
                display_text += f"\n⚙️ **K6 Scripts ({len(script_files)}):**"
                for script_file in script_files:
                    display_text += f"\n• {script_file}"
        elif not summary:
            # Fallback do starego formatu jeśli nie ma summary
            if any(files.values()):
                display_text += f"\n\n📁 **Generated Files:**"
                if files.get("html_report"):
                    display_text += f"\n• HTML Report: {files['html_report']}"
                if files.get("csv_file"):
                    display_text += f"\n• CSV Metrics: {files['csv_file']}"
                if files.get("results_json"):
                    display_text += f"\n• Results JSON: {files['results_json']}"
        
        return display_text
    
    def _format_available_reports_display(self, result_data: Dict[str, Any]) -> str:
        """Format available reports list for display."""
        available_reports = result_data.get("available_reports", [])
        summary = result_data.get("summary", {})
        
        if not available_reports:
            return f"""📋 **Stan raportów w MCP**
            
❌ **Brak dostępnych raportów**
{result_data.get('message', 'W systemie nie ma obecnie żadnych zapisanych raportów z testów wydajności.')}

📁 **Katalog raportów:** {summary.get('reports_directory', 'Unknown')}
📊 **Statystyki:** {summary.get('total_files', 0)} plików, {summary.get('total_reports', 0)} raportów

💡 **Aby wygenerować raporty:**
• Uruchom test K6 przez narzędzie `run_k6_single_test` lub `run_k6_workflow_test`
• Raporty będą automatycznie zapisane i dostępne"""

        display_text = f"""📋 **Stan raportów w MCP**

✅ **Dostępne raporty testów wydajności**
{result_data.get('message', f'Znaleziono {len(available_reports)} raportów testów')}

📁 **Katalog:** {summary.get('reports_directory', 'Unknown')}
📊 **Statystyki:** {summary.get('total_files', 0)} plików, {summary.get('total_reports', 0)} raportów

🎯 **Lista raportów (najnowsze pierwsze):**

"""
        
        for i, report in enumerate(available_reports[:10], 1):  # Show first 10 reports
            test_id = report.get("test_id", "unknown")
            file_types = report.get("file_types", {})
            files = report.get("files", [])
            
            # Get most recent file modification time
            latest_time = max(f.get("modified", 0) for f in files) if files else 0
            
            display_text += f"""{i}. **{test_id}**
   📄 Files: {file_types.get('html', 0)} HTML, {file_types.get('csv', 0)} CSV, {file_types.get('json', 0)} JSON, {file_types.get('js', 0)} JS
   📅 Modified: {latest_time}
   
"""
        
        if len(available_reports) > 10:
            display_text += f"... i {len(available_reports) - 10} więcej raportów\n\n"
        
        display_text += f"""💡 **Jak użyć:**
• `get_test_results test_id="ID_TESTU"` - pokaż szczegóły konkretnego raportu
• `analyze_url_performance` - analizuj czasy odpowiedzi per URL
• `get_workflow_results workflow_id="ID"` - wyniki workflow

🔍 **Przykład:** `get_test_results test_id="{available_reports[0].get('test_id', 'example')}"`"""
        
        return display_text
    
    def _format_workflow_results_display(self, result_data: Dict[str, Any]) -> str:
        """Format workflow results for display."""
        success_icon = "✅" if result_data.get("success") else "❌"
        step_summary = result_data.get("step_summary", {})
        
        display_text = f"""{success_icon} **Workflow Results - {result_data.get('workflow_id')}**

🎯 **Workflow Information:**
• Success: {'Yes' if result_data.get('success') else 'No'}
• Duration: {result_data.get('duration_seconds', 0):.2f}s
• Success Rate: {result_data.get('success_rate', 0):.1%}

📊 **Execution Summary:**
• Total Steps: {step_summary.get('total_steps', 0)}
• Successful Steps: {step_summary.get('successful_steps', 0)}
• Failed Steps: {step_summary.get('failed_steps', 0)}
• Total Requests: {result_data.get('total_requests', 0)}
• Successful Requests: {result_data.get('successful_requests', 0)}
• Failed Requests: {result_data.get('failed_requests', 0)}

🔗 **Step Results:**"""
        
        step_results = result_data.get("step_results", [])
        for step in step_results:
            step_icon = "✅" if step.get("success") else "❌"
            step_duration = step.get("duration_seconds", 0)
            
            display_text += f"\n{step_icon} **{step.get('step_id')}** ({step_duration:.2f}s)"
            if step.get("status_code"):
                display_text += f" - HTTP {step['status_code']}"
            if not step.get("success") and step.get("error_message"):
                display_text += f"\n   Error: {step['error_message']}"
            if step.get("extracted_variables"):
                variables = list(step["extracted_variables"].keys())
                display_text += f"\n   Variables: {', '.join(variables)}"
        
        # Add global variables
        global_vars = result_data.get("global_variables", {})
        if global_vars:
            display_text += f"\n\n🔧 **Global Variables:**"
            for var_name, var_value in global_vars.items():
                display_text += f"\n• {var_name}: {var_value}"
        
        return display_text
    
    def _format_summary_report(self, summary_data: Dict[str, Any]) -> str:
        """Format summary report for display."""
        metrics_summary = summary_data.get("metrics_summary", {})
        
        display_text = f"""📊 **Test Summary Report**

📈 **Overall Statistics:**
• Total Tests: {summary_data.get('total_tests', 0)}
• Successful Tests: {summary_data.get('successful_tests', 0)}
• Failed Tests: {summary_data.get('failed_tests', 0)}
• Success Rate: {summary_data.get('success_rate', 0):.1%}
• Total Duration: {summary_data.get('total_duration', 0):.2f}s
• Average Duration: {summary_data.get('average_duration', 0):.2f}s

🌐 **Aggregate Metrics:**
• Total Requests: {metrics_summary.get('total_requests', 0)}
• Failed Requests: {metrics_summary.get('total_failed_requests', 0)}
• Overall Failure Rate: {metrics_summary.get('overall_failure_rate', 0):.2%}
• Average Response Time: {metrics_summary.get('average_response_time', 0):.2f}ms

📋 **Individual Test Summary:**"""
        
        test_summaries = summary_data.get("test_summaries", [])
        for test in test_summaries[:10]:  # Show first 10 tests
            test_icon = "✅" if test.get("success") else "❌"
            display_text += f"\n{test_icon} **{test.get('test_id')}**"
            display_text += f" - {test.get('url', 'Unknown URL')}"
            display_text += f" ({test.get('duration', 0):.1f}s, {test.get('requests', 0)} reqs)"
        
        if len(test_summaries) > 10:
            display_text += f"\n... and {len(test_summaries) - 10} more tests"
        
        return display_text
    
    def _format_recent_results_list(self, results_data: list, days: int) -> str:
        """Format recent results list for display."""
        display_text = f"""📋 **Recent Test Results (Last {days} days)**

Found {len(results_data)} recent test results:

"""
        
        for result in results_data[:20]:  # Show first 20 results
            success_icon = "✅" if result.get("success") else "❌"
            display_text += f"{success_icon} **{result.get('test_id')}**"
            display_text += f" - {result.get('url', 'Unknown URL')}"
            display_text += f" ({result.get('duration', 0):.1f}s)"
            display_text += f" - {result.get('virtual_users', 0)} VUs"
            display_text += f" - {result.get('requests', 0)} reqs"
            if result.get("failure_rate", 0) > 0:
                display_text += f" - {result['failure_rate']:.1%} failures"
            display_text += f"\n   Start: {result.get('start_time', 'Unknown')}\n\n"
        
        if len(results_data) > 20:
            display_text += f"... and {len(results_data) - 20} more results"
        
        return display_text
    
    def _format_trend_analysis(self, analysis_data: Dict[str, Any]) -> str:
        """Format trend analysis for display."""
        if "message" in analysis_data and "trends" in analysis_data and not analysis_data["trends"]:
            return f"📈 **Performance Trend Analysis**\n\n{analysis_data['message']}"
        
        trends = analysis_data.get("trends", {})
        date_range = trends.get("date_range", {})
        success_trend = trends.get("success_rate_trend", {})
        response_trend = trends.get("response_time_trend", {})
        throughput_trend = trends.get("throughput_trend", {})
        
        display_text = f"""📈 **Performance Trend Analysis**

🗓️ **Analysis Period:**
• Total Tests Analyzed: {trends.get('total_tests', 0)}
• Date Range: {date_range.get('start', 'Unknown')} to {date_range.get('end', 'Unknown')}

📊 **Success Rate Trends:**
• Average Success Rate: {success_trend.get('average', 0):.1%}
• Trend: {success_trend.get('trend', 'Unknown').title()}
• Data Points: {success_trend.get('data_points', 0)}

⏱️ **Response Time Trends:**
• Average Response Time: {response_trend.get('average', 0):.2f}ms
• Trend: {response_trend.get('trend', 'Unknown').title()}
• Data Points: {response_trend.get('data_points', 0)}

🚀 **Throughput Trends:**
• Average Throughput: {throughput_trend.get('average', 0):.2f} req/s
• Trend: {throughput_trend.get('trend', 'Unknown').title()}
• Data Points: {throughput_trend.get('data_points', 0)}"""
        
        recommendations = trends.get("recommendations", [])
        if recommendations:
            display_text += f"\n\n💡 **Recommendations:**"
            for i, recommendation in enumerate(recommendations, 1):
                display_text += f"\n{i}. {recommendation}"
        
        return display_text