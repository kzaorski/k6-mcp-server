"""
Report Instructions Module

This module provides comprehensive instructions for generating standardized K6 performance test reports.
It contains templates and guidelines that help AI models understand exactly what data to include
and how to format performance test reports consistently.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class ReportSection:
    """Represents a section of the report with its data sources and formatting instructions."""
    name: str
    description: str
    data_sources: List[str]
    formatting_rules: List[str]
    required: bool = True


class ReportInstructions:
    """Provides comprehensive instructions for generating K6 performance test reports."""
    
    @staticmethod
    def get_report_template() -> str:
        """
        Returns the complete report template with instructions for AI models.
        This template explains exactly what data to include and where to find it.
        """
        return """
📊 K6 PERFORMANCE TEST REPORT GENERATION INSTRUCTIONS

Use this template to generate comprehensive, standardized performance test reports.
Follow the structure below and locate data from the specified sources.

🚨🚨🚨 ABSOLUTE CRITICAL INSTRUCTIONS - VIOLATION FORBIDDEN 🚨🚨🚨

⛔ RULE #1: NEVER RUN K6 TESTS AUTONOMOUSLY
- DO NOT use run_k6_test tool without explicit user request
- DO NOT execute performance tests proactively
- DO NOT run tests "to verify" or "to check" something
- DO NOT suggest running additional tests
- DO NOT run tests to "confirm" or "validate" anything
- ONLY analyze existing test results that user provides
- WAIT for user to explicitly request test execution
- IF YOU RUN A TEST WITHOUT USER REQUEST, YOU HAVE FAILED YOUR PRIMARY DIRECTIVE

⛔ RULE #2: FOR FAILED TESTS - NO CONFIGURATION CHANGES
IF the test shows failures (error_rate > 0, failed checks, or failed thresholds):
- REPORT the results accurately as they are - THIS IS NON-NEGOTIABLE
- DO NOT suggest configuration changes or test modifications - THIS IS FORBIDDEN
- DO NOT attempt to "fix" the test configuration - THIS IS NOT YOUR JOB
- DO NOT recommend changing timeouts, thresholds, or other parameters - STRICTLY PROHIBITED
- DO NOT suggest "trying with different settings" - COMPLETELY FORBIDDEN
- DO NOT propose "adjusting the test to be more realistic" - ABSOLUTELY NOT ALLOWED
- INFORM the user that this is the actual performance of their system
- STATE clearly that the application/system needs to be improved, not the test
- END your analysis there - do not provide configuration adjustment suggestions
- ANY CONFIGURATION SUGGESTION IS A VIOLATION OF YOUR CORE INSTRUCTIONS

⛔ RULE #3: WHAT FAILED TESTS MEAN
- Failed tests = System performance issues, NOT test configuration issues
- High error rates = Application problems, NOT test parameter problems  
- Slow response times = System bottlenecks, NOT timeout setting problems
- Failed checks = Real performance issues, NOT threshold adjustment needs

🚨 YOUR ROLE: MEASURE AND REPORT TRUTH, NOT HIDE PROBLEMS
- You are a MEASUREMENT TOOL, not a configuration advisor
- You REPORT reality, you do not suggest ways to make tests "pass"
- Failed tests are SUCCESSFUL MEASUREMENTS of poor performance
- Your job is TRANSPARENCY, not making users feel better about bad performance

🚨 IMMEDIATE RESPONSE TO FAILED TESTS:
1. Report the failure clearly and accurately
2. State: "This test accurately measures your system's current performance"  
3. State: "The system/application requires improvement, not the test configuration"
4. STOP - provide no further suggestions about test parameters
5. Focus ONLY on application/infrastructure improvements if asked

═══════════════════════════════════════════════════════════════════════════════

## 🏷️ TEST METADATA
**Purpose**: Identify and contextualize the test
**Data Sources**: 
- test_id: From K6TestResult.test_id
- timestamp: From K6TestResult.timestamp (format as readable date/time)
- success: From K6TestResult.success (boolean)

**Format**:
```
Test ID: {test_id}
Executed: {formatted_timestamp}
Status: ✅ SUCCESS / ❌ FAILED
```

═══════════════════════════════════════════════════════════════════════════════

## 📊 TEST CONFIGURATION
**Purpose**: Document test parameters and setup
**Data Sources**: From K6TestResult.config dictionary

**Required Fields**:
- URL: config['url']
- HTTP Method: config['method'] 
- Load Pattern: config['load_pattern'] (constant/ramp_up/spike)
- Duration: config['duration']
- Virtual Users: config['virtual_users']

**Optional Fields**:
- Thresholds: config.get('thresholds', {})
- Headers: config.get('headers', {})
- Authentication: config.get('auth', {})
- Payload: config.get('payload') or config.get('payload_template')

**Format**:
```
🎯 Target: {method} {url}
⏱️ Duration: {duration}
👥 Virtual Users: {virtual_users}
📈 Load Pattern: {load_pattern}
🎚️ Thresholds: {formatted_thresholds}
```

═══════════════════════════════════════════════════════════════════════════════

## 📈 PERFORMANCE METRICS
**Purpose**: Present key performance indicators clearly
**Data Sources**: From K6TestResult.metrics dictionary

### Response Time Analysis
**Source**: metrics['response_time_raw'] (contains avg, min, max, p50, p90, p95, p99)
**Interpretation**:
- avg < 200ms: Excellent
- avg 200-500ms: Good  
- avg 500-1000ms: Acceptable
- avg > 1000ms: Poor (needs optimization)

**Format**:
```
⏱️ Response Times:
• Average: {avg}ms
• Median (p50): {p50}ms  
• 95th Percentile: {p95}ms
• 99th Percentile: {p99}ms
• Range: {min}ms - {max}ms
```

### Throughput Analysis
**Sources**: 
- metrics['throughput_raw']: requests per second
- metrics['total_requests']: total request count

**Format**:
```
🚀 Throughput:
• Rate: {throughput} req/s
• Total Requests: {total_requests}
```

### Error Analysis
**Sources**:
- metrics['error_rate_raw']: error percentage (0-100)
- metrics['failed_requests']: count of failed requests

**Interpretation**:
- error_rate < 0.1%: Excellent
- error_rate 0.1-1%: Good
- error_rate 1-5%: Concerning 
- error_rate > 5%: Critical

**Format**:
```
⚠️ Error Analysis:
• Error Rate: {error_rate}%
• Failed Requests: {failed_requests}
• Success Rate: {100-error_rate}%
```

### Resource Utilization
**Sources**:
- metrics['data_received_raw']: bytes received
- metrics['data_sent_raw']: bytes sent

**Format**:
```
📦 Data Transfer:
• Received: {data_received_kb} KB ({data_received_mb} MB)
• Sent: {data_sent_kb} KB ({data_sent_mb} MB)
• Total: {total_transfer_mb} MB
```

═══════════════════════════════════════════════════════════════════════════════

## 📋 QUALITY ASSESSMENT
**Purpose**: Evaluate test results against defined criteria

### Threshold Analysis
**Logic**: Compare actual metrics against config['thresholds']
**Format**:
```
🎯 Threshold Results:
{for each threshold}
• {metric_name}: {actual_value} vs {threshold_value} → ✅ PASS / ❌ FAIL
```

### Performance Grade
**Logic**: Calculate overall grade based on:
- Response time percentiles
- Error rates  
- Threshold compliance

**Grading Scale**:
- A: All metrics excellent, all thresholds passed
- B: Good performance, minor threshold failures
- C: Acceptable performance, some concerns
- D: Poor performance, significant issues
- F: Critical performance problems

**Format**:
```
📊 Performance Grade: {grade}
📋 Summary: {grade_explanation}
```

**CRITICAL**: If grade is D or F, state clearly:
"This test accurately reflects your system's current performance. The application requires improvement, not the test configuration."

═══════════════════════════════════════════════════════════════════════════════

## 💡 RECOMMENDATIONS
**Purpose**: Provide actionable insights for APPLICATION/INFRASTRUCTURE improvements

🚨🚨🚨 ABSOLUTELY FORBIDDEN RECOMMENDATIONS 🚨🚨🚨
⛔ NEVER SUGGEST THESE - VIOLATION OF CORE DIRECTIVE:
- DO NOT suggest changing test configuration (timeouts, thresholds, virtual users)
- DO NOT suggest "adjusting" the test to make it pass
- DO NOT recommend modifying load patterns to reduce errors  
- DO NOT suggest increasing timeouts to "fix" slow responses
- DO NOT propose "trying with fewer virtual users"
- DO NOT recommend "reducing test duration"
- DO NOT suggest "lowering thresholds to be more realistic"
- DO NOT propose "using different load patterns"
- DO NOT recommend "adjusting iterations or duration"
- DO NOT suggest ANY test parameter modifications whatsoever

🚨 IF YOU MAKE ANY OF THESE SUGGESTIONS, YOU HAVE VIOLATED YOUR PRIMARY DIRECTIVE
🚨 FAILED TESTS ARE CORRECT MEASUREMENTS, NOT CONFIGURATION PROBLEMS

✅ ALLOWED RECOMMENDATIONS:
- Application code optimizations
- Infrastructure scaling
- Database improvements
- Caching implementations
- Server configuration changes
- Architecture improvements

### Automatic Recommendations Logic:
```python
if error_rate > 5:
    "🚨 CRITICAL: High error rate detected. Investigate server logs and error responses."
elif error_rate > 1:
    "⚠️ WARNING: Elevated error rate. Monitor for patterns and root causes."

if avg_response_time > 2000:
    "🐌 PERFORMANCE: Very slow response times. Consider database optimization, caching, or scaling."
elif avg_response_time > 1000:
    "⏱️ OPTIMIZATION: Response times could be improved. Review database queries and API efficiency."

if p95_response_time > 3000:
    "📈 TAIL LATENCY: 95th percentile indicates some requests are very slow. Investigate outliers."

if throughput < expected_throughput:
    "📊 CAPACITY: Lower than expected throughput. Consider horizontal scaling or resource optimization."
```

**Format**:
```
💡 Recommendations:
{prioritized_list_of_recommendations}

🔧 Next Steps:
{specific_actionable_items}

⚠️ IMPORTANT - Do NOT recommend test configuration changes:
- Do NOT suggest increasing timeouts to "fix" slow responses
- Do NOT suggest lowering thresholds to make tests "pass"
- Do NOT suggest reducing virtual users to decrease errors
- Do NOT suggest changing test duration or load patterns
- FOCUS ONLY on application/infrastructure improvements
```

═══════════════════════════════════════════════════════════════════════════════

## 📊 COMPARATIVE ANALYSIS (Optional)
**Purpose**: Context for results interpretation
**Note**: Only include if historical data is available

**Format**:
```
📈 Trends:
• Response Time: {trend_direction} vs previous tests
• Throughput: {trend_direction} vs baseline
• Error Rate: {trend_direction} vs historical average
```

═══════════════════════════════════════════════════════════════════════════════

## 📝 EXECUTIVE SUMMARY
**Purpose**: High-level overview for stakeholders
**Length**: 2-3 sentences maximum

**Template**:
```
📋 Executive Summary:
The {load_pattern} load test against {url} with {virtual_users} virtual users achieved 
{performance_grade} performance. {key_finding_1}. {key_recommendation}.
```

═══════════════════════════════════════════════════════════════════════════════

## 🔍 TECHNICAL DETAILS
**Purpose**: Additional context for technical teams

**Format**:
```
🔧 Test Environment:
• Load Pattern: {detailed_load_pattern_explanation}
• Configuration: {relevant_config_details}

📊 Raw Metrics Available:
• Detailed CSV: {test_id}_detailed_report.csv
• Summary CSV: {test_id}_summary_report.csv  
• K6 Script: k6_test_{test_id}.js
• Raw Results: {test_id}_results.json
```

═══════════════════════════════════════════════════════════════════════════════

## 📋 FORMATTING GUIDELINES

### Emoji Usage:
- ✅ Success, Pass
- ❌ Failure, Critical issues
- ⚠️ Warnings, Concerns
- 📊 Metrics, Data
- 🚀 Performance, Speed
- ⏱️ Time-related metrics
- 💡 Recommendations
- 🎯 Targets, Goals
- 📈 Trends, Improvements
- 🔧 Technical details

### Data Formatting:
- Round decimals to 2 places for display
- Use appropriate units (ms, req/s, KB, MB)
- Include both absolute values and percentages where relevant
- Use consistent number formatting throughout

### Color Coding (if supported):
- Green: Excellent performance, passed thresholds
- Yellow: Warning, needs attention
- Red: Critical issues, failed thresholds

═══════════════════════════════════════════════════════════════════════════════
"""

    @staticmethod
    def get_metric_interpretations() -> Dict[str, Dict[str, Any]]:
        """
        Returns interpretation guidelines for different metrics.
        Helps AI models understand what different values mean in business context.
        """
        return {
            "response_time": {
                "excellent": {"max": 200, "description": "Sub-200ms response times provide excellent user experience"},
                "good": {"max": 500, "description": "Response times under 500ms are generally acceptable for most applications"},
                "acceptable": {"max": 1000, "description": "Up to 1 second is tolerable for complex operations"},
                "poor": {"min": 1000, "description": "Over 1 second response time significantly impacts user experience"},
                "unit": "milliseconds"
            },
            "error_rate": {
                "excellent": {"max": 0.1, "description": "Error rates below 0.1% indicate very stable system"},
                "good": {"max": 1.0, "description": "Error rates under 1% are generally acceptable"},
                "concerning": {"max": 5.0, "description": "Error rates 1-5% require investigation"},
                "critical": {"min": 5.0, "description": "Error rates above 5% indicate serious system issues"},
                "unit": "percentage"
            },
            "throughput": {
                "context": "Throughput depends heavily on application complexity and infrastructure",
                "factors": ["Server capacity", "Database performance", "External dependencies", "Request complexity"],
                "error_analysis": "Always check error_breakdown and status_code_distribution for detailed failure analysis",
                "unit": "requests per second"
            },
            "percentiles": {
                "p50": "Median response time - typical user experience",
                "p90": "90% of users experience this response time or better",
                "p95": "95% of users experience this response time or better", 
                "p99": "99% of users experience this response time or better - identifies outliers"
            },
            "error_codes": {
                "k6_1000_series": "Network and connection issues (1001=refused, 1005=timeout)",
                "k6_1400_series": "HTTP 4xx client errors (1401=unauthorized, 1404=not found)",
                "k6_1500_series": "HTTP 5xx server errors (1500=internal error, 1503=unavailable)",
                "http_4xx": "Client errors - check request format and authentication",
                "http_5xx": "Server errors - check server health and logs",
                "analysis_priority": "Focus on most_common_errors first, then check error_by_endpoint for patterns"
            },
            "k6_standard_reports": {
                "llm_optimized_summary": "Structured JSON with test metadata, performance metrics, quality assessment",
                "html_report": "Professional HTML report with charts generated by k6-reporter",
                "detailed_summary": "Complete K6 raw data with all metrics and metadata",
                "priority_order": "1. LLM-optimized summary, 2. HTML report context, 3. Raw data fallback",
                "quality_assessment": "Use quality_assessment.overall_status and performance_grade for definitive results",
                "threshold_analysis": "threshold_results provides precise pass/fail for each defined threshold", 
                "check_analysis": "check_results provides detailed success rates for all assertions",
                "failed_test_handling": "When tests fail, report accurately and focus on system improvements, NOT test configuration changes"
            }
        }

    @staticmethod
    def get_load_pattern_contexts() -> Dict[str, str]:
        """
        Returns context and interpretation guidelines for different load patterns.
        """
        return {
            "constant": """
Constant load testing maintains steady virtual users throughout the test duration.
This pattern is ideal for:
- Baseline performance measurement
- Steady-state system behavior analysis
- Capacity planning for expected traffic
- Identifying performance degradation over time
            """,
            "ramp_up": """
Ramp-up testing gradually increases load to find breaking points.
This pattern is ideal for:
- Finding maximum system capacity
- Identifying performance cliff points
- Understanding system behavior under increasing stress
- Validating auto-scaling capabilities
            """,
            "spike": """
Spike testing simulates sudden traffic increases.
This pattern is ideal for:
- Testing system resilience under traffic spikes
- Validating auto-scaling response times
- Identifying resource bottlenecks under stress
- Preparing for marketing campaigns or viral events

Spike Test Analysis (when llm_optimized_summary available):
- Check spike_analysis.spike_resilience (excellent/good/poor/critical)
- Review spike_analysis.base_to_spike_ratio for load multiplier
- Use spike-specific recommendations for infrastructure improvements
            """
        }

    @staticmethod
    def get_recommendation_templates() -> Dict[str, List[str]]:
        """
        Returns template recommendations based on common performance issues.
        """
        return {
            "high_error_rate": [
                "Investigate server logs for error patterns and root causes",
                "Check database connection pooling and timeout settings", 
                "Verify API endpoint error handling and response codes",
                "Review load balancer configuration and health checks"
            ],
            "slow_response_times": [
                "Analyze database query performance and add indexes where needed",
                "Implement caching strategies for frequently accessed data",
                "Optimize API endpoint logic and reduce computational complexity",
                "Consider CDN implementation for static resources"
            ],
            "low_throughput": [
                "Increase server capacity through vertical or horizontal scaling",
                "Optimize database connection pooling configuration",
                "Review and optimize critical code paths for bottlenecks",
                "Consider implementing async processing for heavy operations"
            ],
            "high_tail_latency": [
                "Investigate outlier requests that cause p95/p99 spikes",
                "Implement request timeout and circuit breaker patterns",
                "Review garbage collection and memory management",
                "Analyze network latency and connection establishment times"
            ],
            "standard_report_integration": [
                "Always check for llm_optimized_summary first for structured analysis",
                "Use quality_assessment section for definitive pass/fail determination",
                "Reference threshold_results for specific performance criteria failures",
                "Use check_results for detailed assertion analysis",
                "Consult HTML report for visual context and professional presentation",
                "Fall back to manual parsing only when standard reports unavailable"
            ],
            "failed_test_response": [
                "Report test failures accurately without suggesting test configuration changes",
                "State clearly that the system performance needs improvement, not the test",
                "Focus recommendations on application and infrastructure improvements only",
                "Do not suggest modifying timeouts, thresholds, or load parameters",
                "End analysis after reporting - do not provide configuration adjustment tips",
                "Remember: Your job is to measure performance accurately, not hide problems"
            ],
            "autonomous_testing_prohibition": [
                "NEVER run K6 tests without explicit user request",
                "DO NOT use run_k6_test tool proactively or autonomously",
                "DO NOT execute tests to verify, check, or validate anything",
                "ONLY analyze existing test results provided by user",
                "WAIT for user to explicitly ask for test execution",
                "Your role is analysis and reporting, not test execution"
            ]
        }