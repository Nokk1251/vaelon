"""Long-term memory: SQLite, ENCRYPTED at rest (AES-256-GCM via security/vault.py).

Text is stored encrypted; full-text search runs over a blind index (HMAC tokens), so the database file never
contains your words in readable form. Secrets are redacted before storage. Wipe anytime.
Older plaintext databases are migrated automatically on first open.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time

from . import config
from .security import vault
from .security.redact import redact



def _open(stored: str) -> str | None:
    """One stored memory, or None when it cannot be opened (damaged / not encrypted) - one bad row never breaks a
    search."""
    try:
        return vault.decrypt_text(stored)
    except Exception:
        return None

class Memory:
    def __init__(self, path=None):
        config.HOME.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path or config.HOME / "memory.db"), check_same_thread=False)
        self.lock = threading.Lock()  # one connection shared by the API threads and background reflection
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS mem(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT)")
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mem_idx USING fts5(tokens)")
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        self.db.execute("DROP TABLE IF EXISTS mem_fts")  # old plaintext index from earlier versions
        self.db.commit()
        self._migrate()

    def _index(self, row_id: int, text: str) -> None:
        if self.fts:
            self.db.execute("DELETE FROM mem_idx WHERE rowid=?", (row_id,))
            self.db.execute("INSERT INTO mem_idx(rowid,tokens) VALUES(?,?)", (row_id, " ".join(vault.blind_tokens(text))))

    def _migrate(self) -> None:
        """ONCE (database version 0 -> 1): rows from versions that stored memory in plain text get encrypted. After
        that a plain row is never trusted again - it is dropped (it could only have been planted into the file)."""
        if not vault.available():
            return
        with self.lock:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            rows = self.db.execute("SELECT id,text FROM mem WHERE text NOT LIKE ?", (vault.PREFIX + "%",)).fetchall()
            for row_id, text in rows:
                if version >= 1:
                    self.db.execute("DELETE FROM mem WHERE id=?", (row_id,))
                    if self.fts:
                        self.db.execute("DELETE FROM mem_idx WHERE rowid=?", (row_id,))
                    continue
                self.db.execute("UPDATE mem SET text=? WHERE id=?", (vault.encrypt_text(text), row_id))
                self._index(row_id, text)
            if self.fts and self.db.execute("SELECT count(*) FROM mem_idx").fetchone()[0] == 0:
                for row_id, enc in self.db.execute("SELECT id,text FROM mem").fetchall():
                    plain = _open(enc)
                    if plain is not None:
                        self._index(row_id, plain)
            if version < 1:
                self.db.execute("PRAGMA user_version = 1")
            self.db.commit()

    def add(self, text: str, kind: str = "fact") -> int:
        text = redact(text.strip())
        with self.lock:
            cur = self.db.execute("INSERT INTO mem(ts,kind,text) VALUES(?,?,?)",
                                  (time.time(), kind, vault.encrypt_text(text)))
            self._index(cur.lastrowid, text)
            self.db.commit()
            return cur.lastrowid

    def search(self, query: str, limit: int = 8) -> list[tuple[int, str]]:
        if not re.search(r"\w", query):
            return []
        with self.lock:
            if self.fts:
                toks = vault.blind_tokens(query)
                if not toks:
                    return []
                rows = self.db.execute(
                    "SELECT m.id,m.text FROM mem_idx i JOIN mem m ON m.id=i.rowid WHERE mem_idx MATCH ? "
                    "ORDER BY rank LIMIT ?", (" OR ".join(toks), limit)).fetchall()
                return [(i, p) for i, p in ((i, _open(t)) for i, t in rows) if p is not None]
            words = [w.lower() for w in re.findall(r"\w+", query)]
            rows = [(i, p) for i, p in ((i, _open(t)) for i, t in self.db.execute("SELECT id,text FROM mem").fetchall())
                    if p is not None]
        return [(i, t) for i, t in rows if any(w in t.lower() for w in words)][:limit]

    def forget(self, mem_id: int) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM mem WHERE id=?", (mem_id,))
            if self.fts:
                self.db.execute("DELETE FROM mem_idx WHERE rowid=?", (mem_id,))
            self.db.commit()
            return cur.rowcount > 0

    def wipe(self) -> None:
        with self.lock:
            self.db.execute("DELETE FROM mem")
            if self.fts:
                self.db.execute("DELETE FROM mem_idx")
            self.db.commit()
            self.db.execute("VACUUM")  # really remove the old pages from disk

    def recent(self, n: int = 20, kind: str | None = None):
        with self.lock:
            if kind:
                rows = self.db.execute("SELECT id,text FROM mem WHERE kind=? ORDER BY id DESC LIMIT ?",
                                       (kind, n)).fetchall()
            else:
                rows = self.db.execute("SELECT id,text FROM mem ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [(i, p) for i, p in ((i, _open(t)) for i, t in rows) if p is not None]

    def stats(self) -> dict:
        with self.lock:
            rows = self.db.execute("SELECT kind, count(*) FROM mem GROUP BY kind").fetchall()
        return {k: n for k, n in rows}


class NullMemory:
    """Company mode, a person who is not the owner: remembers nothing and reveals nothing of the owner's memory."""

    def add(self, text: str, kind: str = "fact") -> int:
        return 0

    def search(self, query: str, limit: int = 8) -> list:
        return []

    def recent(self, n: int = 20, kind: str | None = None) -> list:
        return []

    def stats(self) -> dict:
        return {}

    def __getattr__(self, name):  # anything else the owner's memory can do: quietly nothing
        return lambda *a, **k: None
