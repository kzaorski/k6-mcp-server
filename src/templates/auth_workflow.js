import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

// Authentication-specific metrics
const loginResponseTime = new Trend('auth_login_duration');
const tokenExtractionCounter = new Counter('auth_token_extractions');
const authFailureCounter = new Counter('auth_failures');
const protectedResourceCounter = new Counter('auth_protected_access');

// Fallback HTML report for auth workflows
function authHtmlReport(data) {
  const metrics = data.metrics || {};
  const loginDuration = metrics.auth_login_duration?.values || {};
  const tokenExtractions = metrics.auth_token_extractions?.values || {};
  const authFailures = metrics.auth_failures?.values || {};
  
  return `<!DOCTYPE html>
<html>
<head>
  <title>K6 Authentication Workflow Report</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    .header { background: #e8f4f8; padding: 15px; border-radius: 5px; border-left: 4px solid #007acc; }
    .auth-step { margin: 15px 0; padding: 15px; border-radius: 5px; }
    .login-step { background: #fff3cd; border-left: 4px solid #ffc107; }
    .token-step { background: #d4edda; border-left: 4px solid #28a745; }
    .protected-step { background: #cce5ff; border-left: 4px solid #007bff; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }
    .metric-box { padding: 15px; background: #f8f9fa; border-radius: 8px; text-align: center; }
    .metric-value { font-size: 24px; font-weight: bold; color: #007acc; }
  </style>
</head>
<body>
  <div class="header">
    <h1>🔐 Authentication Workflow Report</h1>
    <p><strong>Workflow:</strong> {{workflow_name}}</p>
    <p><strong>Generated:</strong> ${new Date().toISOString()}</p>
  </div>
  
  <div class="metrics">
    <div class="metric-box">
      <h3>🔑 Login Success Rate</h3>
      <div class="metric-value">${Math.round(((tokenExtractions.count || 0) / Math.max(1, (tokenExtractions.count || 0) + (authFailures.count || 0))) * 100)}%</div>
    </div>
    <div class="metric-box">
      <h3>⏱️ Avg Login Time</h3>
      <div class="metric-value">${Math.round(loginDuration.avg || 0)}ms</div>
    </div>
    <div class="metric-box">
      <h3>🎫 Tokens Extracted</h3>
      <div class="metric-value">${tokenExtractions.count || 0}</div>
    </div>
    <div class="metric-box">
      <h3>❌ Auth Failures</h3>
      <div class="metric-value">${authFailures.count || 0}</div>
    </div>
  </div>

  <h2>Authentication Flow Steps</h2>
  <div class="login-step">
    <h3>🔐 Step 1: User Login</h3>
    <p>Authenticate user and extract access tokens</p>
  </div>
  <div class="token-step">
    <h3>🎫 Step 2: Token Validation</h3>
    <p>Verify extracted tokens and session data</p>
  </div>
  <div class="protected-step">
    <h3>🛡️ Step 3: Protected Resource Access</h3>
    <p>Access protected resources using authentication</p>
  </div>
</body>
</html>`;
}

// Specialized auth workflow text summary
function authTextSummary(data) {
  const metrics = data.metrics || {};
  const loginDuration = metrics.auth_login_duration?.values || {};
  const tokenExtractions = metrics.auth_token_extractions?.values || {};
  const authFailures = metrics.auth_failures?.values || {};
  const protectedAccess = metrics.auth_protected_access?.values || {};
  
  const loginSuccessRate = Math.round(((tokenExtractions.count || 0) / Math.max(1, (tokenExtractions.count || 0) + (authFailures.count || 0))) * 100);
  
  return `
🔐 K6 Authentication Workflow Results:
=====================================
Workflow: {{workflow_name}}
Authentication Type: {{auth_type}}

📊 Authentication Metrics:
• Login Success Rate: ${loginSuccessRate}%
• Avg Login Time: ${Math.round(loginDuration.avg || 0)}ms
• Tokens Extracted: ${tokenExtractions.count || 0}
• Authentication Failures: ${authFailures.count || 0}
• Protected Resource Access: ${protectedAccess.count || 0}

🔒 Security Validation:
• Token Format Validation: ${tokenExtractions.count > 0 ? 'PASSED' : 'FAILED'}
• Session Management: {{share_cookies}}
• Auth Header Propagation: ENABLED
`;
}

export const options = {
  vus: {{virtual_users}},
  {{execution_mode_block}}
  {{thresholds_block}}
};

// Authentication workflow configuration
const authConfig = {
  workflow_name: "{{workflow_name}}",
  auth_type: "{{auth_type}}", // oauth, basic, api_key, jwt
  login_endpoint: "{{login_endpoint}}",
  protected_endpoints: {{protected_endpoints_json}},
  token_extraction: {{token_extraction_config}},
  session_management: {{share_cookies}}
};

// Authentication state
let authState = {
  isAuthenticated: false,
  accessToken: null,
  refreshToken: null,
  sessionCookies: {},
  userId: null,
  tokenType: 'Bearer',
  expiresAt: null
};

// Global context for auth workflow
let globalContext = {
  auth: authState,
  cookies: {},
  response: {},
  extractedVariables: {}
};

// Step results for detailed reporting
let stepResults = [];

// Authentication utility functions

function extractAuthTokens(response, extractionConfig) {
  const tokens = {};
  
  try {
    const responseBody = response.json();
    
    // Extract access token
    if (extractionConfig.access_token_path) {
      tokens.access_token = extractJsonPath(responseBody, extractionConfig.access_token_path);
    }
    
    // Extract refresh token
    if (extractionConfig.refresh_token_path) {
      tokens.refresh_token = extractJsonPath(responseBody, extractionConfig.refresh_token_path);
    }
    
    // Extract user ID
    if (extractionConfig.user_id_path) {
      tokens.user_id = extractJsonPath(responseBody, extractionConfig.user_id_path);
    }
    
    // Extract token type
    if (extractionConfig.token_type_path) {
      tokens.token_type = extractJsonPath(responseBody, extractionConfig.token_type_path);
    }
    
    // Extract expiry information
    if (extractionConfig.expires_in_path) {
      const expiresIn = extractJsonPath(responseBody, extractionConfig.expires_in_path);
      if (expiresIn) {
        tokens.expires_at = Date.now() + (expiresIn * 1000);
      }
    }
    
    return tokens;
    
  } catch (error) {
    console.error('❌ Failed to extract auth tokens:', error);
    return {};
  }
}

function extractJsonPath(data, path) {
  if (!path.startsWith('$.')) {
    return data[path]; // Simple key access
  }
  
  const pathParts = path.substring(2).split('.');
  let current = data;
  
  for (const part of pathParts) {
    if (part.includes('[') && part.includes(']')) {
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
      if (current && typeof current === 'object' && part in current) {
        current = current[part];
      } else {
        return undefined;
      }
    }
  }
  
  return current;
}

function buildAuthHeaders(authState) {
  const headers = {
    'Content-Type': 'application/json'
  };
  
  if (authState.isAuthenticated && authState.accessToken) {
    headers['Authorization'] = `${authState.tokenType} ${authState.accessToken}`;
  }
  
  return headers;
}

function validateToken(token) {
  if (!token || typeof token !== 'string') {
    return false;
  }
  
  // Basic token format validation
  if (token.length < 10) {
    return false;
  }
  
  // JWT token validation (basic)
  if (token.includes('.') && token.split('.').length === 3) {
    return true; // Looks like JWT
  }
  
  // OAuth/API token validation (basic)
  if (token.length >= 20 && /^[A-Za-z0-9_-]+$/.test(token)) {
    return true;
  }
  
  return false;
}

function isTokenExpired(authState) {
  if (!authState.expiresAt) {
    return false; // No expiry info, assume valid
  }
  
  return Date.now() >= authState.expiresAt;
}

// Main authentication workflow
export default function() {
  let workflowSuccess = true;
  stepResults = [];
  
  // Reset auth state for each iteration
  authState = {
    isAuthenticated: false,
    accessToken: null,
    refreshToken: null,
    sessionCookies: {},
    userId: null,
    tokenType: 'Bearer',
    expiresAt: null
  };
  
  globalContext = {
    auth: authState,
    cookies: {},
    response: {},
    extractedVariables: {},
    timestamp: Math.floor(Date.now() / 1000),
    current_timestamp: new Date().toISOString()
  };
  
  console.log('🔐 Starting authentication workflow:', authConfig.workflow_name);
  
  // Step 1: User Login/Authentication
  const loginStartTime = Date.now();
  
  try {
    console.log('🔑 Step 1: User Authentication');
    
    const loginPayload = {
      email: "{{user_email}}",
      password: "{{user_password}}",
      username: "{{username}}",
      grant_type: "{{grant_type}}"
    };
    
    const loginHeaders = {
      'Content-Type': 'application/json',
      {{global_headers_block}}
    };
    
    // Remove undefined values from payload
    Object.keys(loginPayload).forEach(key => {
      if (loginPayload[key] === undefined || typeof loginPayload[key] === 'string' && loginPayload[key].includes('{{')) {
        delete loginPayload[key];
      }
    });
    
    const loginResponse = http.post(authConfig.login_endpoint, JSON.stringify(loginPayload), {
      headers: loginHeaders,
      timeout: '30s'
    });
    
    const loginDuration = Date.now() - loginStartTime;
    loginResponseTime.add(loginResponse.timings.duration);
    
    console.log(`📥 Login response: ${loginResponse.status} (${loginResponse.timings.duration}ms)`);
    
    if (loginResponse.status >= 200 && loginResponse.status < 300) {
      // Extract authentication tokens
      const tokens = extractAuthTokens(loginResponse, authConfig.token_extraction);
      
      if (tokens.access_token && validateToken(tokens.access_token)) {
        authState.isAuthenticated = true;
        authState.accessToken = tokens.access_token;
        authState.refreshToken = tokens.refresh_token;
        authState.userId = tokens.user_id;
        authState.tokenType = tokens.token_type || 'Bearer';
        authState.expiresAt = tokens.expires_at;
        
        tokenExtractionCounter.add(1);
        
        console.log('✅ Authentication successful');
        console.log(`🎫 Access token extracted: ${tokens.access_token.substring(0, 20)}...`);
        
        if (tokens.user_id) {
          console.log(`👤 User ID: ${tokens.user_id}`);
        }
        
        // Store in global context
        globalContext.auth = authState;
        globalContext.response.login = {
          status: loginResponse.status,
          body: loginResponse.json(),
          headers: loginResponse.headers,
          extracted: tokens
        };
        
        stepResults.push({
          step_id: 'login',
          name: 'User Authentication',
          success: true,
          status: loginResponse.status,
          duration: loginDuration,
          response_time: loginResponse.timings.duration,
          extracted_variables: tokens
        });
        
      } else {
        authFailureCounter.add(1);
        workflowSuccess = false;
        
        console.error('❌ Token extraction failed - invalid or missing token');
        
        stepResults.push({
          step_id: 'login',
          name: 'User Authentication',
          success: false,
          status: loginResponse.status,
          duration: loginDuration,
          error: 'Token extraction failed'
        });
      }
    } else {
      authFailureCounter.add(1);
      workflowSuccess = false;
      
      console.error(`❌ Login failed with status: ${loginResponse.status}`);
      
      stepResults.push({
        step_id: 'login',
        name: 'User Authentication',
        success: false,
        status: loginResponse.status,
        duration: loginDuration,
        error: `HTTP ${loginResponse.status}`
      });
    }
    
  } catch (error) {
    const loginDuration = Date.now() - loginStartTime;
    authFailureCounter.add(1);
    workflowSuccess = false;
    
    console.error('❌ Login request failed:', error.message);
    
    stepResults.push({
      step_id: 'login',
      name: 'User Authentication',
      success: false,
      status: 0,
      duration: loginDuration,
      error: error.message
    });
  }
  
  // Only proceed if authentication was successful
  if (!authState.isAuthenticated || {{stop_on_failure}}) {
    if (!authState.isAuthenticated && {{stop_on_failure}}) {
      console.error('🛑 Stopping workflow - authentication required but failed');
      return;
    }
  }
  
  sleep(1); // Think time between authentication and resource access
  
  // Step 2: Access Protected Resources
  if (authState.isAuthenticated && authConfig.protected_endpoints.length > 0) {
    console.log('🛡️ Step 2: Accessing Protected Resources');
    
    for (let i = 0; i < authConfig.protected_endpoints.length; i++) {
      const endpoint = authConfig.protected_endpoints[i];
      const resourceStartTime = Date.now();
      
      try {
        // Check if token is expired
        if (isTokenExpired(authState)) {
          console.warn('⚠️ Access token expired - attempting to use anyway');
        }
        
        const resourceUrl = endpoint.url.replace('{{user_id}}', authState.userId || 'unknown');
        const authHeaders = buildAuthHeaders(authState);
        
        // Add any endpoint-specific headers
        if (endpoint.headers) {
          Object.assign(authHeaders, endpoint.headers);
        }
        
        console.log(`📤 ${endpoint.method || 'GET'} ${resourceUrl}`);
        
        const resourceResponse = http.request(endpoint.method || 'GET', resourceUrl, null, {
          headers: authHeaders,
          timeout: '30s'
        });
        
        const resourceDuration = Date.now() - resourceStartTime;
        
        console.log(`📥 Resource response: ${resourceResponse.status} (${resourceResponse.timings.duration}ms)`);
        
        if (resourceResponse.status >= 200 && resourceResponse.status < 300) {
          protectedResourceCounter.add(1, { 
            endpoint: endpoint.name || resourceUrl,
            status: 'success'
          });
          
          console.log(`✅ Successfully accessed: ${endpoint.name || resourceUrl}`);
          
          stepResults.push({
            step_id: `protected_${i}`,
            name: `Access ${endpoint.name || 'Protected Resource'}`,
            success: true,
            status: resourceResponse.status,
            duration: resourceDuration,
            response_time: resourceResponse.timings.duration
          });
          
        } else if (resourceResponse.status === 401) {
          console.error('❌ Authentication failed - token may be invalid or expired');
          
          stepResults.push({
            step_id: `protected_${i}`,
            name: `Access ${endpoint.name || 'Protected Resource'}`,
            success: false,
            status: resourceResponse.status,
            duration: resourceDuration,
            error: 'Authentication failed (401)'
          });
          
          if ({{stop_on_failure}}) {
            workflowSuccess = false;
            break;
          }
          
        } else {
          console.error(`❌ Resource access failed: ${resourceResponse.status}`);
          
          stepResults.push({
            step_id: `protected_${i}`,
            name: `Access ${endpoint.name || 'Protected Resource'}`,
            success: false,
            status: resourceResponse.status,
            duration: resourceDuration,
            error: `HTTP ${resourceResponse.status}`
          });
          
          if ({{stop_on_failure}}) {
            workflowSuccess = false;
            break;
          }
        }
        
      } catch (error) {
        const resourceDuration = Date.now() - resourceStartTime;
        
        console.error(`❌ Resource request failed: ${error.message}`);
        
        stepResults.push({
          step_id: `protected_${i}`,
          name: `Access ${endpoint.name || 'Protected Resource'}`,
          success: false,
          status: 0,
          duration: resourceDuration,
          error: error.message
        });
        
        if ({{stop_on_failure}}) {
          workflowSuccess = false;
          break;
        }
      }
      
      sleep(0.5); // Short think time between resource accesses
    }
  }
  
  // Final workflow summary
  const successfulSteps = stepResults.filter(r => r.success).length;
  const failedSteps = stepResults.filter(r => !r.success).length;
  
  console.log('\n📊 Authentication Workflow Summary:');
  console.log(`🔐 Authentication: ${authState.isAuthenticated ? 'SUCCESS' : 'FAILED'}`);
  console.log(`✅ Successful steps: ${successfulSteps}`);
  console.log(`❌ Failed steps: ${failedSteps}`);
  console.log(`📈 Overall workflow success: ${workflowSuccess ? 'YES' : 'NO'}`);
  
  if (authState.isAuthenticated) {
    console.log(`🎫 Token type: ${authState.tokenType}`);
    console.log(`⏰ Token expires: ${authState.expiresAt ? new Date(authState.expiresAt).toISOString() : 'Unknown'}`);
  }
}

// K6 handleSummary callback for auth workflows
export function handleSummary(data) {
  console.log('📊 Generating authentication workflow reports...');
  
  try {
    const htmlContent = authHtmlReport(data);
    const textContent = authTextSummary(data);
    
    // Enhanced auth workflow summary
    const authWorkflowSummary = {
      workflow_name: authConfig.workflow_name,
      auth_type: authConfig.auth_type,
      authentication_metrics: {
        login_success_rate: ((data.metrics.auth_token_extractions?.values?.count || 0) / Math.max(1, (data.metrics.auth_token_extractions?.values?.count || 0) + (data.metrics.auth_failures?.values?.count || 0))) * 100,
        avg_login_time: data.metrics.auth_login_duration?.values?.avg || 0,
        tokens_extracted: data.metrics.auth_token_extractions?.values?.count || 0,
        auth_failures: data.metrics.auth_failures?.values?.count || 0,
        protected_access_count: data.metrics.auth_protected_access?.values?.count || 0
      },
      step_results: stepResults,
      generated_at: new Date().toISOString()
    };
    
    console.log('✅ Authentication workflow reports generated successfully');
    
    return {
      // Professional HTML report for auth workflow
      'reports/{{test_id}}_auth_workflow_report.html': htmlContent,
      
      // Authentication workflow summary
      'reports/{{test_id}}_auth_summary.json': JSON.stringify(authWorkflowSummary, null, 2),
      
      // Complete raw K6 data
      'reports/{{test_id}}_detailed_summary.json': JSON.stringify(data, null, 2),
      
      // Enhanced console output
      stdout: textContent + `\n\nAuthentication Steps:\n${stepResults.map(r => 
        `${r.success ? '✅' : '❌'} ${r.name}: ${r.status} (${r.duration}ms)`
      ).join('\n')}`,
    };
  } catch (error) {
    console.error('❌ Error in auth workflow handleSummary():', error.message);
    
    return {
      'reports/{{test_id}}_auth_error.txt': `Error in auth handleSummary(): ${error.message}\nAuth Type: ${authConfig.auth_type}`,
      stdout: `Error generating auth workflow reports: ${error.message}`,
    };
  }
}