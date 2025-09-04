import sqlite3

conn = sqlite3.connect("database.db")
c = conn.cursor()

# Drop old tables
c.execute("DROP TABLE IF EXISTS users;")
c.execute("DROP TABLE IF EXISTS books;")

# Users Tables
c.execute("""
          CREATE TABLE users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL,
              email TEXT NOT NULL,
              password TEXT NOT NULL,
              phone_number TEXT
          );
""")

# Books Table
c.execute("""
          CREATE TABLE books (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              author TEXT NOT NULL,
              genre TEXT,
              year INTEGER
        );
""")

# Insert Demo Users
c.executemany("""
              INSERT INTO users (username, email, password, phone_number)
              VALUES (?,?,?,?)
              """, [
                  ('alice', 'alice@xyz.com', 'password123', '1234567890'),
                  ('bob', 'bob@xyz.com', 'secretpass', '9876543210')
              ])

# Insert Demo Books
c.executemany("""
              INSERT INTO books (title, author, genre, year)
              VALUES (?, ?, ?, ?)
              """, [
                  ("Dune", "Frank Herbert", "Science Fiction", 1965),
                  ("Neuromancer", "William Gibson", "Science Fiction", 1984),
                  ("The Hobbit", "J.R.R. Tolkien", "Fantasy", 1937),
                  ("Harry Potter and the Sorcerer's Stone", "J.K. Rowling", "Fantasy", 1997),
                  ("Foundation", "Isaac Asimov", "Science Fiction", 1951)
              ])

conn.commit()
conn.close()

print("Database initialized with sample data")