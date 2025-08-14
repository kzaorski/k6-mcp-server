#!/usr/bin/env python3
"""
Startup script for K6 MCP Server that handles dependencies installation
"""
import subprocess
import sys
import os
from pathlib import Path

def install_requirements():
    """Install required packages if they're missing"""
    try:
        import aiofiles
        import aiohttp
        print("Dependencies already installed")
        return True
    except ImportError:
        print("Installing missing dependencies...")
        
    # Get the directory containing this script
    script_dir = Path(__file__).parent
    requirements_file = script_dir / "requirements.txt"
    
    if requirements_file.exists():
        try:
            # Install packages with --user flag to avoid permission issues
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                "-r", str(requirements_file), "--user"
            ])
            print("Dependencies installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to install dependencies: {e}")
            return False
    else:
        print(f"Requirements file not found: {requirements_file}")
        return False

def main():
    """Main entry point"""
    # Change to src directory
    src_dir = Path(__file__).parent / "src"
    os.chdir(src_dir)
    
    # Add src to Python path
    sys.path.insert(0, str(src_dir))
    
    # Install dependencies
    if not install_requirements():
        sys.exit(1)
    
    # Start the MCP server
    try:
        import server
        print("K6 MCP Server starting...")
        # The server should handle its own main loop
    except Exception as e:
        print(f"Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()