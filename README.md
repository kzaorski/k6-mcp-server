# K6 MCP Server

MCP (Model Context Protocol) server for running K6 performance tests through Claude Code.

## Features

- 🚀 Run K6 performance tests with precise **iterations** or **duration** control
- 📊 Support for different load patterns (constant, ramp-up, spike) with resilience assessment
- 📈 **Multi-format reporting**: JSON (detailed), HTML (with charts), CSV (detailed analysis)
- 🔧 Easy integration with Claude Code/Desktop via Model Context Protocol (MCP)
- 🔐 Advanced HTTP authentication (Bearer, Basic, API Key)
- 🍪 Cookie and custom header support
- 🎲 Dynamic data generation and templating with variable substitution
- 📁 CSV/JSON data file loading
- ⚡ Retry logic and timeout configuration
- 🌐 Environment variable support
- ✅ **Accurate error detection** and detailed failure analysis
- 🛡️ **AI Safety Features**: Prevents autonomous test execution and configuration changes
- 📊 **Professional HTML reports** with charts via k6-reporter integration
- 📊 **Standard K6 reporting** with comprehensive metrics and analysis

## Prerequisites

- Python 3.10 or higher
- K6 installed and available in PATH
- MCP SDK 1.2.0 or higher

## Installation

1. Install K6:
```bash
# macOS (using Homebrew)
brew install k6

# Ubuntu/Debian
sudo apt update
sudo apt install k6

# Windows (using Chocolatey)
choco install k6
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Available Tools

#### 1. `run_k6_test`
Run a K6 performance test with specified parameters.

**Parameters:**

**Basic Parameters:**
- `url` (required): The endpoint URL to test
- `method` (optional): HTTP method (GET, POST, PUT, DELETE, PATCH) - default: GET
- `payload` (optional): JSON payload for POST/PUT requests
- `load_pattern` (optional): Load testing pattern - default: constant
  - `constant`: Maintains steady number of virtual users
  - `ramp_up`: Gradually increases virtual users
  - `spike`: Sudden traffic spikes
- `duration` (optional): Test duration (e.g., '30s', '5m') - default: 30s - **ignored if iterations is set**
- `iterations` (optional): **NEW** - Number of iterations to run (overrides duration for precise request counting)
- `virtual_users` (optional): Number of virtual users - default: 10
- `thresholds` (optional): Performance thresholds

**Advanced HTTP Parameters:**
- `headers` (optional): Custom HTTP headers as key-value pairs
- `auth` (optional): Authentication configuration
  - `type`: "bearer", "basic", or "apikey"
  - `token`: Bearer token or API key value
  - `username`/`password`: For basic auth
  - `header_name`: Custom header name for API key
- `cookies` (optional): HTTP cookies as key-value pairs
- `query_params` (optional): URL query parameters
- `timeout` (optional): Request timeout - default: 30s
- `retry_attempts` (optional): Number of retry attempts - default: 0

**Dynamic Data Parameters:**
- `env_variables` (optional): Environment variables for K6 script
- `data_generators` (optional): Dynamic data generator configuration
  - Supported types: `uuid`, `string`, `number`, `timestamp`, `email`, `choice`
- `data_file` (optional): Path to CSV/JSON data file
- `payload_template` (optional): Dynamic payload template with `{{variable}}` placeholders

**Example:**
```json
{
  "url": "https://api.example.com/users",
  "method": "GET",
  "load_pattern": "ramp_up",
  "duration": "2m",
  "virtual_users": 50,
  "thresholds": {
    "http_req_duration": "p(95)<500",
    "http_req_failed": "rate<0.1"
  }
}
```

#### 2. `get_test_results`
Get results from the last K6 test run or a specific test.

**Parameters:**
- `test_id` (optional): Specific test ID to get results for

#### 3. `list_test_templates`
List available K6 test templates and their descriptions.

#### 4. `get_standard_html_report` ⭐ **NEW**
Access professional HTML reports with charts and visual metrics.

#### 5. `generate_detailed_report` ⭐ **NEW**
Generate detailed CSV reports for chart generation and analysis.

### Load Patterns

#### Constant Load
- Maintains a steady number of virtual users throughout the test
- Good for baseline performance testing
- Use when you want to test sustained load

#### Ramp-up Load
- Gradually increases virtual users over time
- Includes ramp-up, steady state, and ramp-down phases
- Good for finding performance breaking points

#### Spike Load
- Creates sudden traffic spikes
- Tests system resilience under stress
- Useful for testing auto-scaling capabilities

## Claude Desktop Configuration

Add this configuration to your Claude Desktop settings:

```json
{
  "mcpServers": {
    "k6-performance-testing": {
      "command": "python",
      "args": ["/path/to/k6-mcp-server/src/server.py"],
      "env": {}
    }
  }
}
```

## Example Test Scenarios

### Single Request Test (Precise Control) ⭐ **NEW**
```json
{
  "url": "https://api.example.com/health",
  "method": "GET",
  "iterations": 1,
  "virtual_users": 1
}
```

### Basic API Endpoint Test
```json
{
  "url": "https://api.example.com/health",
  "method": "GET",
  "duration": "1m",
  "virtual_users": 10
}
```

### Authenticated API Test with Custom Headers
```json
{
  "url": "https://api.example.com/users",
  "method": "GET",
  "headers": {
    "X-API-Version": "v1",
    "X-Client-ID": "test-client"
  },
  "auth": {
    "type": "bearer",
    "token": "your-jwt-token-here"
  },
  "timeout": "60s",
  "retry_attempts": 2,
  "duration": "2m",
  "virtual_users": 20
}
```

### POST Request with Dynamic Data
```json
{
  "url": "https://api.example.com/users",
  "method": "POST",
  "payload_template": "{\"user_id\": \"{{user_id}}\", \"name\": \"{{username}}\", \"email\": \"{{email}}\", \"timestamp\": \"{{created_at}}\"}",
  "data_generators": {
    "user_id": {"type": "uuid"},
    "username": {"type": "string", "length": 8},
    "email": {"type": "email", "domain": "example.com"},
    "created_at": {"type": "timestamp"}
  },
  "headers": {
    "Content-Type": "application/json"
  },
  "auth": {
    "type": "apikey",
    "token": "your-api-key",
    "header_name": "X-API-Key"
  },
  "load_pattern": "ramp_up",
  "duration": "3m",
  "virtual_users": 25
}
```

### Cookie-based Session Test
```json
{
  "url": "https://app.example.com/api/dashboard",
  "method": "GET",
  "cookies": {
    "session_id": "abc123xyz789",
    "user_preferences": "theme=dark&lang=en"
  },
  "query_params": {
    "include": "stats",
    "format": "json"
  },
  "duration": "5m",
  "virtual_users": 50
}
```

### Load Test with CSV Data
```json
{
  "url": "https://api.example.com/orders",
  "method": "POST",
  "data_file": "/path/to/test-data.csv",
  "headers": {
    "Content-Type": "application/json"
  },
  "auth": {
    "type": "basic",
    "username": "testuser",
    "password": "testpass"
  },
  "load_pattern": "constant",
  "duration": "10m",
  "virtual_users": 100
}
```

### Stress Test with Environment Variables
```json
{
  "url": "https://api.example.com/data",
  "method": "GET",
  "env_variables": {
    "BASE_URL": "https://api.example.com",
    "API_VERSION": "v2",
    "TEST_ENV": "$NODE_ENV"
  },
  "load_pattern": "spike",
  "duration": "5m",
  "virtual_users": 200,
  "thresholds": {
    "http_req_duration": "p(95)<1000",
    "http_req_failed": "rate<0.05",
    "http_reqs": "rate>50"
  }
}
```

## Output Metrics & Reporting ⭐ **ENHANCED**

The server provides comprehensive performance metrics in multiple formats:

### Detailed Metrics
- **Response Times**: Average, minimum, maximum, 50th, 90th, 95th, and 99th percentiles
- **Throughput**: Requests per second and total requests
- **Error Analysis**: Detailed error breakdown with status codes and failure patterns
- **Data Transfer**: Amount of data sent and received
- **Test Duration**: Actual test execution time
- **Virtual Users**: Maximum concurrent users
- **Quality Assessment**: Automated A-F performance grading

### Report Formats
1. **LLM-Optimized JSON**: Structured data perfect for AI analysis
2. **Professional HTML**: Visual reports with charts (k6-reporter integration)
3. **Detailed JSON**: Complete K6 raw data with all metrics
4. **CSV Exports**: Detailed metrics for spreadsheet analysis

### AI Safety Features ⭐ **NEW**
- **Accurate Error Detection**: Based on actual metrics, not process exit codes
- **No Autonomous Execution**: Prevents AI from running tests without explicit user request
- **Transparent Reporting**: All performance issues clearly communicated
- **No Configuration Changes**: Failed tests reported accurately without suggesting test modifications

## Advanced Features

### Data Generators
The server supports dynamic data generation with the following types:

- **`uuid`**: Generates UUID4 strings
- **`string`**: Random alphanumeric strings with configurable length
- **`number`**: Random numbers within specified range (min/max)
- **`timestamp`**: Current timestamp in various formats
- **`email`**: Random email addresses with configurable domain
- **`choice`**: Random selection from provided options

Example configuration:
```json
{
  "data_generators": {
    "user_id": {"type": "uuid"},
    "username": {"type": "string", "length": 12},
    "age": {"type": "number", "min": 18, "max": 65},
    "email": {"type": "email", "domain": "testdomain.com"},
    "role": {"type": "choice", "choices": ["admin", "user", "guest"]}
  }
}
```

### Authentication Types

**Bearer Token:**
```json
{
  "auth": {
    "type": "bearer",
    "token": "eyJhbGciOiJIUzI1NiIs..."
  }
}
```

**Basic Authentication:**
```json
{
  "auth": {
    "type": "basic",
    "username": "admin",
    "password": "secret123"
  }
}
```

**API Key:**
```json
{
  "auth": {
    "type": "apikey",
    "token": "your-api-key-here",
    "header_name": "X-API-Key"
  }
}
```

### File Data Loading
Load test data from CSV or JSON files:

**CSV format example (users.csv):**
```csv
name,email,age
John Doe,john@example.com,25
Jane Smith,jane@example.com,30
```

**JSON format example (users.json):**
```json
[
  {"name": "John Doe", "email": "john@example.com", "age": 25},
  {"name": "Jane Smith", "email": "jane@example.com", "age": 30}
]
```

### Environment Variables
Support for environment variable injection:
```json
{
  "env_variables": {
    "API_BASE_URL": "https://staging.api.com",
    "VERSION": "v2",
    "NODE_ENV": "$NODE_ENV"
  }
}
```

Variables prefixed with `$` will be resolved from system environment variables.

## Troubleshooting

### K6 Not Found
Ensure K6 is installed and available in your PATH:
```bash
k6 version
```

### Permission Issues
Make sure the server has write permissions to the reports directory.

### Script Generation Errors
Check that your URL is valid and accessible.

### Authentication Failures
Verify your authentication tokens and credentials are valid.

### Data File Issues
Ensure CSV/JSON files exist and have proper formatting.

## Development

To run the server directly:
```bash
cd src
python server.py
```

### Testing
Run the test suite to verify functionality:
```bash
# Run unit tests
PYTHONPATH=. python3 test_extended_params.py

# Test individual components
PYTHONPATH=. python3 -c "from src.data_generators import DataGenerator; print('DataGenerator works!')"
```

### Project Structure
```
k6-mcp-server/
├── src/
│   ├── server.py          # Main MCP server with 5 tools (including new HTML/JSON report access)
│   ├── k6_runner.py       # K6 test execution with iterations/duration control
│   ├── report_instructions.py # AI model reporting guidelines and safety restrictions
│   ├── data_generators.py # Dynamic data generation utilities
│   └── templates/         # K6 script templates with handleSummary integration
│       ├── constant_load.js  # Supports both iterations and duration modes
│       ├── ramp_up.js       # Gradual load increase with detailed analysis
│       └── spike.js         # Traffic spikes with resilience assessment
├── reports/               # Multi-format test results
│   ├── *.json            # Raw K6 + detailed summaries
│   ├── *.html            # Professional HTML reports with charts
│   └── *.csv             # Detailed CSV exports for analysis
├── test_extended_params.py # Unit tests
├── requirements.txt       # Python dependencies
├── CLAUDE.md             # Claude Code integration documentation
└── README.md             # This comprehensive documentation
```

For development, install additional dependencies:
```bash
pip install -e ".[dev]"
```

## License

MIT License