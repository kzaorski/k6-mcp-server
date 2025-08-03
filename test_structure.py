#!/usr/bin/env python3
"""
Basic structure test for K6 MCP Server
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all modules can be imported correctly."""
    try:
        import server
        print("✅ server.py imports successfully")
        
        import k6_runner
        print("✅ k6_runner.py imports successfully")
        
        # Test K6Runner class
        runner = k6_runner.K6Runner()
        print("✅ K6Runner class instantiates successfully")
        
        # Test template files exist
        templates_dir = runner.templates_dir
        expected_templates = ['constant_load.js', 'ramp_up.js', 'spike.js']
        
        for template in expected_templates:
            template_path = templates_dir / template
            if template_path.exists():
                print(f"✅ Template {template} exists")
            else:
                print(f"❌ Template {template} missing")
                
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_k6_availability():
    """Test if K6 is available in PATH."""
    import subprocess
    try:
        result = subprocess.run(['k6', 'version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=10)
        if result.returncode == 0:
            print("✅ K6 is available in PATH")
            print(f"   Version: {result.stdout.strip()}")
            return True
        else:
            print("❌ K6 command failed")
            return False
    except FileNotFoundError:
        print("⚠️  K6 not found in PATH")
        print("   Install K6 to run performance tests")
        return False
    except subprocess.TimeoutExpired:
        print("❌ K6 command timed out")
        return False
    except Exception as e:
        print(f"❌ Error checking K6: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing K6 MCP Server Structure")
    print("=" * 40)
    
    import_success = test_imports()
    print()
    
    k6_success = test_k6_availability()
    print()
    
    if import_success:
        print("✅ Server structure is valid")
    else:
        print("❌ Server structure has issues")
        
    print("\n📝 To use this MCP server:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Install K6: https://k6.io/docs/get-started/installation/")
    print("3. Configure in Claude Desktop using claude-config.json")
    print("4. Run server: python src/server.py")