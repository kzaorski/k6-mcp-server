import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

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


// K6 handleSummary callback - generates only JSON output
export function handleSummary(data) {
  console.log('📊 Generating K6 spike test results...');
  
  try {
    console.log('✅ JSON results generated successfully');
    
    return {
      // JSON files that MCP server expects
      'test_{{test_id}}_summary.json': JSON.stringify(data, null, 2),
      'test_{{test_id}}_results.json': JSON.stringify(data, null, 2),
      
      // Console output with basic summary
      stdout: `K6 Spike Test completed. Results saved to JSON files and HTML dashboard (html-report_{{test_id}}.html).`,
    };
  } catch (error) {
    console.error('❌ Error in spike handleSummary():', error.message);
    console.error('Stack:', error.stack);
    
    return {
      'reports/{{test_id}}_error_log.txt': `Error in handleSummary(): ${error.message}\nStack: ${error.stack}\nData keys: ${Object.keys(data).join(', ')}`,
      stdout: `Error generating spike results: ${error.message}`,
    };
  }
}