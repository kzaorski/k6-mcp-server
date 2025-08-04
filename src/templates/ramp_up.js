import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '{{ramp_duration}}', target: {{virtual_users}} },
    { duration: '{{duration}}', target: {{virtual_users}} },
    { duration: '30s', target: 0 },
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

  {{payload_block}}

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });

  // Retry logic
  let retries = {{retry_attempts}};
  while (retries > 0 && response.status >= 400) {
    console.log(`Retrying request, attempts left: ${retries}`);
    {{retry_block}}
    retries--;
  }

  sleep(1);
}