# Agent Package Setup

This is the canonical agent listener package. Drop it on any server and have Claude configure it.

## Quick Start

1. Drop this folder on the target server
2. Run Claude Code in this directory
3. Tell Claude: "Configure this as the [AgentName] agent on port [PORT]"
4. Claude will edit config.json and agent/CLAUDE.md
5. Run: `python listener.py`

## What Claude Should Configure

### 1. config.json

```json
{
  "agent_name": "YOUR_AGENT_NAME",     // e.g., "CRM", "Proto", "Marketing"
  "listen_port": 8080,                  // Unique port for this agent
  "listen_host": "0.0.0.0",            // Usually keep as-is
  "crm_endpoint": "https://crm.actionapi.ca",
  "api_key_env": "ACTO"                // Environment variable with API key
}
```

### 2. agent/CLAUDE.md

The root context file. Must include:
- Agent identity/purpose
- @context/ imports for skills this agent needs

Example:
```markdown
# CRM Agent

You are the CRM Agent for Action/Insight.

@context/identity.md
@context/crm.md
@context/state.md
@context/history.md
```

### 3. agent/context/identity.md

Who this agent is and what it does.

### 4. Additional Skills

Pull skills from CRM after first run:
```
POST /skills/pull
{"name": "crm", "overwrite": true}
```

Or copy skill files into agent/context/

## Prerequisites

- Python 3.8+
- `pip install flask requests`
- Claude CLI: `npm install -g @anthropic-ai/claude-code`
- Environment variable set: `ACTO=<api_key>`
- Network access to CRM (Tailscale or direct)

## Directory Structure

```
agent_package/
├── SETUP.md           # This file
├── config.json        # Agent configuration (edit this)
├── listener.py        # Core listener (don't edit)
├── requirements.txt   # Python deps
└── agent/
    ├── CLAUDE.md      # Root context (edit this)
    ├── context/       # Skill files
    │   ├── identity.md
    │   ├── state.md   # (dynamic, auto-written)
    │   └── history.md # (dynamic, auto-written)
    └── threads/       # Conversation history (auto-created)
```

## Running

```bash
# Install deps
pip install -r requirements.txt

# Set API key
export ACTO=your_api_key  # Linux/Mac
$env:ACTO="your_api_key"  # PowerShell

# Run
python listener.py
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check + version |
| `/version` | GET | Detailed version info |
| `/threads` | GET | List conversation threads |
| `/threads/{id}/history` | GET | Get thread history |
| `/threads/{id}` | DELETE | Delete thread |
| `/message` | POST | Send message to agent |
| `/context` | GET | List context files |
| `/context` | POST | Create context file |
| `/context/{name}` | GET/PUT/DELETE | Manage context file |
| `/claude-md` | GET/PUT | Manage root CLAUDE.md |
| `/skills/available` | GET | List CRM skills |
| `/skills/publish` | POST | Push skill to CRM |
| `/skills/pull` | POST | Pull skill from CRM |
| `/skills/sync` | POST | Sync all to CRM |
| `/update-core` | POST | Update listener code |

## Example Configuration Session

```
User: Configure this as the Marketing agent on port 8083

Claude: I'll configure this agent for you.

[Edits config.json with agent_name="Marketing", listen_port=8083]
[Edits agent/CLAUDE.md with Marketing-specific context]
[Creates agent/context/identity.md with Marketing agent identity]

Done! Run `python listener.py` to start the Marketing agent.
```
