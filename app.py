from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "secret_key_change_me"

DB = "database.db"

STATUS_LABELS = {
    "open": "Открыта",
    "taken": "В работе",
    "done": "Выполнена",
}

CATEGORIES = {
    "walk": {"label": "Прогулка", "icon": "🚶"},
    "delivery": {"label": "Доставка вещей", "icon": "📦"},
    "help": {"label": "Бытовая помощь", "icon": "🔧"},
    "talk": {"label": "Поговорить", "icon": "💬"},
    "other": {"label": "Другое", "icon": "✨"},
}


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        description TEXT,
        category TEXT DEFAULT 'other',
        urgent INTEGER DEFAULT 0,
        status TEXT DEFAULT 'open',
        volunteer_id INTEGER,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def now_str():
    return datetime.now().strftime("%d.%m.%Y %H:%M")


@app.context_processor
def inject_globals():
    return {
        "STATUS_LABELS": STATUS_LABELS,
        "CATEGORIES": CATEGORIES,
    }


@app.route("/")
def index():
    conn = get_db()
    stats = {
        "requests": conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
        "done": conn.execute("SELECT COUNT(*) FROM requests WHERE status='done'").fetchone()[0],
        "volunteers": conn.execute("SELECT COUNT(*) FROM users WHERE role='volunteer'").fetchone()[0],
    }
    conn.close()
    return render_template("index.html", stats=stats)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = generate_password_hash(request.form["password"])
        role = request.form["role"]
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, password, role, created_at) VALUES (?, ?, ?, ?)",
                         (username, password, role, now_str()))
            conn.commit()
            flash("Аккаунт создан! Теперь войдите.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Такой логин уже занят.", "error")
        finally:
            conn.close()
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["username"] = user["username"]
            return redirect(url_for("cabinet"))
        flash("Неверный логин или пароль.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("index"))


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if user["role"] == "patient":
        count = conn.execute("SELECT COUNT(*) FROM requests WHERE patient_id = ?",
                             (user["id"],)).fetchone()[0]
    else:
        count = conn.execute("SELECT COUNT(*) FROM requests WHERE volunteer_id = ? AND status='done'",
                             (user["id"],)).fetchone()[0]
    conn.close()
    return render_template("profile.html", user=user, count=count)


@app.route("/cabinet")
def cabinet():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    if session["role"] == "patient":
        requests = conn.execute(
            "SELECT * FROM requests WHERE patient_id = ? ORDER BY urgent DESC, id DESC",
            (session["user_id"],)
        ).fetchall()
        conn.close()
        return render_template("patient.html", requests=requests)
    else:
        cat = request.args.get("cat", "")
        q = request.args.get("q", "").strip()

        query = "SELECT * FROM requests WHERE status = 'open'"
        params = []
        if cat:
            query += " AND category = ?"
            params.append(cat)
        if q:
            query += " AND description LIKE ?"
            params.append(f"%{q}%")
        query += " ORDER BY urgent DESC, id DESC"

        open_req = conn.execute(query, params).fetchall()
        my_req = conn.execute(
            "SELECT * FROM requests WHERE volunteer_id = ? ORDER BY id DESC",
            (session["user_id"],)
        ).fetchall()
        conn.close()
        return render_template("volunteer.html", open_req=open_req, my_req=my_req,
                               current_cat=cat, current_q=q)


@app.route("/create_request", methods=["GET", "POST"])
def create_request():
    if session.get("role") != "patient":
        return redirect(url_for("login"))
    if request.method == "POST":
        desc = request.form["description"].strip()
        category = request.form.get("category", "other")
        urgent = 1 if request.form.get("urgent") else 0
        if desc:
            conn = get_db()
            conn.execute(
                "INSERT INTO requests (patient_id, description, category, urgent, created_at) VALUES (?, ?, ?, ?, ?)",
                (session["user_id"], desc, category, urgent, now_str()))
            conn.commit()
            conn.close()
            flash("Заявка создана!", "success")
        return redirect(url_for("cabinet"))
    return render_template("create_request.html")


@app.route("/take/<int:req_id>")
def take(req_id):
    if session.get("role") != "volunteer":
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute("UPDATE requests SET status = 'taken', volunteer_id = ? WHERE id = ? AND status = 'open'",
                 (session["user_id"], req_id))
    conn.commit()
    conn.close()
    flash("Заявка взята в работу.", "success")
    return redirect(url_for("cabinet"))


@app.route("/done/<int:req_id>")
def done(req_id):
    if session.get("role") != "volunteer":
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute("UPDATE requests SET status = 'done' WHERE id = ? AND volunteer_id = ?",
                 (req_id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Заявка выполнена. Спасибо!", "success")
    return redirect(url_for("cabinet"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
