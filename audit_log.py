import json
import os
from datetime import datetime, timezone
from threading import Lock

LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.json")
_lock = Lock()


def _read_all():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _write_all(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def add_entry(entry: dict) -> dict:
    """Append a new structured entry to the audit log. Adds a UTC timestamp."""
    with _lock:
        entries = _read_all()
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        entries.append(entry)
        _write_all(entries)
    return entry


def get_entries(limit: int = 50):
    """Return the most recent `limit` entries, newest first."""
    entries = _read_all()
    return list(reversed(entries))[:limit]


def find_entry(content_id: str):
    """Look up a single entry by content_id. Used by the /appeal endpoint."""
    for e in _read_all():
        if e.get("content_id") == content_id:
            return e
    return None



def update_entry(content_id: str, updates: dict):
    """Merge `updates` into the entry matching content_id. Returns the updated
    entry, or None if content_id wasn't found. Used by /appeal in Milestone 5."""
    with _lock:
        entries = _read_all()
        for e in entries:
            if e.get("content_id") == content_id:
                e.update(updates)
                _write_all(entries)
                return e
    return None