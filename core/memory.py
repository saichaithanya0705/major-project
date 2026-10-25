"""
Long-term memory: facts the user explicitly asks Jarvis to remember.

Stored locally in SQLite (``JARVIS_MEMORY_PATH``, default
``~/.jarvis/memory.sqlite3``) with full-text search. Nothing is saved without
an explicit "remember ..." request. Relevant memories are added to prompts, so
they reach whichever model answers, including cloud escalation targets.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MAX_MEMORY_CHARS = 500
_WORD = re.compile(r"[A-Za-z0-9]{2,}")
_STOPWORDS = frozenset(
    "the and for are was were you your with that this from have has had what when where which who whom "
    "why how can could would should will about into onto than then them they their there here please "
    "me my mine our ours its it's i'm".split()
)


@dataclass(frozen=True)
class Memory:
    id: int
    text: str
    created_at: str


def default_memory_path() -> Path:
    configured = os.getenv("JARVIS_MEMORY_PATH", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".jarvis" / "memory.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _search_terms(text: str) -> list[str]:
    seen: list[str] = []
    for word in _WORD.findall(text.lower()):
        if word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return seen[:12]


class MemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_memory_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fts = True
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS memories ("
                "id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE COLLATE NOCASE, "
                "created_at TEXT NOT NULL, last_used_at TEXT, uses INTEGER NOT NULL DEFAULT 0)"
            )
            try:
                db.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='id');
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
                    END;
                    """
                )
            except sqlite3.OperationalError:
                # SQLite built without FTS5: fall back to LIKE matching.
                self._fts = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def remember(self, text: str) -> Memory:
        cleaned = " ".join(str(text).split())[:MAX_MEMORY_CHARS].rstrip(" .")
        if not cleaned:
            raise ValueError("Nothing to remember.")
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO memories(text, created_at) VALUES (?, ?)", (cleaned, _now()))
            row = db.execute("SELECT id, text, created_at FROM memories WHERE text = ?", (cleaned,)).fetchone()
        return Memory(row["id"], row["text"], row["created_at"])

    def all(self) -> list[Memory]:
        with self._connect() as db:
            rows = db.execute("SELECT id, text, created_at FROM memories ORDER BY id").fetchall()
        return [Memory(row["id"], row["text"], row["created_at"]) for row in rows]

    def relevant(self, query: str, limit: int = 5) -> list[Memory]:
        terms = _search_terms(query)
        if not terms:
            return []
        with self._connect() as db:
            if self._fts:
                match = " OR ".join(f'"{term}"*' for term in terms)
                rows = db.execute(
                    "SELECT m.id, m.text, m.created_at FROM memories_fts f JOIN memories m ON m.id = f.rowid "
                    "WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) LIMIT ?",
                    (match, limit),
                ).fetchall()
            else:
                clause = " OR ".join("text LIKE ?" for _ in terms)
                rows = db.execute(
                    f"SELECT id, text, created_at FROM memories WHERE {clause} ORDER BY id DESC LIMIT ?",
                    (*[f"%{term}%" for term in terms], limit),
                ).fetchall()
            if rows:
                db.executemany(
                    "UPDATE memories SET uses = uses + 1, last_used_at = ? WHERE id = ?",
                    [(_now(), row["id"]) for row in rows],
                )
        return [Memory(row["id"], row["text"], row["created_at"]) for row in rows]

    def forget(self, query: str) -> list[Memory]:
        """Delete memories matching every search term in ``query``."""
        terms = _search_terms(query)
        if not terms:
            return []
        matches = [memory for memory in self.all() if all(term in memory.text.lower() for term in terms)]
        with self._connect() as db:
            db.executemany("DELETE FROM memories WHERE id = ?", [(memory.id,) for memory in matches])
        return matches

    def clear(self) -> int:
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            db.execute("DELETE FROM memories")
        return int(count)


def memory_prompt_block(store: MemoryStore, user_prompt: str, limit: int = 5) -> str:
    memories = store.relevant(user_prompt, limit=limit)
    if not memories:
        return ""
    return (
        "\n# Things the user asked you to remember\n"
        "Use these if they are relevant to the request; do not mention them otherwise.\n"
        + "\n".join(f"- {memory.text}" for memory in memories)
        + "\n"
    )


_REMEMBER = re.compile(
    r"^\s*(?:(?:hey\s+)?jarvis[,:]?\s+)?(?:please\s+)?(?:remember|note)(?!\s+(?:when|how|what|who|where|why|if|the time)\b)"
    r"(?:\s+that)?\s*[:,-]?\s+(?P<fact>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_FORGET_ALL = re.compile(r"^\s*(?:please\s+)?forget\s+(?:everything|all)(?:\s+you\s+(?:remember|know))?(?:\s+about\s+me)?\W*$", re.IGNORECASE)
_FORGET = re.compile(r"^\s*(?:please\s+)?forget(?:\s+(?:that|about))?\s+(?P<query>.+)$", re.IGNORECASE | re.DOTALL)
_LIST = re.compile(
    r"^\s*(?:what\s+do\s+you\s+remember(?:\s+about\s+me)?|(?:show|list)\s+(?:me\s+)?(?:my|your|all)\s+memories|what\s+have\s+i\s+asked\s+you\s+to\s+remember)\W*$",
    re.IGNORECASE,
)


def handle_memory_command(text: str, store: MemoryStore | None = None) -> str | None:
    """Reply for a remember/forget/list command, or None if ``text`` is not one."""
    message = (text or "").strip()
    if not message:
        return None
    if _LIST.match(message):
        memories = (store or MemoryStore()).all()
        if not memories:
            return "I'm not remembering anything yet. Say \"remember that ...\" to add something."
        return "Here's what I remember:\n" + "\n".join(f"- {memory.text}" for memory in memories)
    if _FORGET_ALL.match(message):
        count = (store or MemoryStore()).clear()
        return f"Done. I forgot {count} thing{'s' if count != 1 else ''}."
    forget = _FORGET.match(message)
    if forget:
        removed = (store or MemoryStore()).forget(forget.group("query"))
        if not removed:
            return "I couldn't find anything like that in my memory."
        return "Forgotten:\n" + "\n".join(f"- {memory.text}" for memory in removed)
    remember = _REMEMBER.match(message)
    if remember:
        fact = remember.group("fact").strip()
        memory = (store or MemoryStore()).remember(fact)
        return f"Got it. I'll remember: {memory.text}"
    return None
