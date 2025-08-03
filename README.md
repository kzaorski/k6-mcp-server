# K6 MCP Server

MCP (Model Context Protocol) server for running K6 performance tests through Claude Code.

## Features

- 🚀 Run K6 performance tests with customizable parameters
- 📊 Support for different load patterns (constant, ramp-up, spike)
- 📈 Detailed performance metrics and reporting
- 🔧 Easy integration with Claude Code/Desktop

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
- `url` (required): The endpoint URL to test
- `method` (optional): HTTP method (GET, POST, PUT, DELETE, PATCH) - default: GET
- `payload` (optional): JSON payload for POST/PUT requests
- `load_pattern` (optional): Load testing pattern - default: constant
  - `constant`: Maintains steady number of virtual users
  - `ramp_up`: Gradually increases virtual users
  - `spike`: Sudden traffic spikes
- `duration` (optional): Test duration (e.g., '30s', '5m') - default: 30s
- `virtual_users` (optional): Number of virtual users - default: 10
- `thresholds` (optional): Performance thresholds

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

### Basic API Endpoint Test
```json
{
  "url": "https://api.example.com/health",
  "method": "GET",
  "duration": "1m",
  "virtual_users": 10
}
```

### POST Request with Payload
```json
{
  "url": "https://api.example.com/users",
  "method": "POST",
  "payload": {
    "name": "Test User",
    "email": "test@example.com"
  },
  "load_pattern": "ramp_up",
  "duration": "3m",
  "virtual_users": 25
}
```

### Stress Test with Thresholds
```json
{
  "url": "https://api.example.com/data",
  "method": "GET",
  "load_pattern": "spike",
  "duration": "5m",
  "virtual_users": 100,
  "thresholds": {
    "http_req_duration": "p(95)<1000",
    "http_req_failed": "rate<0.05",
    "http_reqs": "rate>10"
  }
}
```

## Output Metrics

The server provides comprehensive performance metrics including:

- **Response Times**: Average, minimum, maximum, and 95th percentile
- **Throughput**: Requests per second and total requests
- **Error Rate**: Percentage of failed requests
- **Data Transfer**: Amount of data sent and received
- **Test Duration**: Actual test execution time
- **Virtual Users**: Maximum concurrent users

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

## Development

To run the server directly:
```bash
cd src
python server.py
```

For development, install additional dependencies:
```bash
pip install -e ".[dev]"
```

## License

MIT License