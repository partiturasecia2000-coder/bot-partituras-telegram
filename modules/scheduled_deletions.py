"""Fila persistente de exclusões; independente do JSON de configurações."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time


class DeletionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS deletions (
                chat_id TEXT NOT NULL, message_id INTEGER NOT NULL,
                due_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                PRIMARY KEY(chat_id, message_id))''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def schedule(self, chat_id, message_id, delay):
        with self.connection() as db:
            db.execute('''INSERT INTO deletions(chat_id,message_id,due_at)
                VALUES (?,?,?) ON CONFLICT(chat_id,message_id) DO UPDATE SET
                due_at=excluded.due_at,attempts=0,status='pending',error=NULL''',
                (str(chat_id), message_id, time.time() + delay))

    def due(self, now=None):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM deletions WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT 100",
                (time.time() if now is None else now,))]

    def complete(self, item):
        with self.connection() as db:
            db.execute('DELETE FROM deletions WHERE chat_id=? AND message_id=? AND due_at=?',
                       (item['chat_id'], item['message_id'], item['due_at']))

    def retry(self, item, error, delay, permanent=False):
        attempts = item['attempts'] + 1
        status = 'failed' if permanent or attempts >= 5 else 'pending'
        with self.connection() as db:
            db.execute('''UPDATE deletions SET attempts=?,status=?,error=?,due_at=?
                WHERE chat_id=? AND message_id=? AND due_at=?''',
                (attempts, status, error, time.time()+delay,
                 item['chat_id'], item['message_id'], item['due_at']))

    def counts(self):
        with self.connection() as db:
            return dict(db.execute('SELECT status,COUNT(*) FROM deletions GROUP BY status').fetchall())
