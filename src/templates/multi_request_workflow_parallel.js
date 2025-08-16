import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

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
      const cookieParts = cookieHeader.split(';')[0].split('=');
      if (cookieParts.length >= 2) {
        const name = cookieParts[0].trim();
        const value = cookieParts.slice(1).join('=').trim();
        cookies[name] = value;
        globalContext.cookies[name] = value;
      }
    }
  }
  
  return cookies;
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

// Execute a single step (used in both sequential and parallel modes)
function executeStep(step, stepIndex) {
  const stepStartTime = Date.now();
  let stepSuccess = false;
  
  if (workflowConfig.logRequests) {
    console.log(`\n🔄 Executing step ${stepIndex + 1}/${workflowSteps.length}: ${step.name} (${step.step_id})`);
  }
  
  try {
    // Build request parameters
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
    
    // Add shared cookies if enabled
    if (workflowConfig.shareCookies && Object.keys(globalContext.cookies).length > 0) {
      const cookieHeader = Object.entries(globalContext.cookies)
        .map(([name, value]) => `${name}=${value}`)
        .join('; ');
      headers['Cookie'] = cookieHeader;
    }
    
    let payload = null;
    if (step.payload) {
      if (typeof step.payload === 'string') {
        payload = interpolateTemplate(step.payload, globalContext);
      } else {
        payload = JSON.stringify(
          JSON.parse(JSON.stringify(step.payload), (key, value) => {
            if (typeof value === 'string') {
              return interpolateTemplate(value, globalContext);
            }
            return value;
          })
        );
      }
    }
    
    const params = {
      headers: headers,
      timeout: step.timeout || '30s'
    };
    
    if (workflowConfig.logRequests) {
      console.log(`📡 Request: ${step.method} ${url}`);
      if (Object.keys(headers).length > 0) {
        console.log(`📄 Headers:`, JSON.stringify(headers, null, 2));
      }
      if (payload) {
        console.log(`📦 Payload:`, payload);
      }
    }
    
    // Execute HTTP request
    const response = executeRequest(step.method, url, payload, params);
    const stepDuration = Date.now() - stepStartTime;
    
    // Record step metrics
    stepResponseTimes.add(stepDuration, { 
      step_id: step.step_id,
      method: step.method,
      status: response.status.toString()
    });
    
    // Check response status
    let isSuccess = response.status >= 200 && response.status < 400;
    
    if (isSuccess) {
      stepSuccessCounter.add(1, { 
        step_id: step.step_id,
        status: response.status.toString()
      });
      stepSuccess = true;
      
      if (workflowConfig.logRequests) {
        console.log(`✅ Step ${step.step_id} completed successfully: ${response.status} in ${stepDuration}ms`);
      }
    } else {
      stepErrorCounter.add(1, { 
        step_id: step.step_id,
        status: response.status.toString()
      });
      
      if (workflowConfig.logRequests) {
        console.log(`❌ Step ${step.step_id} failed: ${response.status} in ${stepDuration}ms`);
      }
    }
    
    // Extract variables if defined
    const extractedVars = extractVariables(response, step.extract_variables, step.step_id);
    
    // Extract cookies if enabled
    let extractedCookies = {};
    if (step.extract_cookies && workflowConfig.shareCookies) {
      extractedCookies = extractCookies(response);
    }
    
    // Store response data for context
    globalContext.response[step.step_id] = {
      status: response.status,
      body: response.body,
      headers: response.headers,
      duration: stepDuration
    };
    
    // Build step result
    const stepResult = {
      step_id: step.step_id,
      name: step.name,
      success: isSuccess,
      status: response.status,
      duration: stepDuration,
      extracted_variables: extractedVars,
      extracted_cookies: extractedCookies,
      response_size: response.body ? response.body.length : 0
    };
    
    if (!isSuccess) {
      stepResult.error = `HTTP ${response.status}`;
    }
    
    // Log extracted data
    if (workflowConfig.logRequests && Object.keys(extractedVars).length > 0) {
      console.log(`📊 Extracted variables:`, extractedVars);
    }
    
    return stepResult;
    
  } catch (error) {
    const stepDuration = Date.now() - stepStartTime;
    
    stepErrorCounter.add(1, { 
      step_id: step.step_id,
      error_type: 'execution_error'
    });
    
    if (workflowConfig.logRequests) {
      console.error(`❌ Step ${step.step_id} failed with error:`, error.message);
    }
    
    return {
      step_id: step.step_id,
      name: step.name,
      success: false,
      status: 0,
      duration: stepDuration,
      error: error.message || 'Unknown error'
    };
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
    console.log(`⚡ Execution mode: ${workflowConfig.executionMode}`);
  }
  
  // **KLUCZOWA ZMIANA: Obsługa trybu równoległego**
  if (workflowConfig.executionMode === 'parallel') {
    if (workflowConfig.logRequests) {
      console.log(`🚀 Executing ALL ${workflowSteps.length} requests in PARALLEL`);
    }
    
    // **RÓWNOLEGŁE WYKONANIE**: Wszystkie requesty naraz z http.batch()
    const batchRequests = {};
    const stepMap = {};
    
    // Przygotuj wszystkie requesty dla batch
    for (let i = 0; i < workflowSteps.length; i++) {
      const step = workflowSteps[i];
      stepMap[step.step_id] = { step, index: i };
      
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
        
        let payload = null;
        if (step.payload) {
          if (typeof step.payload === 'string') {
            payload = interpolateTemplate(step.payload, globalContext);
          } else {
            payload = JSON.stringify(
              JSON.parse(JSON.stringify(step.payload), (key, value) => {
                if (typeof value === 'string') {
                  return interpolateTemplate(value, globalContext);
                }
                return value;
              })
            );
          }
        }
        
        const params = {
          headers: headers,
          timeout: step.timeout || '30s'
        };
        
        // Konfiguracja dla http.batch
        batchRequests[step.step_id] = {
          method: step.method,
          url: url,
          body: payload,
          params: params
        };
        
      } catch (error) {
        if (workflowConfig.logRequests) {
          console.error(`❌ Error preparing step ${step.step_id}:`, error.message);
        }
      }
    }
    
    // **WYKONAJ WSZYSTKIE REQUESTY RÓWNOLEGLE**
    const startTime = Date.now();
    const batchResponses = http.batch(batchRequests);
    const totalTime = Date.now() - startTime;
    
    if (workflowConfig.logRequests) {
      console.log(`⚡ ALL ${Object.keys(batchRequests).length} requests completed in ${totalTime}ms (PARALLEL)`);
    }
    
    // Przetwórz wyniki
    for (const [stepId, response] of Object.entries(batchResponses)) {
      const { step, index } = stepMap[stepId];
      const stepDuration = response.timings ? response.timings.duration : 0;
      
      // Record step metrics
      stepResponseTimes.add(stepDuration, { 
        step_id: step.step_id,
        method: step.method,
        status: response.status.toString()
      });
      
      // Check success
      const isSuccess = response.status >= 200 && response.status < 400;
      
      if (isSuccess) {
        stepSuccessCounter.add(1, { 
          step_id: step.step_id,
          status: response.status.toString()
        });
      } else {
        stepErrorCounter.add(1, { 
          step_id: step.step_id,
          status: response.status.toString()
        });
        workflowSuccess = false;
      }
      
      // Extract variables
      const extractedVars = extractVariables(response, step.extract_variables, step.step_id);
      
      // Store response data
      globalContext.response[step.step_id] = {
        status: response.status,
        body: response.body,
        headers: response.headers,
        duration: stepDuration
      };
      
      const stepResult = {
        step_id: step.step_id,
        name: step.name,
        success: isSuccess,
        status: response.status,
        duration: stepDuration,
        extracted_variables: extractedVars,
        response_size: response.body ? response.body.length : 0,
        execution_order: index + 1
      };
      
      if (!isSuccess) {
        stepResult.error = `HTTP ${response.status}`;
      }
      
      stepResults.push(stepResult);
      
      if (workflowConfig.logRequests) {
        const statusIcon = isSuccess ? '✅' : '❌';
        console.log(`${statusIcon} Step ${index + 1}: ${step.name} → ${response.status} (${stepDuration}ms)`);
      }
    }
    
  } else {
    // **SEKWENCYJNE WYKONANIE** (tryb domyślny)
    if (workflowConfig.logRequests) {
      console.log(`📋 Executing ${workflowSteps.length} requests SEQUENTIALLY`);
    }
    
    for (let i = 0; i < workflowSteps.length; i++) {
      const step = workflowSteps[i];
      const stepResult = executeStep(step, i);
      stepResults.push(stepResult);
      
      if (!stepResult.success) {
        workflowSuccess = false;
        if (workflowConfig.stopOnFailure) {
          break;
        }
      }
      
      // Think time between sequential requests
      if (step.think_time && step.think_time > 0) {
        sleep(step.think_time);
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
    console.log(`⚡ Execution mode: ${workflowConfig.executionMode}`);
    console.log(`✅ Successful steps: ${successfulSteps}`);
    console.log(`❌ Failed steps: ${failedSteps}`);
    console.log(`⏭️ Skipped steps: ${skippedSteps}`);
    console.log(`📈 Overall success: ${workflowSuccess ? 'YES' : 'NO'}`);
  }
}

// K6 handleSummary callback - generates JSON workflow results
export function handleSummary(data) {
  console.log('📊 Generating K6 multi-request workflow results...');
  
  try {
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
      parallel_execution_confirmed: workflowConfig.executionMode === 'parallel',
      generated_at: new Date().toISOString()
    };
    
    console.log('✅ Multi-request workflow JSON results generated successfully');
    
    return {
      // Complete workflow summary with step details
      'test_{{test_id}}_workflow_summary.json': JSON.stringify(workflowSummary, null, 2),
      
      // Complete raw K6 data
      'test_{{test_id}}_detailed_summary.json': JSON.stringify(data, null, 2),
      
      // Basic console output with step summary
      stdout: `K6 Multi-Request Workflow completed (${workflowConfig.executionMode.toUpperCase()} mode). Results saved to JSON files and HTML dashboard (html-report_{{test_id}}.html).\n\nWorkflow Steps Summary:\n${stepResults.map(r => 
        `${r.success ? '✅' : '❌'} ${r.name} (${r.step_id}): ${r.status} - ${r.duration}ms`
      ).join('\n')}`,
    };
  } catch (error) {
    console.error('❌ Error in workflow handleSummary():', error.message);
    
    return {
      'test_{{test_id}}_workflow_error.txt': `Error in workflow handleSummary(): ${error.message}\nWorkflow: {{workflow_name}}\nSteps: ${workflowSteps.length}`,
      stdout: `❌ Error generating workflow results: ${error.message}`
    };
  }
}