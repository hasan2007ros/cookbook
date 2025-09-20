import sqlite3

# Connect to or create the database
conn = sqlite3.connect('cookbook.db')
c = conn.cursor()

# Create the users table
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    email TEXT NOT NULL UNIQUE,
    occupation TEXT,
    dish_choice TEXT,
    diets TEXT,
    bio TEXT,
    password_hash TEXT NOT NULL
)
''')

conn.commit()
conn.close()
print("✅ users table created.")
