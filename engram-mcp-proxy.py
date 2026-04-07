#!/usr/bin/env python3
"""
Engram MCP Remote Proxy
=======================
MCP stdio server that forwards all engram tools to a remote HTTP API.
Replaces the local `engram mcp` command so both Mac and VPS share memory.

Usage:
  ENGRAM_REMOTE_URL=https://engram.example.com python3 engram-mcp-proxy.py

Configure in .claude/settings.json or MCP config:
  {
    "mcpServers": {
      "engram": {
        "command": "python3",
        "args": ["/path/to/engram-mcp-proxy.py"],
        "env": { "ENGRAM_REMOTE_URL": "https://engram.example.com" }
      }
    }
  }
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
import uuid
from datetime import datetime, timezone

REMOTE_URL = os.environ.get("ENGRAM_REMOTE_URL", "http://localhost:7437").rstrip("/")

# --- HTTP helpers ---

def http_get(path, params=None):
    url = f"{REMOTE_URL}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url += f"?{qs}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def http_post(path, body):
    url = f"{REMOTE_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def http_patch(path, body):
    url = f"{REMOTE_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="PATCH")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def http_delete(path):
    url = f"{REMOTE_URL}{path}"
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# --- Tool implementations (MCP tool name -> HTTP call) ---

_ensured_sessions = set()


def ensure_session(session_id, project=""):
    """Create session if it doesn't exist yet (idempotent per process)."""
    if session_id in _ensured_sessions:
        return
    try:
        http_post("/sessions", {"id": session_id, "project": project, "directory": ""})
    except urllib.error.HTTPError as e:
        # 409 Conflict = session already exists, that's fine
        if e.code != 409:
            pass  # best-effort, don't block the save
    _ensured_sessions.add(session_id)


def mem_save(args):
    session_id = args.get("session_id", f"remote-{datetime.now(timezone.utc).strftime('%Y%m%d')}")
    ensure_session(session_id, args.get("project", ""))
    body = {
        "session_id": session_id,
        "type": args.get("type", "manual"),
        "title": args["title"],
        "content": args["content"],
        "project": args.get("project"),
        "scope": args.get("scope", "project"),
        "topic_key": args.get("topic_key"),
    }
    result = http_post("/observations", body)
    obs_id = result.get("id", "?")
    return f'Memory saved: "{args["title"]}" ({args.get("type", "manual")})'


def mem_search(args):
    params = {
        "q": args["query"],
        "type": args.get("type"),
        "project": args.get("project"),
        "scope": args.get("scope"),
        "limit": str(args.get("limit", 10)),
    }
    results = http_get("/search", params)
    if not results:
        return f'No memories found for: "{args["query"]}"'
    lines = []
    for r in results:
        title = r.get("title", "untitled")
        typ = r.get("type", "?")
        content = r.get("content", "")[:200]
        lines.append(f"- [{typ}] **{title}**: {content}")
    return "\n".join(lines)


def mem_context(args):
    params = {
        "project": args.get("project"),
        "scope": args.get("scope"),
    }
    return http_get("/context", params)


def mem_get_observation(args):
    obs_id = args["observation_id"]
    return http_get(f"/observations/{obs_id}")


def mem_update(args):
    obs_id = args["observation_id"]
    body = {}
    for field in ["title", "content", "type", "project", "scope", "topic_key"]:
        if field in args:
            body[field] = args[field]
    return http_patch(f"/observations/{obs_id}", body)


def mem_delete(args):
    obs_id = args["observation_id"]
    return http_delete(f"/observations/{obs_id}")


def mem_suggest_topic_key(args):
    typ = args.get("type", "manual")
    title = args.get("title", "")
    families = {
        "architecture": "architecture",
        "decision": "decision",
        "bugfix": "bug",
        "pattern": "pattern",
        "config": "config",
        "discovery": "discovery",
        "learning": "learning",
    }
    family = families.get(typ, typ)
    slug = title.lower().strip()
    slug = slug.replace(" ", "-")
    for ch in ".,;:!?'\"()[]{}":
        slug = slug.replace(ch, "")
    return f"{family}/{slug}"


def mem_session_start(args):
    body = {
        "id": args.get("session_id", str(uuid.uuid4())),
        "project": args.get("project", ""),
        "directory": args.get("directory", ""),
    }
    return http_post("/sessions", body)


def mem_session_end(args):
    session_id = args["session_id"]
    body = {"summary": args.get("summary", "")}
    return http_post(f"/sessions/{session_id}/end", body)


def mem_session_summary(args):
    session_id = args.get("session_id", f"remote-{datetime.now(timezone.utc).strftime('%Y%m%d')}")
    ensure_session(session_id, args.get("project", ""))
    body = {
        "session_id": session_id,
        "type": "session_summary",
        "title": args.get("title", "Session Summary"),
        "content": args.get("content", ""),
        "project": args.get("project"),
        "scope": args.get("scope", "project"),
        "topic_key": args.get("topic_key"),
    }
    return http_post("/observations", body)


def mem_save_prompt(args):
    body = {
        "session_id": args.get("session_id", f"remote-{datetime.now(timezone.utc).strftime('%Y%m%d')}"),
        "content": args["content"],
        "project": args.get("project"),
    }
    return http_post("/prompts", body)


def mem_capture_passive(args):
    body = {
        "content": args["content"],
    }
    return http_post("/observations/passive", body)


def mem_stats(args):
    return http_get("/stats")


def mem_timeline(args):
    params = {
        "observation_id": str(args["observation_id"]),
        "before": str(args.get("before", 5)),
        "after": str(args.get("after", 5)),
    }
    return http_get("/timeline", params)


# --- Tool registry ---

TOOLS = {
    "mem_save": {
        "fn": mem_save,
        "description": "Save an important observation to persistent memory. Call this PROACTIVELY after completing significant work.",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short, searchable title"},
                "content": {"type": "string", "description": "Structured content using **What**, **Why**, **Where**, **Learned** format"},
                "type": {"type": "string", "description": "Category: decision, architecture, bugfix, pattern, config, discovery, learning"},
                "project": {"type": "string", "description": "Project name"},
                "scope": {"type": "string", "description": "Scope: project (default) or personal"},
                "session_id": {"type": "string", "description": "Session ID"},
                "topic_key": {"type": "string", "description": "Topic key for upserts (e.g. architecture/auth-model)"},
            },
            "required": ["title", "content"],
        },
    },
    "mem_search": {
        "fn": mem_search,
        "description": "Search persistent memory across all sessions.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "type": {"type": "string", "description": "Filter by type"},
                "project": {"type": "string", "description": "Filter by project"},
                "scope": {"type": "string", "description": "Filter by scope: project or personal"},
                "limit": {"type": "number", "description": "Max results (default: 10)"},
            },
            "required": ["query"],
        },
    },
    "mem_context": {
        "fn": mem_context,
        "description": "Get recent memory context from previous sessions.",
        "schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Filter by project"},
                "scope": {"type": "string", "description": "Filter by scope"},
                "limit": {"type": "number", "description": "Number of observations to retrieve"},
            },
        },
    },
    "mem_get_observation": {
        "fn": mem_get_observation,
        "description": "Get full untruncated content of a specific observation by ID.",
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "number", "description": "Observation ID"},
            },
            "required": ["observation_id"],
        },
    },
    "mem_update": {
        "fn": mem_update,
        "description": "Update an observation by ID.",
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "number", "description": "Observation ID"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "type": {"type": "string"},
                "project": {"type": "string"},
                "scope": {"type": "string"},
                "topic_key": {"type": "string"},
            },
            "required": ["observation_id"],
        },
    },
    "mem_delete": {
        "fn": mem_delete,
        "description": "Delete an observation by ID (soft delete).",
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "number", "description": "Observation ID"},
            },
            "required": ["observation_id"],
        },
    },
    "mem_suggest_topic_key": {
        "fn": mem_suggest_topic_key,
        "description": "Suggest a stable topic_key from type + title for upserts.",
        "schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["type", "title"],
        },
    },
    "mem_session_start": {
        "fn": mem_session_start,
        "description": "Register the start of a new coding session.",
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "project": {"type": "string"},
                "directory": {"type": "string"},
            },
        },
    },
    "mem_session_end": {
        "fn": mem_session_end,
        "description": "Mark a session as completed.",
        "schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to end"},
                "summary": {"type": "string", "description": "Session summary"},
            },
            "required": ["session_id"],
        },
    },
    "mem_session_summary": {
        "fn": mem_session_summary,
        "description": "Save comprehensive end-of-session summary.",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string", "description": "Summary with Goal, Discoveries, Accomplished, Next Steps"},
                "project": {"type": "string"},
                "scope": {"type": "string"},
                "session_id": {"type": "string"},
                "topic_key": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    "mem_save_prompt": {
        "fn": mem_save_prompt,
        "description": "Save user prompts for future context.",
        "schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "session_id": {"type": "string"},
                "project": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    "mem_capture_passive": {
        "fn": mem_capture_passive,
        "description": "Extract learnings from text content.",
        "schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Text containing learnings to extract"},
            },
            "required": ["content"],
        },
    },
    "mem_stats": {
        "fn": mem_stats,
        "description": "Show memory system statistics.",
        "schema": {"type": "object", "properties": {}},
    },
    "mem_timeline": {
        "fn": mem_timeline,
        "description": "Chronological context around a specific observation.",
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "number", "description": "Observation ID"},
                "before": {"type": "number", "description": "Observations before (default: 5)"},
                "after": {"type": "number", "description": "Observations after (default: 5)"},
            },
            "required": ["observation_id"],
        },
    },
}


# --- MCP Protocol (JSON-RPC over stdio) ---

def send(msg):
    raw = json.dumps(msg)
    sys.stdout.write(raw + "\n")
    sys.stdout.flush()


def handle_initialize(req):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "engram-remote-proxy", "version": "1.0.0"},
    }


def handle_tools_list(req):
    tools = []
    for name, spec in TOOLS.items():
        tools.append({
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["schema"],
        })
    return {"tools": tools}


def handle_tools_call(req):
    params = req.get("params", {})
    tool_name = params.get("name")
    tool_args = params.get("arguments", {})

    if tool_name not in TOOLS:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            "isError": True,
        }

    try:
        result = TOOLS[tool_name]["fn"](tool_args)
        if isinstance(result, (dict, list)):
            text = json.dumps(result, indent=2, ensure_ascii=False)
        else:
            text = str(result)
        return {"content": [{"type": "text", "text": text}]}
    except urllib.error.URLError as e:
        return {
            "content": [{"type": "text", "text": f"Connection error to {REMOTE_URL}: {e}"}],
            "isError": True,
        }
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error in {tool_name}: {e}"}],
            "isError": True,
        }


HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        req_id = req.get("id")

        # Notifications (no id) — just acknowledge
        if req_id is None:
            if method == "notifications/initialized":
                pass
            continue

        handler = HANDLERS.get(method)
        if handler:
            result = handler(req)
            send({"jsonrpc": "2.0", "id": req_id, "result": result})
        else:
            send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


if __name__ == "__main__":
    main()
