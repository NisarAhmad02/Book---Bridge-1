"""Book Bridge - database layer (SQLite).

All queries use parameter placeholders (?) so user input is never
concatenated into SQL, which protects against SQL injection.
"""
import os
import sqlite3
from datetime import datetime

from flask import g
from flask_login import UserMixin
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "bookbridge.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")

CATEGORIES = [
    "School textbooks",
    "Intermediate textbooks",
    "Engineering textbooks",
    "Degree textbooks",
    "Competitive examination books",
    "Reference books",
    "General Knowledge books",
    "Storybooks",
    "Dictionaries",
    "Other educational books",
]

CATEGORY_ICONS = {
    "School textbooks": "bi-backpack2",
    "Intermediate textbooks": "bi-journal-text",
    "Engineering textbooks": "bi-gear-wide-connected",
    "Degree textbooks": "bi-mortarboard",
    "Competitive examination books": "bi-trophy",
    "Reference books": "bi-bookmarks",
    "General Knowledge books": "bi-globe-europe-africa",
    "Storybooks": "bi-book-half",
    "Dictionaries": "bi-alphabet-uppercase",
    "Other educational books": "bi-collection",
}

EDUCATION_LEVELS = [
    "School (Class 1-10)",
    "Intermediate (Class 11-12)",
    "Diploma",
    "Engineering (B.Tech / B.E.)",
    "Degree (UG)",
    "Postgraduate",
    "Competitive Exams",
    "All levels",
]

CONDITIONS = ["Like New", "Good", "Fair", "Worn but readable"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('donor','student','admin')),
    phone TEXT,
    city TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    icon TEXT
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    education_level TEXT NOT NULL,
    condition TEXT NOT NULL,
    description TEXT,
    image TEXT,
    donor_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','available','reserved','distributed','rejected')),
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS donations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL UNIQUE REFERENCES books(id),
    donor_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected')),
    admin_note TEXT,
    submitted_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS book_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','distributed','cancelled')),
    admin_note TEXT,
    requested_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS distributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL UNIQUE REFERENCES book_requests(id),
    book_id INTEGER NOT NULL REFERENCES books(id),
    student_id INTEGER NOT NULL REFERENCES users(id),
    method TEXT NOT NULL,
    notes TEXT,
    distributed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(id),
    book_id INTEGER REFERENCES books(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
CREATE INDEX IF NOT EXISTS idx_requests_student ON book_requests(student_id);
CREATE INDEX IF NOT EXISTS idx_requests_book ON book_requests(book_id);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------- connection
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


# ----------------------------------------------------------------- user model
class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]
        self.phone = row["phone"]
        self.city = row["city"]
        self._active = bool(row["is_active"])

    @property
    def is_active(self):  # Flask-Login uses this to block disabled accounts
        return self._active

    @staticmethod
    def get(user_id):
        row = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
        return User(row) if row else None


# ----------------------------------------------------------------- setup/seed
def init_db():
    """Create tables, categories and demo data (only if the DB is empty)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for name in CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, icon) VALUES (?, ?)",
            (name, CATEGORY_ICONS.get(name)),
        )
    conn.commit()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_demo_data(conn)
    conn.close()


def _make_cover(path, title, author, color):
    """Create a simple placeholder cover image for demo books with Pillow."""
    from PIL import Image, ImageDraw

    w, h = 480, 640
    img = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 28, h], fill=(0, 0, 0))
    d.rectangle([28, 0, 34, h], fill=(255, 255, 255))
    d.rectangle([60, 80, w - 40, 84], fill=(255, 255, 255))
    d.rectangle([60, h - 120, w - 40, h - 116], fill=(255, 255, 255))

    def wrap(text, width):
        words, lines, cur = text.split(), [], ""
        for word in words:
            if len(cur) + len(word) + 1 > width:
                lines.append(cur)
                cur = word
            else:
                cur = (cur + " " + word).strip()
        if cur:
            lines.append(cur)
        return lines

    y = 130
    for line in wrap(title.upper(), 16):
        d.text((64, y), line, fill=(255, 255, 255))
        y += 22
    d.text((64, h - 100), author[:28], fill=(230, 240, 255))
    d.text((64, h - 60), "DEMO COVER - Book Bridge", fill=(200, 230, 210))
    img.save(path, "JPEG", quality=85)


def seed_demo_data(conn):
    t = now()
    cat = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}

    users = [
        ("Demo Admin", "admin@bookbridge.demo", "Admin@Demo123", "admin", "9000000001", "Hyderabad"),
        ("Demo Donor", "donor@bookbridge.demo", "Donor@Demo123", "donor", "9000000002", "Hyderabad"),
        ("Demo Student", "student@bookbridge.demo", "Student@Demo123", "student", "9000000003", "Warangal"),
    ]
    for name, email, pw, role, phone, city in users:
        conn.execute(
            "INSERT INTO users (name,email,password_hash,role,phone,city,is_demo,created_at) "
            "VALUES (?,?,?,?,?,?,1,?)",
            (name, email, generate_password_hash(pw), role, phone, city, t),
        )
    donor_id = conn.execute("SELECT id FROM users WHERE email='donor@bookbridge.demo'").fetchone()[0]
    student_id = conn.execute("SELECT id FROM users WHERE email='student@bookbridge.demo'").fetchone()[0]

    books = [
        ("Mathematics for Class 10", "NCERT Team", "School textbooks", "School (Class 1-10)", "Good",
         "Class 10 maths textbook with solved examples. Few pencil marks.", "available", (30, 90, 160)),
        ("Physics Part 1 - Class 11", "H. C. Verma", "Intermediate textbooks", "Intermediate (Class 11-12)", "Like New",
         "Concepts of Physics, Part 1. Clean pages, no missing sheets.", "available", (20, 110, 90)),
        ("Engineering Mathematics", "B. S. Grewal", "Engineering textbooks", "Engineering (B.Tech / B.E.)", "Good",
         "Higher Engineering Mathematics. Useful for first and second year.", "available", (15, 40, 90)),
        ("Data Structures using C", "Reema Thareja", "Engineering textbooks", "Engineering (B.Tech / B.E.)", "Fair",
         "Some highlighted notes. All chapters intact.", "available", (60, 80, 140)),
        ("Quantitative Aptitude", "R. S. Aggarwal", "Competitive examination books", "Competitive Exams", "Good",
         "Popular preparation book for bank and government exams.", "available", (150, 70, 40)),
        ("Oxford Advanced Learner's Dictionary", "Oxford Press", "Dictionaries", "All levels", "Good",
         "Hardcover English dictionary, spine in good condition.", "available", (90, 50, 120)),
        ("Wings of Fire", "A. P. J. Abdul Kalam", "General Knowledge books", "All levels", "Like New",
         "Autobiography - inspiring reading for every student.", "available", (180, 90, 20)),
        ("Panchatantra Stories", "Vishnu Sharma", "Storybooks", "School (Class 1-10)", "Good",
         "Illustrated story collection for young readers.", "pending", (40, 130, 70)),
    ]
    for i, (title, author, cname, level, cond, desc, status, color) in enumerate(books, start=1):
        fname = f"demo_{i}.jpg"
        _make_cover(os.path.join(UPLOAD_DIR, fname), title, author, color)
        cur = conn.execute(
            "INSERT INTO books (title,author,category_id,education_level,condition,description,image,"
            "donor_id,status,is_demo,created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
            (title, author, cat[cname], level, cond, desc, fname, donor_id, status, t),
        )
        dstatus = "approved" if status == "available" else "pending"
        conn.execute(
            "INSERT INTO donations (book_id,donor_id,status,submitted_at,reviewed_at) VALUES (?,?,?,?,?)",
            (cur.lastrowid, donor_id, dstatus, t, t if dstatus == "approved" else None),
        )

    # one demo request + one finished distribution so dashboards/reports show data
    conn.execute(
        "INSERT INTO book_requests (book_id,student_id,reason,status,requested_at,reviewed_at) "
        "VALUES (6,?,?,?,?,?)",
        (student_id, "Need a dictionary for my English course.", "distributed", t, t),
    )
    conn.execute("UPDATE books SET status='distributed' WHERE id=6")
    conn.execute(
        "INSERT INTO distributions (request_id,book_id,student_id,method,notes,distributed_at) "
        "VALUES (1,6,?,?,?,?)",
        (student_id, "Hand-over at college", "Demo distribution record", t),
    )
    conn.execute(
        "INSERT INTO book_requests (book_id,student_id,reason,status,requested_at) VALUES (5,?,?,?,?)",
        (student_id, "Preparing for bank exams, cannot afford new books.", "pending", t),
    )
    conn.execute(
        "INSERT INTO feedback (student_id,book_id,rating,comment,created_at) VALUES (?,?,?,?,?)",
        (student_id, 6, 5, "Demo feedback: the dictionary was in great shape. Thank you, Book Bridge!", t),
    )
    conn.commit()
