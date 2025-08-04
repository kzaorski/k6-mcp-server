import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: {{virtual_users}},
  duration: '{{duration}}',
};

export default function() {
  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
    timeout: '{{timeout}}',
  };

  const response = http.{{method_lower}}('{{url}}', params);

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });

  sleep(1);
}