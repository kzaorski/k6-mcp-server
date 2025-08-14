import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

// Custom metrics for HAR-based workflow testing
const harStepResponseTimes = new Trend('har_step_response_times');
const harStepErrorCounter = new Counter('har_step_errors');
const harStepSuccessCounter = new Counter('har_step_success');
const harWorkflowSuccessCounter = new Counter('har_workflow_success');
const harStaticFilesMetrics = new Trend('har_static_files_response_times');

export const options = {
  {{options_block}}
  {{thresholds_block}}
};

// Workflow configuration generated from HAR file
const harWorkflowConfig = {{workflow_config}};

// Static files configuration  
const staticFilesConfig = {{static_files_config}};

// Workflow steps generated from HAR
const harWorkflowSteps = {{workflow_steps}};

// Global context for storing data between HAR steps
let harGlobalContext = {
  cookies: {},
  response: {},
  extractedVariables: {},
  // Built-in variables available in HAR workflows
  timestamp: Math.floor(Date.now() / 1000),
  current_timestamp: new Date().toISOString(),
  random_int: Math.floor(Math.random() * 9000) + 1000,
  uuid: 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  })
};

// HAR step execution results
let harStepResults = [];

/**
 * Template variable interpolation for HAR workflows
 * Supports {{variable}} syntax with nested object access
 */
function interpolateHarTemplate(template, context) {
  if (typeof template !== 'string') {
    return template;
  }
  
  return template.replace(/\{\{([^}]+)\}\}/g, (match, path) => {
    const value = getHarNestedValue(context, path.trim());
    if (harWorkflowConfig.logRequests) {
      console.log(`🔍 HAR Template interpolation: ${match} -> ${value}`);
    }
    return value !== undefined ? value : match;
  });
}

/**
 * Get nested value from context object using dot notation
 * Supports HAR-specific context structure
 */
function getHarNestedValue(obj, path) {
  return path.split('.').reduce((current, key) => {
    return current && current[key] !== undefined ? current[key] : undefined;
  }, obj);
}

/**
 * Extract variables from HTTP response for HAR workflow chaining
 * Supports JSON path extraction and header/cookie extraction
 */
function extractHarVariables(response, extractionRules, stepId) {
  const extracted = {};
  
  if (!extractionRules) {
    return extracted;
  }
  
  for (const [varName, path] of Object.entries(extractionRules)) {
    try {
      let value;
      
      if (path.startsWith('$.')) {
        // JSON Path extraction for HAR responses
        value = extractHarJsonPath(response.json(), path);
      } else if (path.startsWith('headers.')) {
        // Header extraction
        const headerName = path.substring(8);
        value = response.headers[headerName];
      } else if (path.startsWith('cookies.')) {
        // Cookie extraction (HAR-specific)
        const cookieName = path.substring(8);
        value = extractHarCookieValue(response, cookieName);
      } else if (path === 'status') {
        value = response.status;
      }
      
      if (value !== undefined) {
        extracted[varName] = value;
        harGlobalContext.extractedVariables[varName] = value;
        
        if (harWorkflowConfig.logRequests) {
          console.log(`✅ HAR: Extracted ${varName} = ${value} from step ${stepId}`);
        }
      }
    } catch (error) {
      console.warn(`⚠️ HAR: Failed to extract ${varName} using path ${path} in step ${stepId}:`, error.message);
    }
  }
  
  return extracted;
}

/**
 * JSON path extraction for HAR response data
 * Enhanced to handle array access patterns common in HAR workflows
 */
function extractHarJsonPath(data, path) {
  if (!path.startsWith('$.')) {
    throw new Error('HAR JSON path must start with $.');
  }
  
  const pathParts = path.substring(2).split('.');
  let current = data;
  
  for (let part of pathParts) {
    if (part.includes('[') && part.includes(']')) {
      // Handle array access: field[0] or [0]
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

/**
 * Extract cookie value from response (HAR-specific)
 */
function extractHarCookieValue(response, cookieName) {
  const setCookieHeaders = response.headers['Set-Cookie'] || response.headers['set-cookie'];
  
  if (setCookieHeaders) {
    const cookieHeaders = Array.isArray(setCookieHeaders) ? setCookieHeaders : [setCookieHeaders];
    
    for (const cookieHeader of cookieHeaders) {
      if (cookieHeader.includes(`${cookieName}=`)) {
        const cookieParts = cookieHeader.split(';');
        const nameValue = cookieParts[0].trim();
        
        if (nameValue.startsWith(`${cookieName}=`)) {
          return nameValue.substring(cookieName.length + 1);
        }
      }
    }
  }
  
  return undefined;
}

/**
 * Process static files for a HAR-based page load simulation
 * Supports different loading patterns: burst, distributed, realistic
 */
function processHarStaticFiles(staticUrls, loadPattern, parallelLoading) {
  if (!staticUrls || staticUrls.length === 0) {
    return;
  }
  
  if (harWorkflowConfig.logRequests) {
    console.log(`🎨 HAR: Loading ${staticUrls.length} static files using ${loadPattern} pattern`);
  }
  
  switch (loadPattern) {
    case 'burst':
      // Load all static files in parallel burst (typical browser behavior)
      if (parallelLoading && staticUrls.length > 1) {
        const staticRequests = staticUrls.map(url => ['GET', interpolateHarTemplate(url, harGlobalContext)]);
        const staticResponses = http.batch(staticRequests);
        
        // Record metrics for static files
        if (Array.isArray(staticResponses)) {
          staticResponses.forEach((response, index) => {
            harStaticFilesMetrics.add(response.timings.duration);
            if (harWorkflowConfig.logRequests) {
              console.log(`📁 Static file ${index + 1}: ${response.status} (${response.timings.duration}ms)`);
            }
          });
        }
      } else {
        // Sequential loading fallback
        staticUrls.forEach((url, index) => {
          const response = http.get(interpolateHarTemplate(url, harGlobalContext));
          harStaticFilesMetrics.add(response.timings.duration);
          if (harWorkflowConfig.logRequests) {
            console.log(`📁 Static file ${index + 1}: ${response.status} (${response.timings.duration}ms)`);
          }
        });
      }
      break;
      
    case 'distributed':
      // Distribute static file loading over time
      staticUrls.forEach((url, index) => {
        const response = http.get(interpolateHarTemplate(url, harGlobalContext));
        harStaticFilesMetrics.add(response.timings.duration);
        
        if (harWorkflowConfig.logRequests) {
          console.log(`📁 Static file ${index + 1}: ${response.status} (${response.timings.duration}ms)`);
        }
        
        // Small delay between static file requests
        if (index < staticUrls.length - 1) {
          sleep(Math.random() * 0.2); // 0-200ms random delay
        }
      });
      break;
      
    case 'realistic':
    default:
      // Use HAR timing data for realistic loading
      staticUrls.forEach((url, index) => {
        const response = http.get(interpolateHarTemplate(url, harGlobalContext));
        harStaticFilesMetrics.add(response.timings.duration);
        
        if (harWorkflowConfig.logRequests) {
          console.log(`📁 Static file ${index + 1}: ${response.status} (${response.timings.duration}ms)`);
        }
        
        // Use configured think time for realistic spacing
        if (index < staticUrls.length - 1) {
          sleep(staticFilesConfig.thinkTime || 0.1);
        }
      });
  }
}

/**
 * Execute HTTP request with HAR-specific parameters
 */
function executeHarRequest(method, url, payload, params) {
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
      throw new Error(`Unsupported HTTP method in HAR workflow: ${method}`);
  }
}

// Main HAR workflow execution function
export default function() {
  let harWorkflowSuccess = true;
  harStepResults = [];
  
  // Reset global context for each iteration
  harGlobalContext = {
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
  
  if (harWorkflowConfig.logRequests) {
    console.log(`🔄 Starting HAR workflow: ${harWorkflowConfig.name}`);
    console.log(`📊 HAR steps to execute: ${harWorkflowSteps.length}`);
    if (staticFilesConfig.enabled) {
      console.log(`🎨 Static files handling: ${staticFilesConfig.loadPattern} (max ${staticFilesConfig.maxPerPage} per page)`);
    }
  }
  
  for (let i = 0; i < harWorkflowSteps.length; i++) {
    const step = harWorkflowSteps[i];
    let stepStartTime = Date.now();
    
    if (harWorkflowConfig.logRequests) {
      console.log(`\\n🔄 Executing HAR step ${i + 1}/${harWorkflowSteps.length}: ${step.name} (${step.step_id})`);
    }
    
    // Check dependencies (if any)
    if (step.depends_on && step.depends_on.length > 0) {
      let dependenciesMet = true;
      for (const dependency of step.depends_on) {
        const depResult = harStepResults.find(r => r.step_id === dependency);
        if (!depResult || !depResult.success) {
          console.error(`❌ HAR step ${step.step_id} dependency ${dependency} not met`);
          dependenciesMet = false;
          break;
        }
      }
      
      if (!dependenciesMet) {
        harStepResults.push({
          step_id: step.step_id,
          name: step.name,
          success: false,
          status: 0,
          duration: 0,
          skipped: true,
          reason: 'Dependencies not met'
        });
        
        if (harWorkflowConfig.stopOnFailure) {
          harWorkflowSuccess = false;
          break;
        }
        continue;
      }
    }
    
    try {
      // Interpolate URL with current context
      const url = interpolateHarTemplate(step.url, harGlobalContext);
      
      // Build headers with HAR-specific processing
      const headers = {
        {{global_headers_block}}
        ...Object.fromEntries(
          Object.entries(step.headers || {}).map(([k, v]) => [
            k, 
            interpolateHarTemplate(v, harGlobalContext)
          ])
        )
      };
      
      // Add cookies if sharing is enabled (HAR workflow feature)
      if (harWorkflowConfig.shareCookies && Object.keys(harGlobalContext.cookies).length > 0) {
        const cookieString = Object.entries(harGlobalContext.cookies)
          .map(([name, value]) => `${name}=${value}`)
          .join('; ');
        headers['Cookie'] = cookieString;
      }
      
      const params = {
        headers: headers,
        timeout: step.timeout || '30s'
      };
      
      // Handle payload with template interpolation
      let payload = null;
      if (step.payload && ['POST', 'PUT', 'PATCH'].includes(step.method.toUpperCase())) {
        if (typeof step.payload === 'object') {
          // Interpolate object payload
          payload = JSON.stringify(
            Object.fromEntries(
              Object.entries(step.payload).map(([k, v]) => [
                k,
                typeof v === 'string' ? interpolateHarTemplate(v, harGlobalContext) : v
              ])
            )
          );
        } else {
          payload = interpolateHarTemplate(String(step.payload), harGlobalContext);
        }
      }
      
      if (harWorkflowConfig.logRequests) {
        console.log(`📤 ${step.method} ${url}`);
        if (payload) {
          console.log(`📦 Payload: ${payload.substring(0, 200)}${payload.length > 200 ? '...' : ''}`);
        }
      }
      
      // Execute the HAR-derived request
      const response = executeHarRequest(step.method, url, payload, params);
      
      if (harWorkflowConfig.logRequests) {
        console.log(`📥 Response: ${response.status} (${response.timings.duration}ms)`);
      }
      
      // Store response in global context
      harGlobalContext.response[step.step_id] = {
        status: response.status,
        body: response.body,
        json: () => response.json(),
        headers: response.headers
      };
      
      // Extract variables from response
      const extractedVars = extractHarVariables(response, step.extract_variables, step.step_id);
      
      // Extract cookies if enabled
      if (step.extract_cookies && response.headers['Set-Cookie']) {
        const setCookieHeaders = Array.isArray(response.headers['Set-Cookie']) 
          ? response.headers['Set-Cookie'] 
          : [response.headers['Set-Cookie']];
        
        for (const cookieHeader of setCookieHeaders) {
          const cookieParts = cookieHeader.split(';');
          const nameValue = cookieParts[0].trim();
          
          if (nameValue.includes('=')) {
            const [name, value] = nameValue.split('=', 2);
            harGlobalContext.cookies[name.trim()] = value.trim();
            
            if (harWorkflowConfig.logRequests) {
              console.log(`🍪 HAR: Extracted cookie ${name}`);
            }
          }
        }
      }
      
      // Record metrics
      harStepResponseTimes.add(response.timings.duration, {
        step_id: step.step_id,
        step_name: step.name
      });
      
      // Check if request was successful
      const isSuccess = response.status >= 200 && response.status < 400;
      
      if (isSuccess) {
        harStepSuccessCounter.add(1, { step_id: step.step_id });
      } else {
        harStepErrorCounter.add(1, { 
          step_id: step.step_id, 
          status_code: response.status 
        });
        
        if (harWorkflowConfig.stopOnFailure) {
          console.error(`❌ HAR step ${step.step_id} failed with status ${response.status}`);
          harWorkflowSuccess = false;
        }
      }
      
      // Record step result
      harStepResults.push({
        step_id: step.step_id,
        name: step.name,
        success: isSuccess,
        status: response.status,
        duration: response.timings.duration,
        extracted_variables: extractedVars,
        url: url // Record the interpolated URL
      });
      
      // Handle static files if this is a page request and static files are enabled
      if (staticFilesConfig.enabled && 
          (step.static_files && step.static_files.length > 0)) {
        
        if (harWorkflowConfig.logRequests) {
          console.log(`🎨 Processing ${step.static_files.length} static files for ${step.name}`);
        }
        
        processHarStaticFiles(
          step.static_files, 
          staticFilesConfig.loadPattern,
          staticFilesConfig.parallelLoading
        );
      }
      
    } catch (error) {
      console.error(`❌ HAR step ${step.step_id} failed with error: ${error.message}`);
      
      harStepErrorCounter.add(1, { 
        step_id: step.step_id, 
        error_type: error.name 
      });
      
      harStepResults.push({
        step_id: step.step_id,
        name: step.name,
        success: false,
        status: 0,
        duration: Date.now() - stepStartTime,
        error: error.message
      });
      
      if (harWorkflowConfig.stopOnFailure) {
        harWorkflowSuccess = false;
        break;
      }
    }
    
    // Think time between HAR steps
    if (i < harWorkflowSteps.length - 1 && step.think_time > 0) {
      sleep(step.think_time);
    }
  }
  
  // Final HAR workflow summary
  const successfulSteps = harStepResults.filter(r => r.success).length;
  const failedSteps = harStepResults.filter(r => !r.success).length;
  const workflowSuccess = failedSteps === 0 && harWorkflowSuccess;
  
  if (harWorkflowConfig.logRequests) {
    console.log(`\\n📊 HAR Workflow Summary: ${harWorkflowConfig.name}`);
    console.log(`✅ Successful steps: ${successfulSteps}`);
    console.log(`❌ Failed steps: ${failedSteps}`);
    console.log(`📈 Overall workflow success: ${workflowSuccess ? 'YES' : 'NO'}`);
    
    if (staticFilesConfig.enabled) {
      console.log(`🎨 Static files processed with ${staticFilesConfig.loadPattern} pattern`);
    }
  }
  
  if (workflowSuccess) {
    harWorkflowSuccessCounter.add(1);
  }
}

// HAR workflow summary handler
export function handleSummary(data) {
  console.log('📊 Generating HAR workflow test report...');
  
  const harWorkflowSummary = {
    workflow_name: harWorkflowConfig.name,
    workflow_type: "HAR-based Multi-Request Workflow",
    static_files_enabled: staticFilesConfig.enabled,
    static_files_pattern: staticFilesConfig.enabled ? staticFilesConfig.loadPattern : null,
    total_steps: harWorkflowSteps.length,
    step_results: harStepResults,
    overall_metrics: {
      total_requests: data.metrics.http_reqs?.values?.count || 0,
      avg_response_time: data.metrics.http_req_duration?.values?.avg || 0,
      p95_response_time: data.metrics.http_req_duration?.values['p(95)'] || 0,
      error_rate: (data.metrics.http_req_failed?.values?.rate || 0) * 100,
      workflow_success_rate: (data.metrics.har_workflow_success?.values?.count || 0)
    },
    extracted_variables: harGlobalContext.extractedVariables,
    static_files_metrics: staticFilesConfig.enabled ? {
      avg_static_response_time: data.metrics.har_static_files_response_times?.values?.avg || 0,
      total_static_requests: data.metrics.har_static_files_response_times?.values?.count || 0
    } : null,
    generated_at: new Date().toISOString()
  };
  
  const htmlReport = `<!DOCTYPE html>
<html>
<head>
  <title>HAR Workflow Test Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
    .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    .header { background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
    .step { margin: 15px 0; padding: 20px; border-radius: 8px; border-left: 5px solid #ccc; }
    .success { background: #d4edda; border-left-color: #28a745; }
    .failed { background: #f8d7da; border-left-color: #dc3545; }
    .variables { background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 5px solid #ffc107; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
    .metric-box { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #e9ecef; }
    .metric-value { font-size: 24px; font-weight: bold; color: #495057; }
    .static-info { background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 5px solid #2196f3; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🔄 HAR Workflow Test Report</h1>
      <p><strong>Workflow:</strong> ${harWorkflowSummary.workflow_name}</p>
      <p><strong>Type:</strong> ${harWorkflowSummary.workflow_type}</p>
      <p>Generated: ${harWorkflowSummary.generated_at}</p>
    </div>
    
    <div class="metrics">
      <div class="metric-box">
        <h3>Total Steps</h3>
        <div class="metric-value">${harWorkflowSummary.total_steps}</div>
      </div>
      <div class="metric-box">
        <h3>Success Rate</h3>
        <div class="metric-value">${harStepResults.filter(r => r.success).length}/${harStepResults.length}</div>
      </div>
      <div class="metric-box">
        <h3>Total Requests</h3>
        <div class="metric-value">${harWorkflowSummary.overall_metrics.total_requests}</div>
      </div>
      <div class="metric-box">
        <h3>Avg Response Time</h3>
        <div class="metric-value">${Math.round(harWorkflowSummary.overall_metrics.avg_response_time)}ms</div>
      </div>
    </div>
    
    ${staticFilesConfig.enabled ? `
    <div class="static-info">
      <h3>🎨 Static Files Configuration</h3>
      <p><strong>Load Pattern:</strong> ${staticFilesConfig.loadPattern}</p>
      <p><strong>Parallel Loading:</strong> ${staticFilesConfig.parallelLoading ? 'Yes' : 'No'}</p>
      ${harWorkflowSummary.static_files_metrics ? `
      <p><strong>Static Files Processed:</strong> ${harWorkflowSummary.static_files_metrics.total_static_requests}</p>
      <p><strong>Avg Static Response Time:</strong> ${Math.round(harWorkflowSummary.static_files_metrics.avg_static_response_time)}ms</p>
      ` : ''}
    </div>
    ` : ''}
    
    <div class="variables">
      <h3>🔧 Extracted Variables</h3>
      ${Object.entries(harGlobalContext.extractedVariables).map(([key, value]) => {
        const displayValue = String(value).length > 50 ? String(value).substring(0, 50) + '...' : value;
        return `<p><strong>${key}:</strong> ${displayValue}</p>`;
      }).join('')}
    </div>
    
    <h2>📋 HAR Steps Results</h2>
    ${harStepResults.map((step, index) => `
      <div class="step ${step.success ? 'success' : 'failed'}">
        <h3>${step.success ? '✅' : '❌'} Step ${index + 1}: ${step.name}</h3>
        <p><strong>Step ID:</strong> ${step.step_id}</p>
        <p><strong>Status:</strong> ${step.status}</p>
        <p><strong>Duration:</strong> ${step.duration}ms</p>
        ${step.url ? `<p><strong>URL:</strong> ${step.url}</p>` : ''}
        ${step.error ? `<p><strong>Error:</strong> ${step.error}</p>` : ''}
        ${step.extracted_variables && Object.keys(step.extracted_variables).length > 0 ? 
          `<p><strong>Variables Extracted:</strong> ${Object.keys(step.extracted_variables).join(', ')}</p>` : ''}
      </div>
    `).join('')}
  </div>
</body>
</html>`;
  
  return {
    [`har_workflow_${harWorkflowConfig.name}_report.html`]: htmlReport,
    [`har_workflow_${harWorkflowConfig.name}_summary.json`]: JSON.stringify(harWorkflowSummary, null, 2),
    stdout: `
🔄 HAR Workflow Test Results: ${harWorkflowConfig.name}
${'='.repeat(60)}

📊 Workflow Summary:
• Total Steps: ${harStepResults.length}
• Successful Steps: ${harStepResults.filter(r => r.success).length}
• Failed Steps: ${harStepResults.filter(r => !r.success).length}
• Average Response Time: ${Math.round(harWorkflowSummary.overall_metrics.avg_response_time)}ms

${staticFilesConfig.enabled ? `
🎨 Static Files Summary:
• Load Pattern: ${staticFilesConfig.loadPattern}
• Parallel Loading: ${staticFilesConfig.parallelLoading ? 'Enabled' : 'Disabled'}
• Static Requests: ${harWorkflowSummary.static_files_metrics?.total_static_requests || 0}
` : ''}

🔧 Variables Extracted:
${Object.entries(harGlobalContext.extractedVariables).map(([key, value]) => {
  const displayValue = String(value).length > 30 ? String(value).substring(0, 30) + '...' : value;
  return `• ${key}: ${displayValue}`;
}).join('\\n')}

📋 Step Details:
${harStepResults.map(r => 
  `${r.success ? '✅' : '❌'} ${r.name}: ${r.status} (${r.duration}ms)`
).join('\\n')}
`,
  };
}