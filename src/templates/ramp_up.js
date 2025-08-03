import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '{{ramp_duration}}', target: {{virtual_users}} },
    { duration: '{{duration}}', target: {{virtual_users}} },
    { duration: '{{ramp_duration}}', target: 0 },
  ],
  {{#if thresholds}}
  thresholds: {
    {{#each thresholds}}
    '{{@key}}': ['{{this}}'],
    {{/each}}
  },
  {{/if}}
};

export default function() {
  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  {{#if payload}}
  const payload = JSON.stringify({{json payload}});
  const response = http.{{method_lower}}('{{url}}', payload, params);
  {{else}}
  const response = http.{{method_lower}}('{{url}}', params);
  {{/if}}

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });

  sleep(1);
}