import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';
// External report libraries - may fail due to network issues
// import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
// import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

// Fallback simple HTML report generator
function htmlReport(data) {
  const metrics = data.metrics || {};
  const duration = metrics.http_req_duration || {};
  const reqs = metrics.http_reqs || {};
  const failed = metrics.http_req_failed || {};
  
  return `<!DOCTYPE html>
<html>
<head><title>K6 Spike Test Report</title></head>
<body>
<h1>K6 Spike Performance Test Report</h1>
<h2>Summary</h2>
<ul>
<li>Total Requests: ${reqs.count || 0}</li>
<li>Failed Requests: ${Math.round((reqs.count || 0) * (failed.rate || 0))}</li>
<li>Average Response Time: ${Math.round(duration.avg || 0)}ms</li>
<li>95th Percentile: ${Math.round(duration['p(95)'] || 0)}ms</li>
</ul>
<h2>Generated: ${new Date().toISOString()}</h2>
</body>
</html>`;
}

// Fallback text summary
function textSummary(data) {
  const metrics = data.metrics || {};
  const duration = metrics.http_req_duration || {};
  const reqs = metrics.http_reqs || {};
  
  return `
K6 Spike Test Results:
======================
• Total Requests: ${reqs.count || 0}
• Avg Response Time: ${Math.round(duration.avg || 0)}ms
• P95 Response Time: ${Math.round(duration['p(95)'] || 0)}ms
• Success Rate: ${Math.round((1 - (metrics.http_req_failed?.rate || 0)) * 100)}%
`;
}

// Custom metrics for detailed analysis
const responseTimeTrend = new Trend('custom_response_time');
const errorCounter = new Counter('custom_errors');
const successCounter = new Counter('custom_success');

export const options = {
  stages: [
    { duration: '10s', target: {{base_users}} },
    { duration: '1m', target: {{spike_users}} },
    { duration: '10s', target: {{base_users}} },
    { duration: '{{duration}}', target: {{base_users}} },
  ],
  {{thresholds_block}}
};

export default function() {
  const params = {
    headers: {
      'Content-Type': 'application/json',
      {{custom_headers_block}}
      {{auth_header_block}}
    },
    timeout: '{{timeout}}',
    {{cookies_block}}
  };

  {{request_logging_block}}

  {{payload_block}}

  // Record custom metrics
  responseTimeTrend.add(response.timings.duration);
  
  if (response.status >= 200 && response.status < 400) {
    successCounter.add(1);
  } else {
    errorCounter.add(1);
  }

  {{checks_block}}

  // Retry logic
  let retries = {{retry_attempts}};
  while (retries > 0 && response.status >= 400) {
    console.log(`Retrying request, attempts left: ${retries}`);
    {{retry_block}}
    retries--;
  }

  sleep({{think_time}});
}


// K6 handleSummary callback - generates only HTML report + console output
export function handleSummary(data) {
  console.log('📊 Generating K6 spike test reports...');
  
  try {
    const htmlContent = htmlReport(data);
    const textContent = textSummary(data);
    
    console.log('✅ HTML spike report generated successfully');
    
    return {
      'reports/{{test_id}}_standard_report.html': htmlContent,
      stdout: textContent,
    };
  } catch (error) {
    console.error('❌ Error in spike handleSummary():', error.message);
    console.error('Stack:', error.stack);
    
    return {
      'reports/{{test_id}}_error_log.txt': `Error in handleSummary(): ${error.message}\nStack: ${error.stack}\nData keys: ${Object.keys(data).join(', ')}`,
      stdout: `Error generating spike reports: ${error.message}`,
    };
  }
}