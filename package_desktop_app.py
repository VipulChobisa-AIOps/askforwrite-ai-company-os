"""
Build script to package AskforWrite AI Company OS into a Windows Desktop Executable.
"""

import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
BUILD_DIR = BASE_DIR / "build"

def build():
    print("=" * 60)
    print(" Packaging AskforWrite AI Company OS Desktop Application")
    print("=" * 60)
    
    python_exe = sys.executable
    print(f"Using Python: {python_exe}")
    
    cmd = [
        python_exe, "-m", "PyInstaller",
        "--name=AskforWrite_Company_OS",
        "--noconfirm",
        "--clean",
        "--windowed",  # No black cmd box for the GUI
        "--add-data=app;app",
        "--add-data=.env.example;.",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=sqlalchemy.dialects.sqlite",
        "--hidden-import=google.genai",
        "--hidden-import=langgraph",
        "--hidden-import=langsmith",
        "desktop_app.py"
    ]
    
    print("\nRunning PyInstaller command:")
    print(" ".join(cmd))
    
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print(f"  Executable location: {DIST_DIR / 'AskforWrite_Company_OS' / 'AskforWrite_Company_OS.exe'}")
        print("=" * 60)
    else:
        print("\nBuild failed with exit code:", result.returncode)
        sys.exit(result.returncode)

if __name__ == "__main__":
    build()
