#!/usr/bin/env python3
"""
Agent Deployment Script - One-click setup for agent listener.

Usage:
    python deploy.py              # Configure and verify
    python deploy.py --start      # Configure, verify, and start listener
    python deploy.py --check      # Just check prerequisites
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
AGENT_DIR = SCRIPT_DIR / "agent"
CONTEXT_DIR = AGENT_DIR / "context"


def load_config():
    """Load configuration from config.json."""
    if not CONFIG_FILE.exists():
        print("ERROR: config.json not found!")
        print("Create config.json with your agent settings.")
        sys.exit(1)

    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)


def check_prerequisites(config):
    """Check all prerequisites are met."""
    print("\n=== Checking Prerequisites ===\n")
    all_ok = True

    # Python version
    py_version = sys.version_info
    if py_version >= (3, 8):
        print(f"  [OK] Python {py_version.major}.{py_version.minor}")
    else:
        print(f"  [FAIL] Python 3.8+ required (found {py_version.major}.{py_version.minor})")
        all_ok = False

    # Flask
    try:
        import flask
        try:
            from importlib.metadata import version
            flask_ver = version("flask")
        except:
            flask_ver = "installed"
        print(f"  [OK] Flask {flask_ver}")
    except ImportError:
        print("  [FAIL] Flask not installed - run: pip install flask")
        all_ok = False

    # Requests
    try:
        import requests
        print(f"  [OK] Requests {requests.__version__}")
    except ImportError:
        print("  [FAIL] Requests not installed - run: pip install requests")
        all_ok = False

    # Claude CLI
    claude_path = shutil.which("claude")
    if claude_path:
        print(f"  [OK] Claude CLI found: {claude_path}")
    else:
        print("  [FAIL] Claude CLI not found in PATH")
        print("         Install: npm install -g @anthropic-ai/claude-code")
        all_ok = False

    # API Key environment variable
    api_key_env = config.get("api_key_env", "ACTO")
    if os.getenv(api_key_env):
        print(f"  [OK] {api_key_env} environment variable set")
    else:
        print(f"  [FAIL] {api_key_env} environment variable not set")
        all_ok = False

    # Directories
    if AGENT_DIR.exists():
        print(f"  [OK] Agent directory: {AGENT_DIR}")
    else:
        print(f"  [FAIL] Agent directory missing: {AGENT_DIR}")
        all_ok = False

    if (AGENT_DIR / "CLAUDE.md").exists():
        print(f"  [OK] CLAUDE.md found")
    else:
        print(f"  [FAIL] CLAUDE.md missing in agent/")
        all_ok = False

    return all_ok


def apply_templates(config):
    """Replace {{placeholders}} in template files."""
    print("\n=== Applying Configuration ===\n")

    agent_name = config["agent_name"]
    description = config.get("description", f"{agent_name} Agent")

    replacements = {
        "{{AGENT_NAME}}": agent_name,
        "{{DESCRIPTION}}": description,
    }

    # Files to process
    template_files = [
        AGENT_DIR / "CLAUDE.md",
        CONTEXT_DIR / "identity.md",
        CONTEXT_DIR / "crm-api.md",
    ]

    for filepath in template_files:
        if filepath.exists():
            content = filepath.read_text(encoding='utf-8')
            original = content

            for placeholder, value in replacements.items():
                content = content.replace(placeholder, value)

            if content != original:
                filepath.write_text(content, encoding='utf-8')
                print(f"  [UPDATED] {filepath.name}")
            else:
                print(f"  [OK] {filepath.name} (no changes needed)")

    # Ensure threads directory exists
    threads_dir = AGENT_DIR / "threads"
    threads_dir.mkdir(exist_ok=True)
    print(f"  [OK] threads/ directory ready")


def show_summary(config):
    """Show configuration summary."""
    print("\n=== Agent Configuration ===\n")
    print(f"  Agent Name:    {config['agent_name']}")
    print(f"  Listen Port:   {config['listen_port']}")
    print(f"  Listen Host:   {config.get('listen_host', '0.0.0.0')}")
    print(f"  CRM Endpoint:  {config['crm_endpoint']}")
    print(f"  API Key Env:   {config.get('api_key_env', 'ACTO')}")
    print(f"  Working Dir:   {AGENT_DIR}")


def start_listener():
    """Start the listener service."""
    print("\n=== Starting Listener ===\n")
    listener_path = SCRIPT_DIR / "listener.py"
    subprocess.run([sys.executable, str(listener_path)])


def main():
    args = sys.argv[1:]

    print("""
=====================================
  Agent Listener Deployment Tool
=====================================
""")

    config = load_config()
    show_summary(config)

    if "--check" in args:
        ok = check_prerequisites(config)
        sys.exit(0 if ok else 1)

    ok = check_prerequisites(config)
    if not ok:
        print("\n[!] Fix prerequisites before continuing.")
        sys.exit(1)

    apply_templates(config)

    print("\n=== Ready! ===\n")
    print(f"  To start: python listener.py")
    print(f"  Or run:   python deploy.py --start")

    if "--start" in args:
        start_listener()


if __name__ == "__main__":
    main()
