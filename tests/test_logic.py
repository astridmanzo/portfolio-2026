import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import has_conflict

def test_schedule_conflict_detection():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE jobs (id INTEGER PRIMARY KEY, scheduled_at TEXT, status TEXT)')
    conn.execute("INSERT INTO jobs (scheduled_at,status) VALUES ('2026-03-17T10:00','scheduled')")
    assert has_conflict(conn, '2026-03-17T10:00') is True
    assert has_conflict(conn, '2026-03-17T10:00', job_id=1) is False
    assert has_conflict(conn, '2026-03-17T12:00') is False
