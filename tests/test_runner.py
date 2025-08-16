"""
Test runner for K6 MCP Server.

Provides utilities for running tests with different configurations
and generating test reports.
"""

import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional


def run_unit_tests(verbose: bool = False, coverage: bool = True) -> int:
    """
    Run unit tests.
    
    Args:
        verbose: Enable verbose output
        coverage: Enable coverage reporting
        
    Returns:
        Exit code (0 for success)
    """
    cmd = ["python", "-m", "pytest", "tests/unit/"]
    
    if verbose:
        cmd.append("-v")
    
    if coverage:
        cmd.extend([
            "--cov=src",
            "--cov-report=html:reports/coverage",
            "--cov-report=term-missing"
        ])
    
    cmd.extend([
        "--tb=short",
        "-x"  # Stop on first failure
    ])
    
    print("🧪 Running unit tests...")
    return subprocess.run(cmd).returncode


def run_integration_tests(verbose: bool = False) -> int:
    """
    Run integration tests.
    
    Args:
        verbose: Enable verbose output
        
    Returns:
        Exit code (0 for success)
    """
    cmd = [
        "python", "-m", "pytest", 
        "tests/integration/",
        "-m", "integration"
    ]
    
    if verbose:
        cmd.append("-v")
    
    cmd.extend([
        "--tb=short",
        "-x"
    ])
    
    print("🔗 Running integration tests...")
    return subprocess.run(cmd).returncode


def run_e2e_tests(verbose: bool = False) -> int:
    """
    Run end-to-end tests.
    
    Args:
        verbose: Enable verbose output
        
    Returns:
        Exit code (0 for success)
    """
    cmd = [
        "python", "-m", "pytest",
        "tests/e2e/",
        "-m", "e2e"
    ]
    
    if verbose:
        cmd.append("-v")
    
    cmd.extend([
        "--tb=short",
        "-x"
    ])
    
    print("🎯 Running end-to-end tests...")
    return subprocess.run(cmd).returncode


def run_performance_tests(verbose: bool = False) -> int:
    """
    Run performance tests.
    
    Args:
        verbose: Enable verbose output
        
    Returns:
        Exit code (0 for success)
    """
    cmd = [
        "python", "-m", "pytest",
        "tests/unit/test_performance.py",
        "-v" if verbose else "",
        "--tb=short"
    ]
    
    cmd = [c for c in cmd if c]  # Remove empty strings
    
    print("⚡ Running performance tests...")
    return subprocess.run(cmd).returncode


def run_all_tests(verbose: bool = False, coverage: bool = True) -> int:
    """
    Run all tests in sequence.
    
    Args:
        verbose: Enable verbose output
        coverage: Enable coverage reporting
        
    Returns:
        Exit code (0 if all tests pass)
    """
    print("🚀 Running complete test suite...")
    
    # Run tests in order of speed (fastest first)
    test_runners = [
        ("Unit Tests", lambda: run_unit_tests(verbose, coverage)),
        ("Performance Tests", lambda: run_performance_tests(verbose)),
        ("Integration Tests", lambda: run_integration_tests(verbose)),
        ("End-to-End Tests", lambda: run_e2e_tests(verbose))
    ]
    
    total_exit_code = 0
    
    for test_name, runner in test_runners:
        print(f"\n{'='*50}")
        print(f"Running {test_name}")
        print(f"{'='*50}")
        
        exit_code = runner()
        total_exit_code += exit_code
        
        if exit_code == 0:
            print(f"✅ {test_name} passed")
        else:
            print(f"❌ {test_name} failed (exit code: {exit_code})")
            
            # Ask if user wants to continue
            if not verbose:  # Only prompt in non-verbose mode
                response = input(f"\n{test_name} failed. Continue with remaining tests? (y/n): ")
                if response.lower() != 'y':
                    break
    
    print(f"\n{'='*50}")
    if total_exit_code == 0:
        print("🎉 All tests passed!")
    else:
        print(f"💥 Some tests failed (total exit code: {total_exit_code})")
    print(f"{'='*50}")
    
    return min(total_exit_code, 1)  # Return 0 or 1


def run_specific_test(test_path: str, verbose: bool = False) -> int:
    """
    Run a specific test file or test function.
    
    Args:
        test_path: Path to test file or test function (e.g., "tests/unit/test_models.py::TestK6TestConfig::test_valid_config")
        verbose: Enable verbose output
        
    Returns:
        Exit code (0 for success)
    """
    cmd = ["python", "-m", "pytest", test_path]
    
    if verbose:
        cmd.append("-v")
    
    cmd.extend([
        "--tb=short",
        "-s"  # Don't capture output
    ])
    
    print(f"🎯 Running specific test: {test_path}")
    return subprocess.run(cmd).returncode


def check_test_dependencies() -> bool:
    """
    Check if all test dependencies are installed.
    
    Returns:
        True if all dependencies are available
    """
    required_packages = [
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "pytest-mock"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ Missing test dependencies: {', '.join(missing_packages)}")
        print("💡 Install with: pip install pytest pytest-asyncio pytest-cov pytest-mock")
        return False
    
    print("✅ All test dependencies are installed")
    return True


def setup_test_environment() -> bool:
    """
    Set up test environment.
    
    Returns:
        True if setup successful
    """
    print("🔧 Setting up test environment...")
    
    # Ensure test directories exist
    test_dirs = [
        "tests/unit",
        "tests/integration", 
        "tests/e2e",
        "reports",
        "reports/coverage"
    ]
    
    for directory in test_dirs:
        Path(directory).mkdir(parents=True, exist_ok=True)
    
    # Set environment variables for testing
    os.environ["PYTHONPATH"] = str(Path(__file__).parent / "src")
    os.environ["TESTING"] = "true"
    
    print("✅ Test environment setup complete")
    return True


def generate_test_report() -> None:
    """Generate comprehensive test report."""
    print("📊 Generating test report...")
    
    # Run tests with JUnit XML output for CI/CD
    cmd = [
        "python", "-m", "pytest",
        "tests/",
        "--junitxml=reports/junit.xml",
        "--cov=src",
        "--cov-report=xml:reports/coverage.xml",
        "--cov-report=html:reports/coverage",
        "--html=reports/test_report.html",
        "--self-contained-html"
    ]
    
    subprocess.run(cmd)
    print("✅ Test report generated in reports/ directory")


def main():
    """Main test runner entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="K6 MCP Server Test Runner")
    parser.add_argument(
        "test_type",
        choices=["unit", "integration", "e2e", "performance", "all", "specific"],
        help="Type of tests to run"
    )
    parser.add_argument(
        "--test-path",
        help="Specific test path (for 'specific' test type)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--no-coverage",
        action="store_true",
        help="Disable coverage reporting"
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only setup test environment, don't run tests"
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Only check test dependencies"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate comprehensive test report"
    )
    
    args = parser.parse_args()
    
    # Check dependencies
    if args.check_deps:
        return 0 if check_test_dependencies() else 1
    
    # Setup environment
    if not setup_test_environment():
        return 1
    
    if args.setup_only:
        return 0
    
    # Check test dependencies
    if not check_test_dependencies():
        return 1
    
    # Generate report
    if args.report:
        generate_test_report()
        return 0
    
    # Run tests
    coverage = not args.no_coverage
    
    if args.test_type == "unit":
        return run_unit_tests(args.verbose, coverage)
    elif args.test_type == "integration":
        return run_integration_tests(args.verbose)
    elif args.test_type == "e2e":
        return run_e2e_tests(args.verbose)
    elif args.test_type == "performance":
        return run_performance_tests(args.verbose)
    elif args.test_type == "all":
        return run_all_tests(args.verbose, coverage)
    elif args.test_type == "specific":
        if not args.test_path:
            print("❌ --test-path is required for 'specific' test type")
            return 1
        return run_specific_test(args.test_path, args.verbose)
    
    return 1


if __name__ == "__main__":
    sys.exit(main())