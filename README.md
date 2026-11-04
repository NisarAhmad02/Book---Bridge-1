# Book Bridge - Used Book Collection and Distribution System

A college **Community Service Project (CSP)**. Book Bridge collects reusable books from donors and
distributes them **free of cost** to students who need them. There is no payment feature anywhere -
every book is free.

> **Just want to see the design on your Android phone?**
> Open **`preview/index.html`** in Chrome - no Python needed. See
> [Open the standalone preview on Android](#open-the-standalone-preview-on-android).

---

## 1. Features

**Donor**
- Register / log in
- Submit a book: title, author, category, education level, condition, description, cover image
- View all donated books and track each donation's status (pending / approved / rejected)

**Student**
- Register / log in
- Browse available books, search by title or author, filter by category and education level
- View book details and request books for free
- Track request status (pending / approved / rejected / distributed), cancel a request
- Give feedback (rating + comment) for books received

**Administrator**
- Dashboard with statistics
- Manage donors and students (activate / deactivate accounts)
- Review submitted books: approve or reject donations
- Approve or reject book requests (a competing pending request for the same book is auto-rejected)
- Record book distributions (hand-over method and notes)
- View feedback and contact messages
- Reports: books by category/status, distributions per month, top donors, **CSV export**

**Pages:** Home, About Us, How It Works, Register, Login, Donate Books, Find Books, Book Details,
Student Dashboard, Donor Dashboard, Admin Dashboard, My Requests, My Donations,
Distribution Records, Feedback, Contact Us.

**Book categories:** School textbooks, Intermediate textbooks, Engineering textbooks, Degree textbooks,
Competitive examination books, Reference books, General Knowledge books, Storybooks, Dictionaries,
Other educational books.

## 2. Technology used

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, JavaScript, Bootstrap 5 (loaded from the jsDelivr CDN) |
| Backend | Python Flask |
| Database | SQLite (single file, created automatically) |
| Authentication | Flask-Login (sessions) |
| Passwords | Werkzeug password hashing |
| Image uploads | Pillow (validates and re-encodes every upload) |

No paid APIs or services are used.

## 3. Security features

- Passwords stored only as Werkzeug hashes
- Session authentication with Flask-Login; new session on login
- Role-based access control (donor / student / admin) on every protected route
- CSRF token required on every POST request
- All SQL uses parameterised queries (protection against SQL injection)
- Upload validation: extension allow-list, real image check with Pillow, 5 MB limit,
  re-encoded to JPEG and saved under a random file name (the user's file name is never used)
- Jinja2 auto-escaping (protection against XSS), safe `next=` redirects, CSV formula-injection guard
- Users cannot register as administrators

## 4. Folder structure

```
Book_Bridge/
├── app.py                 Flask application (routes, auth, validation, uploads)
├── models.py              SQLite schema, helpers, User model, demo data
├── requirements.txt       Python dependencies
├── README.md
├── database/              bookbridge.db is created here on first run
├── static/
│   ├── css/style.css
│   ├── js/main.js
│   ├── images/            logo.svg, hero.svg
│   └── uploads/           uploaded book images (demo covers are generated on first run)
├── templates/
│   ├── base.html, _macros.html, error.html
│   ├── index.html, about.html, how_it_works.html, contact.html
│   ├── login.html, register.html
│   ├── donate.html, books.html, book_detail.html
│   ├── dashboard.html     (student and donor dashboards)
│   ├── my_requests.html, my_donations.html, feedback.html, distributions.html
│   └── admin.html         (admin dashboard, users, donations, requests, feedback, messages, reports)
└── preview/
    └── index.html         STANDALONE offline preview (no Flask / Python needed)
```

## 5. Install and run the Flask application

You need **Python 3.9 or newer**. An internet connection is needed in the browser the first time
because Bootstrap is loaded from a CDN.

```bash
# 1. open a terminal in the Book_Bridge folder
cd Book_Bridge

# 2. (recommended) create a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 3. install dependencies
pip install -r requirements.txt

# 4. run the app
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

On the first run the app automatically creates `database/bookbridge.db`, the 10 categories, and
the demo records below. To reset everything, stop the app and delete
`database/bookbridge.db` (and the `demo_*.jpg` files in `static/uploads/`), then start it again.

Optional: `set SECRET_KEY=your-long-random-string` (Windows) or `export SECRET_KEY=...` (macOS/Linux)
before running. If not set, a random key is generated and saved in `database/secret.key`.

## 6. Demo login credentials

These accounts are **demo-only** and are labelled "demo" in the admin Users list. Change or delete them
before using the system for real.

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@bookbridge.demo` | `Admin@Demo123` |
| Donor | `donor@bookbridge.demo` | `Donor@Demo123` |
| Student | `student@bookbridge.demo` | `Student@Demo123` |

Demo data: 8 books (marked with a "Demo record" badge) with generated cover images, one completed
distribution with feedback, one pending request and one donation waiting for approval.

### Quick test walk-through
1. Log in as **donor** → *Donate Books* → submit a book (with an image).
2. Log in as **admin** → *Donations* → **Approve** it.
3. Log in as **student** → *Find Books* → open the book → **Request this book**.
4. As **admin** → *Requests* → **Approve** → *Distributions* → **Record** the hand-over.
5. As **student** → *Feedback* → rate the book you received.
6. As **admin** → *Reports* → view statistics and download the CSV.

## 7. Open the standalone preview on Android

`preview/index.html` is a single file containing all HTML, CSS and JavaScript. It needs **no Flask,
no Python, no internet and no backend**. It shows the Book Bridge design with demo books, working
navigation, search and filters, book details, a donate form and a contact form. Everything you enter
stays on your phone (browser local storage) and is clearly marked as a preview.

1. Download **Book_Bridge.zip** to your phone (it normally goes to the *Downloads* folder).
2. Open the **Files** app (Files by Google) → *Downloads* → tap **Book_Bridge.zip** → **Extract**.
3. Open the extracted folder **Book_Bridge → preview**.
4. Tap **index.html** and choose **Chrome** (use *Open with → Chrome* if your phone asks).

If your phone shows the file as plain text or "can't open", type this in Chrome's address bar instead
(adjust the folder if you extracted elsewhere):

```
file:///storage/emulated/0/Download/Book_Bridge/preview/index.html
```

If Chrome says it cannot access the file, allow *Files and media / Storage* access for Chrome in
Android Settings → Apps → Chrome → Permissions, or copy `index.html` alone to *Downloads* and open it
from there. The file works on its own - you can move it anywhere.

The preview is an **additional** deliverable; the real application is the Flask project above.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: flask_login` | Run `pip install -r requirements.txt` (inside the activated virtual environment). |
| Page looks unstyled | The browser could not reach the Bootstrap CDN - connect to the internet. |
| "Security token missing or invalid" | Reload the page and submit the form again (your session expired). |
| Port 5000 already in use | Edit the last line of `app.py` and change `port=5000`. |
| Want to see the app from your phone on the same Wi-Fi | Change `host="127.0.0.1"` to `host="0.0.0.0"` in `app.py`, then open `http://<computer-ip>:5000` on the phone. Use this only on a trusted network, with debug off. |

## 9. Notes for the project report

- The app is intended for learning and campus use. Before a public deployment: use a production WSGI
  server (e.g. Waitress or Gunicorn), HTTPS, set `SECRET_KEY`, remove the demo accounts and consider
  adding email verification and rate limiting.
- All books are free; there is no payment code of any kind.
