#!/usr/bin/env python3
"""
Agent Listener - Canonical package with composable context.

Reads configuration from config.json in the same directory.
See SETUP.md for configuration instructions.

Architecture:
- CLAUDE.md in agent/ contains @context/ imports
- Context files in agent/context/ are modular and composable
- Dynamic context (state, history) written before each session
- Claude CLI reads CLAUDE.md and resolves imports automatically
"""

import os
import sys
import json
import subprocess
import threading
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
from pathlib import Path

from flask import Flask, request, jsonify
import requests

# Version - increment when making changes
LISTENER_VERSION = "1.1.0"

# Load configuration from config.json
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"

if not CONFIG_FILE.exists():
    print("ERROR: config.json not found. See SETUP.md")
    sys.exit(1)

with open(CONFIG_FILE, 'r') as f:
    CONFIG = json.load(f)

AGENT_NAME = CONFIG.get("agent_name", "UNCONFIGURED")
LISTEN_HOST = CONFIG.get("listen_host", "0.0.0.0")
LISTEN_PORT = CONFIG.get("listen_port", 8080)
CRM_ENDPOINT = CONFIG.get("crm_endpoint", "https://crm.actionapi.ca")
API_KEY_ENV = CONFIG.get("api_key_env", "ACTO")

if AGENT_NAME == "UNCONFIGURED":
    print("ERROR: Agent not configured. Edit config.json. See SETUP.md")
    sys.exit(1)

CRM_API_KEY = os.getenv(API_KEY_ENV)
if not CRM_API_KEY:
    print(f"ERROR: {API_KEY_ENV} environment variable not set")
    sys.exit(1)

# Paths - agent/ directory contains CLAUDE.md and context/
WORKING_DIR = SCRIPT_DIR / "agent"
CONTEXT_DIR = WORKING_DIR / "context"
THREADS_DIR = WORKING_DIR / "threads"

# Ensure directories exist
WORKING_DIR.mkdir(exist_ok=True)
CONTEXT_DIR.mkdir(exist_ok=True)
THREADS_DIR.mkdir(exist_ok=True)


def get_tailscale_ip():
    """Get Tailscale IPv4 address."""
    try:
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return None


def register_with_crm(retries=5, delay=10):
    """Register agent with CRM on startup. Retries if Tailscale not ready."""
    if not CRM_API_KEY:
        print("No API key - skipping CRM registration")
        return False

    for attempt in range(retries):
        ip = get_tailscale_ip()
        if not ip:
            if attempt < retries - 1:
                print(f"No Tailscale IP yet, retry {attempt + 1}/{retries} in {delay}s...")
                time.sleep(delay)
                continue
            else:
                print("No Tailscale IP after all retries - skipping registration")
                return False

        try:
            resp = requests.post(
                f"{CRM_ENDPOINT}/api/agents/register",
                json={"name": AGENT_NAME, "ip": ip, "port": LISTEN_PORT, "default": False},
                headers={"X-API-Key": CRM_API_KEY},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"Registered with CRM: {data.get('agent', {}).get('endpoint', 'ok')}")
                return True
            else:
                print(f"CRM registration failed: {resp.status_code}")
        except Exception as e:
            print(f"CRM registration error: {e}")

        if attempt < retries - 1:
            print(f"Retrying registration in {delay}s...")
            time.sleep(delay)

    return False


@dataclass
class ThreadState:
    """Represents the state of a conversation thread."""
    thread_id: str
    status: str = "sleeping"
    last_active: datetime = field(default_factory=datetime.now)
    message_count: int = 0


class AgentListener:
    """Listener service using CLI-based Claude spawning with composable context."""

    def __init__(self):
        self.threads: Dict[str, ThreadState] = {}
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        """Configure Flask routes."""

        # ============ HEALTH & VERSION ============

        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "threads": len(self.threads),
                "agent": AGENT_NAME,
                "version": LISTENER_VERSION
            })

        @self.app.route('/version', methods=['GET'])
        def get_version():
            return jsonify({
                "version": LISTENER_VERSION,
                "agent": AGENT_NAME,
                "listener_file": str(Path(__file__).name),
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            })

        # ============ UPDATE & ROLLBACK ============

        @self.app.route('/update', methods=['POST'])
        def update_listener():
            data = request.json or {}
            force = data.get('force', False)

            try:
                response = requests.get(
                    f"{CRM_ENDPOINT}/api/agents/listener",
                    headers={"X-API-Key": CRM_API_KEY},
                    params={"agent": AGENT_NAME},
                    timeout=30
                )

                if response.status_code == 404:
                    return jsonify({"error": "No listener update available on CRM"}), 404

                if response.status_code != 200:
                    return jsonify({"error": f"CRM returned {response.status_code}"}), response.status_code

                update_data = response.json()
                new_version = update_data.get('version', 'unknown')
                new_code = update_data.get('code', '')

                if not new_code:
                    return jsonify({"error": "No code in update response"}), 400

                if new_version == LISTENER_VERSION and not force:
                    return jsonify({
                        "status": "current",
                        "version": LISTENER_VERSION,
                        "message": "Already at latest version"
                    })

                # Backup current file
                listener_path = Path(__file__)
                backup_path = listener_path.with_suffix('.py.bak')
                shutil.copy(listener_path, backup_path)

                # Write new code
                listener_path.write_text(new_code, encoding='utf-8')

                print(f"   [UPDATE] Updated from {LISTENER_VERSION} to {new_version}")
                print(f"   [UPDATE] Backup saved to {backup_path}")

                return jsonify({
                    "status": "updated",
                    "old_version": LISTENER_VERSION,
                    "new_version": new_version,
                    "backup": str(backup_path),
                    "restart_required": True
                })

            except requests.exceptions.RequestException as e:
                return jsonify({"error": f"Failed to reach CRM: {str(e)}"}), 503

        @self.app.route('/rollback', methods=['POST'])
        def rollback_listener():
            listener_path = Path(__file__)
            backup_path = listener_path.with_suffix('.py.bak')

            if not backup_path.exists():
                return jsonify({"error": "No backup file found"}), 404

            try:
                failed_path = listener_path.with_suffix('.py.failed')
                shutil.copy(listener_path, failed_path)
                shutil.copy(backup_path, listener_path)

                print(f"   [ROLLBACK] Restored from backup")
                return jsonify({
                    "status": "rolled_back",
                    "restart_required": True
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        # ============ THREADS ============

        @self.app.route('/threads', methods=['GET'])
        def get_threads():
            return self._handle_get_threads()

        @self.app.route('/threads/<thread_id>/history', methods=['GET'])
        def get_thread_history(thread_id):
            return self._handle_get_history(thread_id)

        @self.app.route('/threads/<thread_id>', methods=['DELETE'])
        def delete_thread(thread_id):
            return self._handle_delete_thread(thread_id)

        @self.app.route('/message', methods=['POST'])
        def send_message():
            return self._handle_send_message()

        # ============ CONTEXT API ============

        @self.app.route('/context', methods=['GET'])
        def list_context():
            files = []
            claude_md = WORKING_DIR / "CLAUDE.md"
            claude_content = claude_md.read_text(encoding='utf-8') if claude_md.exists() else ""

            for f in CONTEXT_DIR.glob("*.md"):
                stat = f.stat()
                files.append({
                    "name": f.stem,
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "included": f"@context/{f.name}" in claude_content
                })
            return jsonify({"context_files": files, "total": len(files)})

        @self.app.route('/context', methods=['POST'])
        def create_context():
            import re
            data = request.json
            name = data.get('name', '').strip()
            content = data.get('content', '')

            if not name:
                return jsonify({"error": "Name required"}), 400
            if not re.match(r'^[A-Za-z0-9_-]+$', name):
                return jsonify({"error": "Invalid name (alphanumeric, dash, underscore only)"}), 400

            filepath = CONTEXT_DIR / f"{name}.md"
            if filepath.exists():
                return jsonify({"error": f"Context '{name}' already exists. Use PUT to update."}), 409

            filepath.write_text(content, encoding='utf-8')
            print(f"   [CONTEXT] Created: {name}.md ({len(content)} chars)")
            return jsonify({"status": "created", "name": name}), 201

        @self.app.route('/context/<name>', methods=['GET'])
        def get_context(name):
            import re
            if not re.match(r'^[A-Za-z0-9_-]+$', name):
                return jsonify({"error": "Invalid name"}), 400

            filepath = CONTEXT_DIR / f"{name}.md"
            if not filepath.exists():
                return jsonify({"error": f"Context '{name}' not found"}), 404

            content = filepath.read_text(encoding='utf-8')
            return jsonify({"name": name, "content": content})

        @self.app.route('/context/<name>', methods=['PUT'])
        def save_context(name):
            import re
            if not re.match(r'^[A-Za-z0-9_-]+$', name):
                return jsonify({"error": "Invalid name"}), 400

            data = request.json
            content = data.get('content')
            if not content:
                return jsonify({"error": "Content required"}), 400

            filepath = CONTEXT_DIR / f"{name}.md"
            filepath.write_text(content, encoding='utf-8')

            print(f"   [CONTEXT] Saved: {name}.md ({len(content)} chars)")
            return jsonify({"status": "saved", "name": name})

        @self.app.route('/context/<name>', methods=['DELETE'])
        def delete_context(name):
            import re
            if not re.match(r'^[A-Za-z0-9_-]+$', name):
                return jsonify({"error": "Invalid name"}), 400

            filepath = CONTEXT_DIR / f"{name}.md"
            if not filepath.exists():
                return jsonify({"error": f"Context '{name}' not found"}), 404

            filepath.unlink()
            print(f"   [CONTEXT] Deleted: {name}.md")
            return jsonify({"status": "deleted", "name": name})

        @self.app.route('/claude-md', methods=['GET'])
        def get_claude_md():
            claude_md = WORKING_DIR / "CLAUDE.md"
            if not claude_md.exists():
                return jsonify({"error": "CLAUDE.md not found"}), 404
            content = claude_md.read_text(encoding='utf-8')
            return jsonify({"content": content})

        @self.app.route('/claude-md', methods=['PUT'])
        def save_claude_md():
            data = request.json
            content = data.get('content')
            if not content:
                return jsonify({"error": "Content required"}), 400

            claude_md = WORKING_DIR / "CLAUDE.md"
            claude_md.write_text(content, encoding='utf-8')
            print(f"   [CLAUDE.md] Updated ({len(content)} chars)")
            return jsonify({"status": "saved"})

        # ============ SKILLS SYNC API ============

        @self.app.route('/skills/available', methods=['GET'])
        def list_available_skills():
            try:
                response = requests.get(
                    f"{CRM_ENDPOINT}/api/skills",
                    headers={"X-API-Key": CRM_API_KEY},
                    timeout=10
                )
                if response.status_code == 200:
                    return jsonify(response.json())
                else:
                    return jsonify({"error": f"CRM returned {response.status_code}"}), response.status_code
            except requests.exceptions.RequestException as e:
                return jsonify({"error": f"Failed to reach CRM: {str(e)}"}), 503

        @self.app.route('/skills/publish', methods=['POST'])
        def publish_skill():
            import re
            data = request.json
            name = data.get('name', '').strip()

            if not name:
                return jsonify({"error": "Skill name required"}), 400
            if not re.match(r'^[A-Za-z0-9_-]+$', name):
                return jsonify({"error": "Invalid name"}), 400

            filepath = CONTEXT_DIR / f"{name}.md"
            if not filepath.exists():
                return jsonify({"error": f"Local context '{name}' not found"}), 404

            content = filepath.read_text(encoding='utf-8')

            try:
                response = requests.post(
                    f"{CRM_ENDPOINT}/api/skills",
                    headers={"X-API-Key": CRM_API_KEY, "Content-Type": "application/json"},
                    json={"name": name, "content": content, "source_agent": AGENT_NAME},
                    timeout=10
                )
                if response.status_code in (200, 201):
                    print(f"   [SKILLS] Published '{name}' to CRM")
                    return jsonify({"status": "published", "name": name})
                else:
                    return jsonify({"error": f"CRM returned {response.status_code}"}), response.status_code
            except requests.exceptions.RequestException as e:
                return jsonify({"error": f"Failed to reach CRM: {str(e)}"}), 503

        @self.app.route('/skills/pull', methods=['POST'])
        def pull_skill():
            import re
            data = request.json
            name = data.get('name', '').strip()
            overwrite = data.get('overwrite', False)

            if not name:
                return jsonify({"error": "Skill name required"}), 400
            if not re.match(r'^[A-Za-z0-9_-]+$', name):
                return jsonify({"error": "Invalid name"}), 400

            filepath = CONTEXT_DIR / f"{name}.md"
            if filepath.exists() and not overwrite:
                return jsonify({"error": f"Local context '{name}' already exists. Set overwrite=true."}), 409

            try:
                response = requests.get(
                    f"{CRM_ENDPOINT}/api/skills/{name}",
                    headers={"X-API-Key": CRM_API_KEY},
                    timeout=10
                )
                if response.status_code == 200:
                    skill_data = response.json()
                    content = skill_data.get('content', '')
                    filepath.write_text(content, encoding='utf-8')
                    print(f"   [SKILLS] Pulled '{name}' from CRM ({len(content)} chars)")
                    return jsonify({"status": "pulled", "name": name, "size": len(content)})
                elif response.status_code == 404:
                    return jsonify({"error": f"Skill '{name}' not found on CRM"}), 404
                else:
                    return jsonify({"error": f"CRM returned {response.status_code}"}), response.status_code
            except requests.exceptions.RequestException as e:
                return jsonify({"error": f"Failed to reach CRM: {str(e)}"}), 503

        @self.app.route('/skills/sync', methods=['POST'])
        def sync_skills():
            results = {"published": [], "failed": []}

            for filepath in CONTEXT_DIR.glob("*.md"):
                name = filepath.stem
                if name in ('state', 'history'):
                    continue

                content = filepath.read_text(encoding='utf-8')
                try:
                    response = requests.post(
                        f"{CRM_ENDPOINT}/api/skills",
                        headers={"X-API-Key": CRM_API_KEY, "Content-Type": "application/json"},
                        json={"name": name, "content": content, "source_agent": AGENT_NAME},
                        timeout=10
                    )
                    if response.status_code in (200, 201):
                        results["published"].append(name)
                    else:
                        results["failed"].append({"name": name, "error": response.status_code})
                except Exception as e:
                    results["failed"].append({"name": name, "error": str(e)})

            print(f"   [SKILLS] Sync complete: {len(results['published'])} published, {len(results['failed'])} failed")
            return jsonify(results)

    # ============ HANDLERS ============

    def _handle_get_threads(self):
        threads_info = []

        for thread_file in THREADS_DIR.glob("*.json"):
            thread_id = thread_file.stem
            try:
                history = self._load_history(thread_id)
                if history:
                    threads_info.append({
                        "thread_id": thread_id,
                        "status": self.threads.get(thread_id, ThreadState(thread_id)).status,
                        "message_count": len([m for m in history if m.get("role") == "user"]),
                        "last_active": history[-1].get("timestamp", "")
                    })
            except Exception as e:
                print(f"WARNING: Error loading thread {thread_id}: {e}")

        return jsonify({"threads": threads_info})

    def _handle_get_history(self, thread_id: str):
        history = self._load_history(thread_id)
        return jsonify({"messages": history})

    def _handle_delete_thread(self, thread_id: str):
        deleted_memory = thread_id in self.threads
        if deleted_memory:
            del self.threads[thread_id]

        history_file = THREADS_DIR / f"{thread_id}.json"
        deleted_disk = history_file.exists()
        if deleted_disk:
            history_file.unlink()

        if not deleted_memory and not deleted_disk:
            return jsonify({"error": f"Thread '{thread_id}' not found"}), 404

        print(f"   [DELETE] Thread '{thread_id}' deleted")
        return jsonify({"status": "deleted", "thread_id": thread_id})

    def _handle_send_message(self):
        try:
            data = request.json
            thread_id = data.get('thread_id', 'general')
            message = data.get('message')
            sender = data.get('sender', 'unknown')
            channel = data.get('channel', 'unknown')

            if not message:
                return jsonify({"error": "Message required"}), 400

            print(f"\n>> [{AGENT_NAME}] Received message for thread '{thread_id}' from {sender} via {channel}")
            print(f"   Message: {message[:100]}...")

            threading.Thread(
                target=self._process_message_sync,
                args=(thread_id, message, sender, channel),
                daemon=True
            ).start()

            return jsonify({
                "status": "accepted",
                "thread_id": thread_id,
                "message": "Processing your request..."
            })

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    def _process_message_sync(self, thread_id: str, message: str, sender: str, channel: str):
        try:
            if thread_id not in self.threads:
                self.threads[thread_id] = ThreadState(thread_id, "live")
            self.threads[thread_id].status = "live"
            self.threads[thread_id].last_active = datetime.now()

            self._save_message(thread_id, "user", message)
            self._write_dynamic_context(thread_id, sender, channel)

            print(f"   [CLAUDE] Spawning Claude CLI for thread '{thread_id}'...")
            response_text = self._run_claude_cli(message)

            self._save_message(thread_id, "assistant", response_text)
            self._send_to_crm(thread_id, sender, channel, response_text)

            self.threads[thread_id].status = "sleeping"
            self.threads[thread_id].message_count += 1
            print(f"   [COMPLETE] Thread '{thread_id}' response sent")

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            self._send_error_to_crm(thread_id, sender, channel, str(e))
            if thread_id in self.threads:
                self.threads[thread_id].status = "sleeping"

    def _write_dynamic_context(self, thread_id: str, sender: str, channel: str):
        # Write state.md
        state_content = f"""# Current State

## Session Info
- Thread: {thread_id}
- Timestamp: {datetime.now().isoformat()}
- Channel: {channel}
- Sender: {sender}

## Environment
- Agent: {AGENT_NAME}
- Working Directory: {WORKING_DIR}
"""
        (CONTEXT_DIR / "state.md").write_text(state_content, encoding='utf-8')

        # Write history.md
        history = self._load_history(thread_id)
        if history:
            history_lines = ["# Conversation History\n"]
            history_lines.append(f"Thread: {thread_id}\n")
            history_lines.append(f"Total messages: {len(history)}\n\n")

            for msg in history:
                role = "User" if msg["role"] == "user" else AGENT_NAME
                timestamp = msg.get("timestamp", "")
                content = msg["content"]
                history_lines.append(f"**{role}** ({timestamp}):\n{content}\n\n---\n")

            history_content = "\n".join(history_lines)
        else:
            history_content = "# Conversation History\n\n(No prior history - this is a new conversation)"

        (CONTEXT_DIR / "history.md").write_text(history_content, encoding='utf-8')

        print(f"   [CONTEXT] Dynamic context written (state + {len(history)} history messages)")

    def _run_claude_cli(self, message: str) -> str:
        cmd = [
            "claude",
            "-p", message,
            "--output-format", "text",
            "--allowedTools", "Bash,Edit,Read,Write,Glob,Grep,WebFetch"
        ]

        env = os.environ.copy()
        env[API_KEY_ENV] = CRM_API_KEY

        print(f"   [CLI] Running: claude -p '<message>' in {WORKING_DIR}")

        result = subprocess.run(
            cmd,
            cwd=str(WORKING_DIR),
            env=env,
            capture_output=True,
            text=True,
            shell=True,
            timeout=300
        )

        if result.returncode != 0:
            error_msg = result.stderr or "Unknown error"
            print(f"   [CLI] Error: {error_msg[:200]}")
            raise Exception(f"Claude CLI error: {error_msg}")

        print(f"   [CLI] Success - response length: {len(result.stdout)} chars")
        return result.stdout.strip()

    def _send_to_crm(self, thread_id: str, sender: str, channel: str, response_text: str):
        try:
            payload = {
                "thread_id": thread_id,
                "sender": sender,
                "channel": channel,
                "timestamp": datetime.now().isoformat(),
                "agent": AGENT_NAME,
                "message": {
                    "type": "assistant",
                    "content": [{"type": "text", "text": response_text}]
                }
            }

            response = requests.post(
                f"{CRM_ENDPOINT}/api/agent/stream",
                json=payload,
                headers={"X-API-Key": CRM_API_KEY},
                timeout=5
            )

            if response.status_code != 200:
                print(f"   WARNING: CRM stream failed: {response.status_code}")

            # Send result message
            result_payload = {
                "thread_id": thread_id,
                "sender": sender,
                "channel": channel,
                "timestamp": datetime.now().isoformat(),
                "agent": AGENT_NAME,
                "message": {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "num_turns": 1
                }
            }

            requests.post(
                f"{CRM_ENDPOINT}/api/agent/stream",
                json=result_payload,
                headers={"X-API-Key": CRM_API_KEY},
                timeout=5
            )

        except Exception as e:
            print(f"   WARNING: Failed to send to CRM: {e}")

    def _send_error_to_crm(self, thread_id: str, sender: str, channel: str, error: str):
        try:
            requests.post(
                f"{CRM_ENDPOINT}/api/agent/error",
                json={
                    "thread_id": thread_id,
                    "sender": sender,
                    "channel": channel,
                    "timestamp": datetime.now().isoformat(),
                    "agent": AGENT_NAME,
                    "error": error
                },
                headers={"X-API-Key": CRM_API_KEY},
                timeout=5
            )
        except Exception as e:
            print(f"   WARNING: Failed to send error to CRM: {e}")

    def _load_history(self, thread_id: str) -> List[dict]:
        history_file = THREADS_DIR / f"{thread_id}.json"
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"   WARNING: Failed to load history: {e}")
                return []
        return []

    def _save_message(self, thread_id: str, role: str, content: str):
        history_file = THREADS_DIR / f"{thread_id}.json"
        history = self._load_history(thread_id)

        history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"   WARNING: Failed to save history: {e}")

    def run(self):
        print(f"""
=====================================
  {AGENT_NAME} Agent Listener
=====================================
  Version:     {LISTENER_VERSION}
  Host:        {LISTEN_HOST}
  Port:        {LISTEN_PORT}
  Working Dir: {WORKING_DIR}
  CRM:         {CRM_ENDPOINT}
=====================================
        """)

        # Show CLAUDE.md info
        claude_md = WORKING_DIR / "CLAUDE.md"
        if claude_md.exists():
            content = claude_md.read_text(encoding='utf-8')
            imports = [line.strip() for line in content.split('\n') if line.strip().startswith('@context/')]
            print(f"CLAUDE.md imports: {len(imports)}")
            for imp in imports:
                print(f"  - {imp}")
        else:
            print("WARNING: CLAUDE.md not found in agent/")

        print(f"\nContext files available:")
        for f in CONTEXT_DIR.glob("*.md"):
            print(f"  - {f.name}")

        # Register with CRM (retries if Tailscale not ready yet)
        print(f"\nRegistering with CRM...")
        register_with_crm()

        print(f"\nReady to receive messages.\n")

        self.app.run(
            host=LISTEN_HOST,
            port=LISTEN_PORT,
            debug=False,
            threaded=True
        )


if __name__ == "__main__":
    listener = AgentListener()
    listener.run()
