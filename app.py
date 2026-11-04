"""Book Bridge - Used Book Collection and Distribution System (Flask app)."""
import csv
import hmac
import io
import os
import re
import secrets
import uuid
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

import models
from models import (CATEGORIES, CONDITIONS, EDUCATION_LEVELS, User, execute,
                    init_db, now, query)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _load_secret_key():
    """Use SECRET_KEY from the environment, else a key persisted in database/."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(os.path.join(BASE_DIR, "database"), exist_ok=True)
    path = os.path.join(BASE_DIR, "database", "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_secret_key(),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # 5 MB upload cap
    UPLOAD_FOLDER=models.UPLOAD_DIR,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
app.teardown_appcontext(models.close_db)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


# --------------------------------------------------------------------- CSRF
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(24)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token  # also usable inside imported macros


@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="Security token missing or invalid. Please go back, refresh the page and try again.")


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


@app.context_processor
def inject_globals():
    pending_admin = 0
    if current_user.is_authenticated and current_user.role == "admin":
        pending_admin = (
            query("SELECT COUNT(*) c FROM donations WHERE status='pending'", one=True)["c"]
            + query("SELECT COUNT(*) c FROM book_requests WHERE status='pending'", one=True)["c"]
        )
    return {
        "csrf_token": csrf_token,
        "all_categories": query("SELECT * FROM categories ORDER BY id"),
        "pending_admin": pending_admin,
    }


# --------------------------------------------------------------------- helpers
def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def is_safe_redirect(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/") and not target.startswith("//")


def save_image(file_storage):
    """Validate an uploaded image, re-encode it with Pillow and return the stored name.

    Raises ValueError with a user-friendly message if the file is not acceptable.
    """
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Image must be a PNG, JPG, JPEG or WEBP file.")
    try:
        img = Image.open(file_storage.stream)
        img.verify()  # detects truncated / fake image files
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError("The uploaded file is not a valid image.")
    img.thumbnail((900, 900))
    name = f"{uuid.uuid4().hex}.jpg"  # random server-side name, never the user's filename
    img.save(os.path.join(app.config["UPLOAD_FOLDER"], name), "JPEG", quality=85, optimize=True)
    return name


def clean(value, max_len=500):
    return (value or "").strip()[:max_len]


def password_problem(pw):
    if len(pw) < 8:
        return "Password must be at least 8 characters long."
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        return "Password must contain both letters and numbers."
    return None


def get_stats():
    q = lambda sql: query(sql, one=True)["c"]
    return {
        "books_donated": q("SELECT COUNT(*) c FROM books WHERE status IN ('available','reserved','distributed')"),
        "books_available": q("SELECT COUNT(*) c FROM books WHERE status='available'"),
        "books_distributed": q("SELECT COUNT(*) c FROM distributions"),
        "students_helped": q("SELECT COUNT(DISTINCT student_id) c FROM distributions"),
        "donors": q("SELECT COUNT(*) c FROM users WHERE role='donor'"),
        "students": q("SELECT COUNT(*) c FROM users WHERE role='student'"),
    }


# --------------------------------------------------------------------- public pages
@app.route("/")
def index():
    latest = query(
        "SELECT b.*, c.name AS category FROM books b JOIN categories c ON c.id=b.category_id "
        "WHERE b.status='available' ORDER BY b.id DESC LIMIT 4"
    )
    counts = {r["category_id"]: r["n"] for r in query(
        "SELECT category_id, COUNT(*) n FROM books WHERE status='available' GROUP BY category_id")}
    return render_template("index.html", stats=get_stats(), latest=latest, counts=counts)


@app.route("/about")
def about():
    return render_template("about.html", stats=get_stats())


@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name, email = clean(request.form.get("name"), 100), clean(request.form.get("email"), 150)
        subject, message = clean(request.form.get("subject"), 150), clean(request.form.get("message"), 2000)
        if not (name and email and subject and message):
            flash("Please fill in all fields.", "danger")
        elif not EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "danger")
        else:
            execute(
                "INSERT INTO contact_messages (name,email,subject,message,created_at) VALUES (?,?,?,?,?)",
                (name, email, subject, message, now()),
            )
            flash("Thank you! Your message has been sent. We will get back to you soon.", "success")
            return redirect(url_for("contact"))
    return render_template("contact.html")


# --------------------------------------------------------------------- auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = {}
    if request.method == "POST":
        form = {k: clean(request.form.get(k), 150) for k in ("name", "email", "phone", "city", "role")}
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm_password", "")
        errors = []
        if len(form["name"]) < 2:
            errors.append("Please enter your full name.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Please enter a valid email address.")
        if form["role"] not in ("donor", "student"):
            errors.append("Please choose whether you are a Donor or a Student.")
        if form["phone"] and not re.fullmatch(r"[0-9+\- ]{7,15}", form["phone"]):
            errors.append("Phone number may only contain digits, spaces, + and -.")
        problem = password_problem(pw)
        if problem:
            errors.append(problem)
        if pw != pw2:
            errors.append("Passwords do not match.")
        if not errors and query("SELECT id FROM users WHERE email=?", (form["email"].lower(),), one=True):
            errors.append("An account with this email already exists.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            execute(
                "INSERT INTO users (name,email,password_hash,role,phone,city,created_at) VALUES (?,?,?,?,?,?,?)",
                (form["name"], form["email"].lower(), generate_password_hash(pw), form["role"],
                 form["phone"], form["city"], now()),
            )
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = clean(request.form.get("email"), 150).lower()
        pw = request.form.get("password", "")
        row = query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if row and check_password_hash(row["password_hash"], pw):
            if not row["is_active"]:
                flash("This account has been deactivated. Please contact the administrator.", "danger")
            else:
                session.clear()  # new session on login (prevents session fixation)
                login_user(User(row), remember=bool(request.form.get("remember")))
                flash(f"Welcome back, {row['name']}!", "success")
                nxt = request.args.get("next")
                return redirect(nxt if is_safe_redirect(nxt) else url_for("dashboard"))
        else:
            flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# --------------------------------------------------------------------- dashboards
@app.route("/dashboard")
@login_required
def dashboard():
    uid = current_user.id
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    if current_user.role == "donor":
        data = {
            "total": query("SELECT COUNT(*) c FROM books WHERE donor_id=?", (uid,), one=True)["c"],
            "pending": query("SELECT COUNT(*) c FROM books WHERE donor_id=? AND status='pending'", (uid,), one=True)["c"],
            "available": query("SELECT COUNT(*) c FROM books WHERE donor_id=? AND status IN ('available','reserved')", (uid,), one=True)["c"],
            "distributed": query("SELECT COUNT(*) c FROM books WHERE donor_id=? AND status='distributed'", (uid,), one=True)["c"],
        }
        recent = query(
            "SELECT b.*, c.name AS category FROM books b JOIN categories c ON c.id=b.category_id "
            "WHERE b.donor_id=? ORDER BY b.id DESC LIMIT 5", (uid,))
        return render_template("dashboard.html", data=data, recent=recent)
    data = {
        "total": query("SELECT COUNT(*) c FROM book_requests WHERE student_id=?", (uid,), one=True)["c"],
        "pending": query("SELECT COUNT(*) c FROM book_requests WHERE student_id=? AND status='pending'", (uid,), one=True)["c"],
        "approved": query("SELECT COUNT(*) c FROM book_requests WHERE student_id=? AND status='approved'", (uid,), one=True)["c"],
        "received": query("SELECT COUNT(*) c FROM book_requests WHERE student_id=? AND status='distributed'", (uid,), one=True)["c"],
    }
    recent = query(
        "SELECT r.*, b.title, b.author FROM book_requests r JOIN books b ON b.id=r.book_id "
        "WHERE r.student_id=? ORDER BY r.id DESC LIMIT 5", (uid,))
    return render_template("dashboard.html", data=data, recent=recent)


# --------------------------------------------------------------------- donor
@app.route("/donate", methods=["GET", "POST"])
@role_required("donor")
def donate():
    form = {}
    if request.method == "POST":
        form = {k: clean(request.form.get(k), 200) for k in ("title", "author", "category", "level", "condition")}
        form["description"] = clean(request.form.get("description"), 1000)
        errors = []
        if len(form["title"]) < 2:
            errors.append("Please enter the book title.")
        if len(form["author"]) < 2:
            errors.append("Please enter the author name.")
        cat = query("SELECT id FROM categories WHERE name=?", (form["category"],), one=True)
        if not cat:
            errors.append("Please choose a valid category.")
        if form["level"] not in EDUCATION_LEVELS:
            errors.append("Please choose a valid education level.")
        if form["condition"] not in CONDITIONS:
            errors.append("Please choose the book condition.")
        image_name = None
        if not errors:
            try:
                image_name = save_image(request.files.get("image"))
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            book_id = execute(
                "INSERT INTO books (title,author,category_id,education_level,condition,description,image,"
                "donor_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
                (form["title"], form["author"], cat["id"], form["level"], form["condition"],
                 form["description"], image_name, current_user.id, now()),
            )
            execute(
                "INSERT INTO donations (book_id,donor_id,status,submitted_at) VALUES (?,?,'pending',?)",
                (book_id, current_user.id, now()),
            )
            flash("Thank you! Your book has been submitted and is waiting for admin approval.", "success")
            return redirect(url_for("my_donations"))
    return render_template("donate.html", form=form, levels=EDUCATION_LEVELS, conditions=CONDITIONS)


@app.route("/my-donations")
@role_required("donor")
def my_donations():
    rows = query(
        "SELECT d.id AS donation_id, d.status AS donation_status, d.admin_note, d.submitted_at, "
        "b.id AS book_id, b.title, b.author, b.status AS book_status, b.image, c.name AS category "
        "FROM donations d JOIN books b ON b.id=d.book_id JOIN categories c ON c.id=b.category_id "
        "WHERE d.donor_id=? ORDER BY d.id DESC", (current_user.id,))
    return render_template("my_donations.html", donations=rows)


# --------------------------------------------------------------------- books (public browse)
@app.route("/books")
def books():
    q = clean(request.args.get("q"), 100)
    category = clean(request.args.get("category"), 100)
    level = clean(request.args.get("level"), 100)
    sql = ("SELECT b.*, c.name AS category FROM books b JOIN categories c ON c.id=b.category_id "
           "WHERE b.status='available'")
    params = []
    if q:
        sql += " AND (b.title LIKE ? OR b.author LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if category:
        sql += " AND c.name = ?"
        params.append(category)
    if level:
        sql += " AND b.education_level = ?"
        params.append(level)
    sql += " ORDER BY b.id DESC"
    return render_template("books.html", books=query(sql, params), q=q, sel_category=category,
                           sel_level=level, levels=EDUCATION_LEVELS)


@app.route("/books/<int:book_id>")
def book_detail(book_id):
    book = query(
        "SELECT b.*, c.name AS category, u.name AS donor_name FROM books b "
        "JOIN categories c ON c.id=b.category_id JOIN users u ON u.id=b.donor_id WHERE b.id=?",
        (book_id,), one=True)
    if not book:
        abort(404)
    is_owner = current_user.is_authenticated and current_user.id == book["donor_id"]
    is_admin = current_user.is_authenticated and current_user.role == "admin"
    if book["status"] != "available" and not (is_owner or is_admin):
        abort(404)
    existing = None
    if current_user.is_authenticated and current_user.role == "student":
        existing = query(
            "SELECT * FROM book_requests WHERE book_id=? AND student_id=? "
            "AND status IN ('pending','approved','distributed')", (book_id, current_user.id), one=True)
    return render_template("book_detail.html", book=book, existing=existing)


# --------------------------------------------------------------------- student
@app.route("/books/<int:book_id>/request", methods=["POST"])
@role_required("student")
def request_book(book_id):
    book = query("SELECT * FROM books WHERE id=?", (book_id,), one=True)
    if not book or book["status"] != "available":
        flash("Sorry, this book is no longer available.", "warning")
        return redirect(url_for("books"))
    if query("SELECT id FROM book_requests WHERE book_id=? AND student_id=? "
             "AND status IN ('pending','approved','distributed')", (book_id, current_user.id), one=True):
        flash("You have already requested this book.", "info")
        return redirect(url_for("my_requests"))
    active = query("SELECT COUNT(*) c FROM book_requests WHERE student_id=? AND status IN ('pending','approved')",
                   (current_user.id,), one=True)["c"]
    if active >= 5:
        flash("You can have at most 5 open requests at a time. Please wait for them to be processed.", "warning")
        return redirect(url_for("my_requests"))
    execute(
        "INSERT INTO book_requests (book_id,student_id,reason,status,requested_at) VALUES (?,?,?,'pending',?)",
        (book_id, current_user.id, clean(request.form.get("reason"), 500), now()),
    )
    flash("Your request has been submitted. It is completely free - no payment needed!", "success")
    return redirect(url_for("my_requests"))


@app.route("/my-requests")
@role_required("student")
def my_requests():
    rows = query(
        "SELECT r.*, b.title, b.author, b.image FROM book_requests r JOIN books b ON b.id=r.book_id "
        "WHERE r.student_id=? ORDER BY r.id DESC", (current_user.id,))
    return render_template("my_requests.html", requests=rows)


@app.route("/requests/<int:req_id>/cancel", methods=["POST"])
@role_required("student")
def cancel_request(req_id):
    r = query("SELECT * FROM book_requests WHERE id=? AND student_id=?", (req_id, current_user.id), one=True)
    if not r:
        abort(404)
    if r["status"] not in ("pending", "approved"):
        flash("This request can no longer be cancelled.", "warning")
    else:
        execute("UPDATE book_requests SET status='cancelled', reviewed_at=? WHERE id=?", (now(), req_id))
        if r["status"] == "approved":
            execute("UPDATE books SET status='available' WHERE id=? AND status='reserved'", (r["book_id"],))
        flash("Request cancelled.", "info")
    return redirect(url_for("my_requests"))


@app.route("/feedback", methods=["GET", "POST"])
@role_required("student")
def feedback():
    received = query(
        "SELECT DISTINCT b.id, b.title FROM book_requests r JOIN books b ON b.id=r.book_id "
        "WHERE r.student_id=? AND r.status='distributed'", (current_user.id,))
    if request.method == "POST":
        try:
            book_id, rating = int(request.form.get("book_id", "")), int(request.form.get("rating", ""))
        except ValueError:
            book_id, rating = 0, 0
        comment = clean(request.form.get("comment"), 1000)
        if book_id not in {r["id"] for r in received}:
            flash("You can only give feedback for books you have received.", "danger")
        elif not 1 <= rating <= 5:
            flash("Please choose a rating from 1 to 5.", "danger")
        elif len(comment) < 5:
            flash("Please write a short comment (at least 5 characters).", "danger")
        else:
            execute("INSERT INTO feedback (student_id,book_id,rating,comment,created_at) VALUES (?,?,?,?,?)",
                    (current_user.id, book_id, rating, comment, now()))
            flash("Thank you for your feedback!", "success")
            return redirect(url_for("feedback"))
    mine = query("SELECT f.*, b.title FROM feedback f LEFT JOIN books b ON b.id=f.book_id "
                 "WHERE f.student_id=? ORDER BY f.id DESC", (current_user.id,))
    return render_template("feedback.html", received=received, mine=mine)


# --------------------------------------------------------------------- distribution records
@app.route("/distributions")
@login_required
def distributions():
    base = ("SELECT d.*, b.title, b.author, s.name AS student_name, s.email AS student_email, "
            "u.name AS donor_name FROM distributions d JOIN books b ON b.id=d.book_id "
            "JOIN users s ON s.id=d.student_id JOIN users u ON u.id=b.donor_id")
    if current_user.role == "admin":
        rows = query(base + " ORDER BY d.id DESC")
        ready = query(
            "SELECT r.*, b.title, b.author, s.name AS student_name FROM book_requests r "
            "JOIN books b ON b.id=r.book_id JOIN users s ON s.id=r.student_id "
            "WHERE r.status='approved' ORDER BY r.id")
    elif current_user.role == "student":
        rows, ready = query(base + " WHERE d.student_id=? ORDER BY d.id DESC", (current_user.id,)), []
    else:
        rows, ready = query(base + " WHERE b.donor_id=? ORDER BY d.id DESC", (current_user.id,)), []
    return render_template("distributions.html", records=rows, ready=ready)


# --------------------------------------------------------------------- admin
def admin_page(section, **ctx):
    return render_template("admin.html", section=section, **ctx)


@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    stats = get_stats()
    stats.update({
        "pending_donations": query("SELECT COUNT(*) c FROM donations WHERE status='pending'", one=True)["c"],
        "pending_requests": query("SELECT COUNT(*) c FROM book_requests WHERE status='pending'", one=True)["c"],
        "approved_waiting": query("SELECT COUNT(*) c FROM book_requests WHERE status='approved'", one=True)["c"],
        "feedback": query("SELECT COUNT(*) c FROM feedback", one=True)["c"],
        "unread": query("SELECT COUNT(*) c FROM contact_messages WHERE is_read=0", one=True)["c"],
    })
    recent_requests = query(
        "SELECT r.*, b.title, s.name AS student_name FROM book_requests r JOIN books b ON b.id=r.book_id "
        "JOIN users s ON s.id=r.student_id ORDER BY r.id DESC LIMIT 5")
    recent_donations = query(
        "SELECT d.*, b.title, u.name AS donor_name FROM donations d JOIN books b ON b.id=d.book_id "
        "JOIN users u ON u.id=d.donor_id ORDER BY d.id DESC LIMIT 5")
    return admin_page("dashboard", stats=stats, recent_requests=recent_requests,
                      recent_donations=recent_donations)


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    role = clean(request.args.get("role"), 20)
    sql, params = "SELECT * FROM users", []
    if role in ("donor", "student", "admin"):
        sql += " WHERE role=?"
        params.append(role)
    return admin_page("users", users=query(sql + " ORDER BY id DESC", params), role=role)


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_toggle_user(user_id):
    u = query("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not u:
        abort(404)
    if u["role"] == "admin":
        flash("Administrator accounts cannot be deactivated here.", "warning")
    else:
        execute("UPDATE users SET is_active=? WHERE id=?", (0 if u["is_active"] else 1, user_id))
        flash(f"Account for {u['name']} has been {'deactivated' if u['is_active'] else 'activated'}.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/donations")
@role_required("admin")
def admin_donations():
    status = clean(request.args.get("status"), 20)
    sql = ("SELECT d.*, b.title, b.author, b.image, b.condition, b.education_level, c.name AS category, "
           "u.name AS donor_name, u.email AS donor_email FROM donations d JOIN books b ON b.id=d.book_id "
           "JOIN categories c ON c.id=b.category_id JOIN users u ON u.id=d.donor_id")
    params = []
    if status in ("pending", "approved", "rejected"):
        sql += " WHERE d.status=?"
        params.append(status)
    return admin_page("donations", donations=query(sql + " ORDER BY d.id DESC", params), status=status)


@app.route("/admin/donations/<int:donation_id>/decision", methods=["POST"])
@role_required("admin")
def admin_donation_decision(donation_id):
    d = query("SELECT * FROM donations WHERE id=?", (donation_id,), one=True)
    if not d:
        abort(404)
    action = request.form.get("action")
    note = clean(request.form.get("admin_note"), 300)
    if d["status"] != "pending":
        flash("This donation has already been reviewed.", "warning")
    elif action == "approve":
        execute("UPDATE donations SET status='approved', admin_note=?, reviewed_at=? WHERE id=?", (note, now(), donation_id))
        execute("UPDATE books SET status='available' WHERE id=?", (d["book_id"],))
        flash("Donation approved - the book is now visible to students.", "success")
    elif action == "reject":
        execute("UPDATE donations SET status='rejected', admin_note=?, reviewed_at=? WHERE id=?", (note, now(), donation_id))
        execute("UPDATE books SET status='rejected' WHERE id=?", (d["book_id"],))
        flash("Donation rejected.", "info")
    else:
        abort(400)
    return redirect(url_for("admin_donations", status="pending"))


@app.route("/admin/requests")
@role_required("admin")
def admin_requests():
    status = clean(request.args.get("status"), 20)
    sql = ("SELECT r.*, b.title, b.author, b.status AS book_status, s.name AS student_name, "
           "s.email AS student_email, s.phone AS student_phone FROM book_requests r "
           "JOIN books b ON b.id=r.book_id JOIN users s ON s.id=r.student_id")
    params = []
    if status in ("pending", "approved", "rejected", "distributed", "cancelled"):
        sql += " WHERE r.status=?"
        params.append(status)
    return admin_page("requests", reqs=query(sql + " ORDER BY r.id DESC", params), status=status)


@app.route("/admin/requests/<int:req_id>/decision", methods=["POST"])
@role_required("admin")
def admin_request_decision(req_id):
    r = query("SELECT * FROM book_requests WHERE id=?", (req_id,), one=True)
    if not r:
        abort(404)
    action = request.form.get("action")
    note = clean(request.form.get("admin_note"), 300)
    if r["status"] != "pending":
        flash("This request has already been processed.", "warning")
    elif action == "approve":
        book = query("SELECT status FROM books WHERE id=?", (r["book_id"],), one=True)
        if book["status"] != "available":
            flash("This book is no longer available, so the request cannot be approved.", "danger")
        else:
            execute("UPDATE book_requests SET status='approved', admin_note=?, reviewed_at=? WHERE id=?", (note, now(), req_id))
            execute("UPDATE books SET status='reserved' WHERE id=?", (r["book_id"],))
            execute("UPDATE book_requests SET status='rejected', admin_note='Book was given to another student.', "
                    "reviewed_at=? WHERE book_id=? AND status='pending' AND id<>?", (now(), r["book_id"], req_id))
            flash("Request approved and the book is reserved. Record the distribution once handed over.", "success")
    elif action == "reject":
        execute("UPDATE book_requests SET status='rejected', admin_note=?, reviewed_at=? WHERE id=?", (note, now(), req_id))
        flash("Request rejected.", "info")
    else:
        abort(400)
    return redirect(url_for("admin_requests", status="pending"))


@app.route("/admin/requests/<int:req_id>/distribute", methods=["POST"])
@role_required("admin")
def admin_record_distribution(req_id):
    r = query("SELECT * FROM book_requests WHERE id=?", (req_id,), one=True)
    if not r:
        abort(404)
    method = clean(request.form.get("method"), 100)
    if r["status"] != "approved":
        flash("Only approved requests can be recorded as distributed.", "warning")
    elif not method:
        flash("Please choose how the book was handed over.", "danger")
    else:
        execute("INSERT INTO distributions (request_id,book_id,student_id,method,notes,distributed_at) VALUES (?,?,?,?,?,?)",
                (req_id, r["book_id"], r["student_id"], method, clean(request.form.get("notes"), 300), now()))
        execute("UPDATE book_requests SET status='distributed' WHERE id=?", (req_id,))
        execute("UPDATE books SET status='distributed' WHERE id=?", (r["book_id"],))
        flash("Distribution recorded.", "success")
    return redirect(url_for("distributions"))


@app.route("/admin/feedback")
@role_required("admin")
def admin_feedback():
    rows = query("SELECT f.*, s.name AS student_name, b.title FROM feedback f "
                 "JOIN users s ON s.id=f.student_id LEFT JOIN books b ON b.id=f.book_id ORDER BY f.id DESC")
    avg = query("SELECT ROUND(AVG(rating),1) a FROM feedback", one=True)["a"]
    return admin_page("feedback", items=rows, avg=avg)


@app.route("/admin/messages")
@role_required("admin")
def admin_messages():
    return admin_page("messages", items=query("SELECT * FROM contact_messages ORDER BY id DESC"))


@app.route("/admin/messages/<int:msg_id>/read", methods=["POST"])
@role_required("admin")
def admin_mark_read(msg_id):
    execute("UPDATE contact_messages SET is_read=1 WHERE id=?", (msg_id,))
    return redirect(url_for("admin_messages"))


@app.route("/admin/reports")
@role_required("admin")
def admin_reports():
    by_category = query(
        "SELECT c.name, COUNT(b.id) AS donated, "
        "SUM(CASE WHEN b.status='distributed' THEN 1 ELSE 0 END) AS distributed "
        "FROM categories c LEFT JOIN books b ON b.category_id=c.id AND b.status IN ('available','reserved','distributed') "
        "GROUP BY c.id ORDER BY c.id")
    by_status = query("SELECT status, COUNT(*) n FROM books GROUP BY status")
    monthly = query("SELECT substr(distributed_at,1,7) AS month, COUNT(*) n FROM distributions "
                    "GROUP BY month ORDER BY month DESC LIMIT 12")
    top_donors = query(
        "SELECT u.name, COUNT(b.id) n FROM users u JOIN books b ON b.donor_id=u.id "
        "WHERE b.status IN ('available','reserved','distributed') GROUP BY u.id ORDER BY n DESC LIMIT 5")
    return admin_page("reports", stats=get_stats(), by_category=by_category, by_status=by_status,
                      monthly=monthly, top_donors=top_donors)


@app.route("/admin/reports/export.csv")
@role_required("admin")
def admin_export_csv():
    rows = query(
        "SELECT d.id, d.distributed_at, b.title, b.author, c.name AS category, s.name AS student, "
        "u.name AS donor, d.method, d.notes FROM distributions d JOIN books b ON b.id=d.book_id "
        "JOIN categories c ON c.id=b.category_id JOIN users s ON s.id=d.student_id "
        "JOIN users u ON u.id=b.donor_id ORDER BY d.id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Date", "Title", "Author", "Category", "Student", "Donor", "Method", "Notes"])

    def safe(v):  # neutralise spreadsheet formula injection
        v = "" if v is None else str(v)
        return "'" + v if v[:1] in "=+-@" else v

    for r in rows:
        w.writerow([safe(x) for x in tuple(r)])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=distribution_report.csv"})


# --------------------------------------------------------------------- errors
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def http_error(err):
    code = getattr(err, "code", 500)
    messages = {400: "Bad request.", 403: "You do not have permission to view this page.",
                404: "The page you are looking for was not found.",
                413: "The uploaded file is too large (maximum 5 MB)."}
    detail = getattr(err, "description", None) if code == 400 else messages.get(code)
    return render_template("error.html", code=code, message=detail or messages.get(code, "Error")), code


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)
