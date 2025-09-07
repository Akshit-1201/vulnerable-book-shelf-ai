#!/usr/bin/env python3
"""
data/init_db.py

Initializes the SQLite database for Vulnerable Book Shelf (version-2).

- Creates ../data/database.db (relative to project root)
- Creates tables: users (with role), books
- Seeds an admin user with plaintext password (INTENTIONAL for vulnerability demo)
- Seeds a handful of sample books (if not already present)

Usage:
    python data/init_db.py
"""

import os
import sqlite3
from pathlib import Path

# Database path (relative to repository root)
DATA_DIR = Path(__file__).resolve().parent
DB_FILE = DATA_DIR / "database.db"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

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

    # books table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        genre TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()

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

def seed_sample_books(conn: sqlite3.Connection):
    cur = conn.cursor()
    # Simple idempotent check: if there's at least one book, assume seeded
    cur.execute("SELECT COUNT(1) as c FROM books;")
    row = cur.fetchone()
    if row and row["c"] > 0:
        print("Books table already has entries — skipping sample book seed.")
        return

    sample_books = [
        ("The Pragmatic Programmer", "Andrew Hunt & David Thomas", "Software", "Classic software engineering best practices."),
        ("Clean Code", "Robert C. Martin", "Software", "A handbook of agile software craftsmanship."),
        ("Designing Data-Intensive Applications", "Martin Kleppmann", "Data", "Principles of reliable, scalable systems."),
        ("Deep Work", "Cal Newport", "Self-help", "Rules for focused success in a distracted world."),
    ]

    cur.executemany("""
        INSERT INTO books (title, author, genre, description)
        VALUES (?, ?, ?, ?)
    """, sample_books)
    conn.commit()
    print(f"Seeded {len(sample_books)} sample books.")

def main():
    print("Initializing database at:", DB_FILE)
    conn = connect()
    try:
        create_tables(conn)
        seed_admin(conn)
        seed_sample_books(conn)
        print("Initialization complete.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
