import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

// External report libraries - fallback to simple implementations
// import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
// import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';

// Fallback simple HTML report generator for multi-request workflows
function htmlReport(data) {
  const metrics = data.metrics || {};
  const duration = metrics.http_req_duration?.values || {};
  const reqs = metrics.http_reqs?.values || {};
  const failed = metrics.http_req_failed?.values || {};
  
  const totalRequests = reqs.count || 0;
  const failedRequests = Math.round(totalRequests * (failed.rate || 0));
  
  return `<!DOCTYPE html>
<html>
<head>
  <title>K6 Multi-Request Workflow Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    .header { background: #f5f5f5; padding: 15px; border-radius: 5px; }
    .step { margin: 10px 0; padding: 10px; border-left: 3px solid #007acc; }
    .success { border-left-color: #28a745; }
    .failed { border-left-color: #dc3545; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 20px 0; }
    .metric-box { padding: 10px; background: #f8f9fa; border-radius: 5px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>K6 Multi-Request Workflow Report</h1>
    <p>Workflow: {{workflow_name}}</p>
    <p>Generated: ${new Date().toISOString()}</p>
  </div>
  
  <div class="metrics">
    <div class="metric-box">
      <h3>Total Requests</h3>
      <p>${totalRequests}</p>
    </div>
    <div class="metric-box">
      <h3>Failed Requests</h3>
      <p>${failedRequests}</p>
    </div>
    <div class="metric-box">
      <h3>Average Response Time</h3>
      <p>${Math.round(duration.avg || 0)}ms</p>
    </div>
    <div class="metric-box">
      <h3>95th Percentile</h3>
      <p>${Math.round(duration['p(95)'] || 0)}ms</p>
    </div>
  </div>

  <h2>Step Results</h2>
  <div id="steps">
    <!-- Step results will be populated by K6 script -->
  </div>
</body>
</html>`;
}

// Fallback text summary for workflows
function textSummary(data) {
  const metrics = data.metrics || {};
  const duration = metrics.http_req_duration?.values || {};
  const reqs = metrics.http_reqs?.values || {};
  const failed = metrics.http_req_failed?.values || {};
  
  const totalRequests = reqs.count || 0;
  const successRate = Math.round((1 - (failed.rate || 0)) * 100);
  
  return `
K6 Multi-Request Workflow Results:
=================================
Workflow: {{workflow_name}}
• Total Requests: ${totalRequests}
• Avg Response Time: ${Math.round(duration.avg || 0)}ms
• P95 Response Time: ${Math.round(duration['p(95)'] || 0)}ms
• Success Rate: ${successRate}%
• Execution Mode: {{execution_mode}}
• Stop on Failure: {{stop_on_failure}}
`;
}

// Custom metrics for per-step analysis
const stepResponseTimes = new Trend('step_response_times');
const stepErrorCounter = new Counter('step_errors');
const stepSuccessCounter = new Counter('step_success');
const workflowSuccessCounter = new Counter('workflow_success');

export const options = {
  vus: {{virtual_users}},
  {{execution_mode_block}}
  {{thresholds_block}}
};

// Workflow configuration
const workflowSteps = {{workflow_steps_json}};
const workflowConfig = {
  name: "{{workflow_name}}",
  executionMode: "{{execution_mode}}",
  stopOnFailure: {{stop_on_failure}},
  shareCookies: {{share_cookies}},
  detailedPerStepMetrics: {{detailed_per_step_metrics}},
  logRequests: {{log_requests}}
};

// Global context for storing data between steps
let globalContext = {
  cookies: {},
  response: {},
  extractedVariables: {}
};

// Step execution results for reporting
let stepResults = [];

// Utility functions

function interpolateTemplate(template, context) {
  if (typeof template !== 'string') {
    return template;
  }
  
  return template.replace(/\{\{([^}]+)\}\}/g, (match, path) => {
    const value = getNestedValue(context, path.trim());
    return value !== undefined ? value : match;
  });
}

function getNestedValue(obj, path) {
  return path.split('.').reduce((current, key) => {
    return current && current[key] !== undefined ? current[key] : undefined;
  }, obj);
}

function extractVariables(response, extractionRules, stepId) {
  const extracted = {};
  
  if (!extractionRules) {
    return extracted;
  }
  
  for (const [varName, path] of Object.entries(extractionRules)) {
    try {
      let value;
      
      if (path.startsWith('$.')) {
        // JSON Path extraction
        value = extractJsonPath(response.json(), path);
      } else if (path.startsWith('headers.')) {
        // Header extraction
        const headerName = path.substring(8);
        value = response.headers[headerName];
      } else if (path === 'status') {
        // Status code
        value = response.status;
      }
      
      if (value !== undefined) {
        extracted[varName] = value;
        globalContext.extractedVariables[varName] = value;
      }
    } catch (error) {
      if (workflowConfig.logRequests) {
        console.warn(`Failed to extract ${varName} using path ${path} in step ${stepId}:`, error);
      }
    }
  }
  
  return extracted;
}

function extractJsonPath(data, path) {
  // Simple JSON path implementation for basic paths
  // Supports: $.field, $.field.subfield, $.array[0], $.array[0].field
  
  if (!path.startsWith('$.')) {
    throw new Error('JSON path must start with $.');
  }
  
  const pathParts = path.substring(2).split('.');
  let current = data;
  
  for (let part of pathParts) {
    if (part.includes('[') && part.includes(']')) {
      // Array access: field[index]
      const fieldName = part.substring(0, part.indexOf('['));
      const indexStr = part.substring(part.indexOf('[') + 1, part.indexOf(']'));
      const index = parseInt(indexStr);
      
      if (fieldName && current[fieldName]) {
        current = current[fieldName];
      }
      
      if (Array.isArray(current) && index >= 0 && index < current.length) {
        current = current[index];
      } else {
        return undefined;
      }
    } else {
      // Simple field access
      if (current && typeof current === 'object' && part in current) {
        current = current[part];
      } else {
        return undefined;
      }
    }
  }
  
  return current;
}

function extractCookies(response) {
  const cookies = {};
  const setCookieHeaders = response.headers['Set-Cookie'] || response.headers['set-cookie'];
  
  if (setCookieHeaders) {
    const cookieHeaders = Array.isArray(setCookieHeaders) ? setCookieHeaders : [setCookieHeaders];
    
    for (const cookieHeader of cookieHeaders) {
      const cookieParts = cookieHeader.split(';');
      const nameValue = cookieParts[0].trim();
      
      if (nameValue.includes('=')) {
        const [name, value] = nameValue.split('=', 2);
        cookies[name.trim()] = value.trim();
      }
    }
  }
  
  return cookies;
}

function evaluateCondition(condition, context) {
  if (!condition) {
    return true;
  }
  
  try {
    const interpolatedCondition = interpolateTemplate(condition, context);
    
    // Simple condition evaluation for basic comparisons
    const operators = ['===', '==', '!==', '!=', '<=', '>=', '<', '>'];
    
    for (const op of operators) {
      if (interpolatedCondition.includes(op)) {
        const [left, right] = interpolatedCondition.split(op).map(s => s.trim());
        const leftVal = parseValue(left);
        const rightVal = parseValue(right);
        
        switch (op) {
          case '===':
          case '==':
            return leftVal == rightVal;
          case '!==':
          case '!=':
            return leftVal != rightVal;
          case '<=':
            return leftVal <= rightVal;
          case '>=':
            return leftVal >= rightVal;
          case '<':
            return leftVal < rightVal;
          case '>':
            return leftVal > rightVal;
        }
      }
    }
    
    // If no operator found, treat as boolean
    return !!parseValue(interpolatedCondition);
    
  } catch (error) {
    if (workflowConfig.logRequests) {
      console.warn(`Error evaluating condition '${condition}':`, error);
    }
    return false;
  }
}

function parseValue(valueStr) {
  if (typeof valueStr !== 'string') {
    return valueStr;
  }
  
  valueStr = valueStr.trim();
  
  // Remove quotes
  if ((valueStr.startsWith('"') && valueStr.endsWith('"')) ||
      (valueStr.startsWith("'") && valueStr.endsWith("'"))) {
    return valueStr.slice(1, -1);
  }
  
  // Parse numbers
  if (!isNaN(valueStr)) {
    return parseFloat(valueStr);
  }
  
  // Parse booleans
  if (valueStr === 'true') return true;
  if (valueStr === 'false') return false;
  if (valueStr === 'null') return null;
  
  return valueStr;
}

function executeRequest(method, url, payload, params) {
  switch (method.toUpperCase()) {
    case 'GET':
      return http.get(url, params);
    case 'POST':
      return http.post(url, payload, params);
    case 'PUT':
      return http.put(url, payload, params);
    case 'DELETE':
      return http.del(url, params);
    case 'PATCH':
      return http.patch(url, payload, params);
    case 'HEAD':
      return http.head(url, params);
    case 'OPTIONS':
      return http.options(url, params);
    default:
      throw new Error(`Unsupported HTTP method: ${method}`);
  }
}

// Main workflow execution function
export default function() {
  let workflowSuccess = true;
  stepResults = [];
  
  // Reset global context for each iteration
  globalContext = {
    cookies: {},
    response: {},
    extractedVariables: {},
    // Add built-in variables
    timestamp: Math.floor(Date.now() / 1000),
    current_timestamp: new Date().toISOString(),
    random_int: Math.floor(Math.random() * 9000) + 1000,
    uuid: 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0;
      const v = c == 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    })
  };
  
  if (workflowConfig.logRequests) {
    console.log(`🔄 Starting workflow: ${workflowConfig.name}`);
    console.log(`📊 Steps to execute: ${workflowSteps.length}`);
  }
  
  for (let i = 0; i < workflowSteps.length; i++) {
    const step = workflowSteps[i];
    let stepStartTime = Date.now();
    
    if (workflowConfig.logRequests) {
      console.log(`\n🔄 Executing step ${i + 1}/${workflowSteps.length}: ${step.name} (${step.step_id})`);
    }
    
    // Check dependencies
    if (step.depends_on && step.depends_on.length > 0) {
      let dependenciesMet = true;
      
      for (const dependency of step.depends_on) {
        const depResult = stepResults.find(r => r.step_id === dependency);
        if (!depResult || !depResult.success) {
          console.error(`❌ Step ${step.step_id} skipped - dependency ${dependency} failed or missing`);
          dependenciesMet = false;
          break;
        }
      }
      
      if (!dependenciesMet) {
        stepResults.push({
          step_id: step.step_id,
          name: step.name,
          success: false,
          status: 0,
          duration: 0,
          error: 'Dependencies not met',
          skipped: true
        });
        
        if (workflowConfig.stopOnFailure) {
          workflowSuccess = false;
          break;
        }
        continue;
      }
    }
    
    // Check execution condition
    if (step.condition) {
      const conditionResult = evaluateCondition(step.condition, globalContext);
      if (!conditionResult) {
        if (workflowConfig.logRequests) {
          console.log(`⏭️ Step ${step.step_id} skipped - condition not met: ${step.condition}`);
        }
        
        stepResults.push({
          step_id: step.step_id,
          name: step.name,
          success: true,
          status: 0,
          duration: 0,
          skipped: true,
          condition_result: false
        });
        continue;
      }
    }
    
    // Build request parameters
    try {
      const url = interpolateTemplate(step.url, globalContext);
      
      const headers = {
        {{global_headers_block}}
        ...Object.fromEntries(
          Object.entries(step.headers || {}).map(([k, v]) => [
            k, 
            interpolateTemplate(v, globalContext)
          ])
        )
      };
      
      // Add cookies if sharing is enabled
      if (workflowConfig.shareCookies && Object.keys(globalContext.cookies).length > 0) {
        const cookieString = Object.entries(globalContext.cookies)
          .map(([name, value]) => `${name}=${value}`)
          .join('; ');
        headers['Cookie'] = cookieString;
      }
      
      const params = {
        headers: headers,
        timeout: step.timeout || '30s'
      };
      
      let payload = null;
      if (step.payload && ['POST', 'PUT', 'PATCH'].includes(step.method.toUpperCase())) {
        if (typeof step.payload === 'string') {
          payload = interpolateTemplate(step.payload, globalContext);
        } else {
          const interpolatedPayload = JSON.parse(interpolateTemplate(JSON.stringify(step.payload), globalContext));
          payload = JSON.stringify(interpolatedPayload);
        }
      }
      
      if (workflowConfig.logRequests) {
        console.log(`📤 ${step.method.toUpperCase()} ${url}`);
        console.log(`🔧 Headers:`, JSON.stringify(headers, null, 2));
        if (payload) {
          console.log(`📦 Payload:`, payload);
        }
      }
      
      // Execute request with retry logic
      let response;
      let retries = step.retry_attempts || 0;
      
      do {
        response = executeRequest(step.method, url, payload, params);
        
        if (response.status >= 200 && response.status < 400) {
          break;
        }
        
        if (retries > 0) {
          if (workflowConfig.logRequests) {
            console.log(`🔄 Retrying ${step.step_id}, attempts left: ${retries}`);
          }
          sleep(1);
        }
        
        retries--;
      } while (retries >= 0);
      
      const stepDuration = Date.now() - stepStartTime;
      const stepSuccess = response.status >= 200 && response.status < 400;
      
      // Record metrics
      stepResponseTimes.add(response.timings.duration, {
        step_id: step.step_id,
        step_name: step.name
      });
      
      if (stepSuccess) {
        stepSuccessCounter.add(1, { step_id: step.step_id });
      } else {
        stepErrorCounter.add(1, { 
          step_id: step.step_id,
          status_code: response.status.toString()
        });
      }
      
      if (workflowConfig.logRequests) {
        console.log(`📥 Response: ${response.status} (${response.timings.duration}ms)`);
      }
      
      // Process response for variable extraction
      const extractedVars = extractVariables(response, step.extract_variables, step.step_id);
      
      // Store response data in global context
      globalContext.response[step.step_id] = {
        status: response.status,
        body: response.json ? response.json() : {},
        headers: response.headers,
        extracted: extractedVars
      };
      
      // Extract and store cookies if enabled
      if (step.extract_cookies !== false && workflowConfig.shareCookies) {
        const newCookies = extractCookies(response);
        Object.assign(globalContext.cookies, newCookies);
      }
      
      // Store step result
      stepResults.push({
        step_id: step.step_id,
        name: step.name,
        success: stepSuccess,
        status: response.status,
        duration: stepDuration,
        response_time: response.timings.duration,
        extracted_variables: extractedVars,
        error: stepSuccess ? null : `HTTP ${response.status}`
      });
      
      // Handle step failure
      if (!stepSuccess) {
        workflowSuccess = false;
        
        if (step.on_failure === 'stop' || workflowConfig.stopOnFailure) {
          if (workflowConfig.logRequests) {
            console.error(`❌ Step ${step.step_id} failed with status ${response.status}, stopping workflow`);
          }
          break;
        } else if (step.on_failure === 'continue') {
          if (workflowConfig.logRequests) {
            console.warn(`⚠️ Step ${step.step_id} failed with status ${response.status}, continuing workflow`);
          }
        }
      }
      
      // Think time
      if (step.think_time && step.think_time > 0) {
        sleep(step.think_time);
      }
      
    } catch (error) {
      const stepDuration = Date.now() - stepStartTime;
      
      stepErrorCounter.add(1, { 
        step_id: step.step_id,
        error_type: 'execution_error'
      });
      
      stepResults.push({
        step_id: step.step_id,
        name: step.name,
        success: false,
        status: 0,
        duration: stepDuration,
        error: error.message || 'Unknown error'
      });
      
      workflowSuccess = false;
      
      if (workflowConfig.logRequests) {
        console.error(`❌ Step ${step.step_id} failed with error:`, error.message);
      }
      
      if (step.on_failure === 'stop' || workflowConfig.stopOnFailure) {
        break;
      }
    }
  }
  
  // Record overall workflow success
  if (workflowSuccess) {
    workflowSuccessCounter.add(1);
  }
  
  if (workflowConfig.logRequests) {
    const successfulSteps = stepResults.filter(r => r.success && !r.skipped).length;
    const failedSteps = stepResults.filter(r => !r.success && !r.skipped).length;
    const skippedSteps = stepResults.filter(r => r.skipped).length;
    
    console.log(`\n📊 Workflow completed: ${workflowConfig.name}`);
    console.log(`✅ Successful steps: ${successfulSteps}`);
    console.log(`❌ Failed steps: ${failedSteps}`);
    console.log(`⏭️ Skipped steps: ${skippedSteps}`);
    console.log(`📈 Overall success: ${workflowSuccess ? 'YES' : 'NO'}`);
  }
}

// K6 handleSummary callback - generates multi-request workflow reports
export function handleSummary(data) {
  console.log('📊 Generating K6 multi-request workflow reports...');
  
  try {
    const htmlContent = htmlReport(data);
    const textContent = textSummary(data);
    
    // Enhanced summary with step results
    const workflowSummary = {
      workflow_name: workflowConfig.name,
      execution_mode: workflowConfig.executionMode,
      total_steps: workflowSteps.length,
      step_results: stepResults,
      overall_metrics: {
        total_requests: data.metrics.http_reqs?.values?.count || 0,
        avg_response_time: data.metrics.http_req_duration?.values?.avg || 0,
        error_rate: (data.metrics.http_req_failed?.values?.rate || 0) * 100,
        workflow_success_rate: data.metrics.workflow_success?.values?.rate || 0
      },
      generated_at: new Date().toISOString()
    };
    
    console.log('✅ Multi-request workflow reports generated successfully');
    
    return {
      // Professional HTML report
      'reports/{{test_id}}_workflow_report.html': htmlContent,
      
      // Complete workflow summary with step details
      'reports/{{test_id}}_workflow_summary.json': JSON.stringify(workflowSummary, null, 2),
      
      // Complete raw K6 data
      'reports/{{test_id}}_detailed_summary.json': JSON.stringify(data, null, 2),
      
      // Enhanced console output
      stdout: textContent + `\n\nWorkflow Steps Summary:\n${stepResults.map(r => 
        `${r.success ? '✅' : '❌'} ${r.name} (${r.step_id}): ${r.status} - ${r.duration}ms`
      ).join('\n')}`,
    };
  } catch (error) {
    console.error('❌ Error in workflow handleSummary():', error.message);
    
    return {
      'reports/{{test_id}}_workflow_error.txt': `Error in workflow handleSummary(): ${error.message}\nWorkflow: {{workflow_name}}\nSteps: ${workflowSteps.length}`,
      stdout: `Error generating workflow reports: ${error.message}`,
    };
  }
}