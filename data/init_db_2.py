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

    # books table: create if not exists (includes status column)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        genre TEXT,
        description TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # If an older DB exists where books table was created without `status`,
    # add the status column now (safe ALTER TABLE ADD COLUMN).
    if not table_has_column(conn, "books", "status"):
        try:
            cur.execute("ALTER TABLE books ADD COLUMN status TEXT DEFAULT 'active';")
            print("Added missing 'status' column to books table.")
        except sqlite3.OperationalError as e:
            # If this fails for some unexpected reason, print warning but continue.
            print("Warning: Failed to add 'status' column:", e)

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
        ("Dune",
         "Frank Herbert",
         "Science Fiction",
         "Epic story of politics, religion, and ecology on the desert planet Arrakis."),

        ("Neuromancer",
         "William Gibson",
         "Science Fiction",
         "Cyberpunk classic that introduced cyberspace and reshaped science fiction."),

        ("The Hobbit",
         "J.R.R. Tolkien",
         "Fantasy",
         "The adventure of Bilbo Baggins as he journeys with dwarves to reclaim treasure from Smaug the dragon."),

        ("Harry Potter and the Sorcerer's Stone",
         "J.K. Rowling",
         "Fantasy",
         "The first story of Harry Potter discovering he is a wizard and attending Hogwarts School of Witchcraft and Wizardry."),

        ("Foundation",
         "Isaac Asimov",
         "Science Fiction",
         "The beginning of Asimov's Foundation saga, about the fall and rebirth of a galactic empire."),

        ("1984",
         "George Orwell",
         "Dystopian",
         "A chilling novel about surveillance, totalitarianism, and loss of individuality."),

        ("Brave New World",
         "Aldous Huxley",
         "Dystopian",
         "A futuristic society driven by technology, pleasure, and control."),

        ("Fahrenheit 451",
         "Ray Bradbury",
         "Dystopian",
         "A fireman burns books in a world where reading is forbidden."),

        ("The Catcher in the Rye",
         "J.D. Salinger", "Classic",
         "Holden Caulfield narrates a story of teenage angst and rebellion."),

        ("To Kill a Mockingbird",
         "Harper Lee", "Classic",
         "A powerful novel on race, justice, and morality in the American South."),

        ("The Lord of the Rings: The Fellowship of the Ring",
         "J.R.R. Tolkien",
         "Fantasy",
         "The first volume of the epic quest to destroy the One Ring."),

        ("Snow Crash",
         "Neal Stephenson",
         "Science Fiction",
         "A fast-paced cyberpunk adventure mixing virtual reality and ancient history."),

        ("The Martian",
         "Andy Weir",
         "Science Fiction",
         "An astronaut stranded on Mars fights to survive using science and ingenuity."),

        ("Ender's Game",
         "Orson Scott Card",
         "Science Fiction",
         "A young boy is trained to lead humanity's fight against alien invaders."),

        ("A Game of Thrones",
         "George R.R. Martin",
         "Fantasy",
         "The first book of A Song of Ice and Fire, filled with intrigue, battles, and betrayal."),

        ("Dracula",
         "Bram Stoker",
         "Horror",
         "The gothic classic that introduced Count Dracula to the world."),

        ("Frankenstein",
         "Mary Shelley",
         "Horror",
         "The story of Victor Frankenstein and the monster he creates."),

        ("The Name of the Wind",
         "Patrick Rothfuss",
         "Fantasy",
         "The tale of Kvothe, a gifted musician and magician, recounting his life story."),
    ]

    # Insert sample books with status = 'active' (explicit for clarity)
    cur.executemany("""
        INSERT INTO books (title, author, genre, description, status)
        VALUES (?, ?, ?, ?, ?)
    """, [(t, a, g, d, "active") for (t, a, g, d) in sample_books])
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
