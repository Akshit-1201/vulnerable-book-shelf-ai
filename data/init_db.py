import os
import sqlite3
from pathlib import Path
from typing import Optional

# Database path (this file is located in the "data" directory)
DATA_DIR = Path(__file__).resolve().parent
DB_FILE = DATA_DIR / "database.db"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a sqlite3 connection with row factory set."""
    db = db_path or DB_FILE
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table});")
    cols = [r[1] for r in cur.fetchall()]
    return column in cols


def create_tables(conn: sqlite3.Connection):
    cur = conn.cursor()

    # users table with role column (default 'user')
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT UNIQUE,
        password TEXT,
        phone_number TEXT,
        role TEXT DEFAULT 'user'
    );
    """)


def seed_admin(conn: sqlite3.Connection):
    cur = conn.cursor()
    # Check if admin already exists by email
    cur.execute("SELECT id FROM users WHERE email = ?", ("admin@example.com",))
    if cur.fetchone():
        print("Admin user already exists — skipping admin seed.")
        return

    # Intentionally storing plaintext password for the vulnerable demo
    cur.execute("""
        INSERT INTO users (username, email, password, phone_number, role)
        VALUES (?, ?, ?, ?, ?)
    """, ("admin", "admin@example.com", "admin123", "0000000000", "admin"))
    conn.commit()
    print("Seeded admin user: admin@example.com / admin123 (plaintext)")


def main():
    print("Initializing database at:", DB_FILE)
    conn = connect()
    try:
        create_tables(conn)
        seed_admin(conn)
        print("Initialization complete.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
