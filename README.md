# Agent Listener Package

Portable agent listener with composable context for Action/Insight agents.

## Quick Start

1. **Copy this folder** to your target server
2. **Edit `config.json`** with your agent settings
3. **Set environment variable**: `ACTO=your_api_key`
4. **Run**: `python deploy.py --start`

## Files

```
agent_package/
├── config.json          # Your agent config (edit this!)
├── deploy.py            # One-click setup script
├── listener.py          # Main listener service
├── requirements.txt     # Python dependencies
└── agent/
    ├── CLAUDE.md        # Root context (uses @context/ imports)
    └── context/
        ├── identity.md  # Agent identity & personality
        ├── crm-api.md   # CRM API reference
        ├── state.md     # (dynamic) Session state
        └── history.md   # (dynamic) Conversation history
```

## Configuration (config.json)

```json
{
  "agent_name": "CRM",
  "listen_port": 8082,
  "listen_host": "0.0.0.0",
  "crm_endpoint": "https://crm.actionapi.ca",
  "api_key_env": "ACTO",
  "description": "CRM Agent - Manages Timeline CRM operations"
}
```

## Prerequisites

- Python 3.8+
- Claude CLI: `npm install -g @anthropic-ai/claude-code`
- Dependencies: `pip install -r requirements.txt`
- `ACTO` environment variable with API key

## Deploy Commands

```bash
# Check prerequisites only
python deploy.py --check

# Configure and verify
python deploy.py

# Configure, verify, and start
python deploy.py --start

# Just run the listener
python listener.py
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/threads` | GET | List all threads |
| `/threads/{id}/history` | GET | Get thread history |
| `/threads/{id}` | DELETE | Delete a thread |
| `/message` | POST | Send message to agent |
| `/context` | GET | Get current CLAUDE.md |
| `/context` | PUT | Update CLAUDE.md |

## How It Works

1. Message arrives at `/message`
2. Listener saves to JSON history
3. Writes dynamic context files (state.md, history.md)
4. Spawns `claude -p "message"` with cwd=agent/
5. Claude reads CLAUDE.md, resolves @context/ imports
6. Response saved to history, streamed to CRM

No command-line limits - history is file-based!
