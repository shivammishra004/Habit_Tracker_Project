"""
Habit Tracker with GitHub-style Heatmap
A beginner-friendly Flask + SQLite project.

Run with:
    pip install -r requirements.txt
    python app.py

Then open http://127.0.0.1:5000 in your browser.
"""

import os
import sqlite3
from datetime import date, timedelta, datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.environ.get("DB_PATH", "habit_tracker.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deploying")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Other',
            goal_hours INTEGER NOT NULL DEFAULT 0,
            goal_minutes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (habit_id) REFERENCES habits (id) ON DELETE CASCADE,
            UNIQUE (habit_id, date)
        );
        """
    )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE id = ?", (session["user_id"],)
    ).fetchone()


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# ---------------------------------------------------------------------------
# Streak / heatmap helpers
# ---------------------------------------------------------------------------

def get_completed_dates(db, habit_id):
    rows = db.execute(
        "SELECT date FROM logs WHERE habit_id = ? AND completed = 1",
        (habit_id,),
    ).fetchall()
    return {r["date"] for r in rows}


def calculate_streaks(completed_dates):
    """Return (current_streak, best_streak) given a set of 'YYYY-MM-DD' strings."""
    if not completed_dates:
        return 0, 0

    dates = sorted(date.fromisoformat(d) for d in completed_dates)

    # Best streak: longest run of consecutive calendar days
    best = 1
    run = 1
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days == 1:
            run += 1
        elif (dates[i] - dates[i - 1]).days == 0:
            continue
        else:
            run = 1
        best = max(best, run)

    # Current streak: consecutive days counting back from today
    # (allows the streak to still be "alive" if today isn't marked yet,
    # as long as yesterday was marked)
    today = date.today()
    date_set = set(dates)
    current = 0
    cursor = today
    if today not in date_set:
        cursor = today - timedelta(days=1)
        if cursor not in date_set:
            return 0, best
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)

    return current, best


def build_heatmap(completed_dates, days=365):
    """Build a list of {date, count} for the last `days` days (count 0/1)."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    cells = []
    d = start
    while d <= today:
        iso = d.isoformat()
        cells.append({"date": iso, "count": 1 if iso in completed_dates else 0})
        d += timedelta(days=1)
    return cells


def build_aggregate_heatmap(db, user_id, days=365):
    """Heatmap across ALL of a user's habits: count = number of habits done that day."""
    rows = db.execute(
        """
        SELECT l.date as date, COUNT(*) as cnt
        FROM logs l
        JOIN habits h ON h.id = l.habit_id
        WHERE h.user_id = ? AND l.completed = 1
        GROUP BY l.date
        """,
        (user_id,),
    ).fetchall()
    counts = {r["date"]: r["cnt"] for r in rows}

    today = date.today()
    start = today - timedelta(days=days - 1)
    cells = []
    d = start
    while d <= today:
        iso = d.isoformat()
        cells.append({"date": iso, "count": counts.get(iso, 0)})
        d += timedelta(days=1)
    return cells


def cells_to_weeks(cells):
    """Turn a flat list of {date, count} (ascending) into GitHub-style week
    columns (7 rows: Sun..Sat) plus month label positions per column."""
    if not cells:
        return [], []

    max_count = max((c["count"] for c in cells), default=0) or 1
    for c in cells:
        if c["count"] <= 0:
            c["level"] = 0
        else:
            c["level"] = min(4, max(1, round((c["count"] / max_count) * 4)))

    first_date = date.fromisoformat(cells[0]["date"])
    # Python weekday(): Mon=0..Sun=6 -> convert so Sun=0..Sat=6
    lead_offset = (first_date.weekday() + 1) % 7

    padded = [None] * lead_offset + cells
    while len(padded) % 7 != 0:
        padded.append(None)

    weeks = [padded[i:i + 7] for i in range(0, len(padded), 7)]

    month_labels = []
    last_month = None
    for w_idx, week in enumerate(weeks):
        for day in week:
            if day is None:
                continue
            m = date.fromisoformat(day["date"]).strftime("%b")
            if m != last_month:
                month_labels.append({"col": w_idx, "label": m})
                last_month = m
            break

    return weeks, month_labels


def last_7_days_activity(db, user_id):
    today = date.today()
    labels, values = [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        cnt = db.execute(
            """
            SELECT COUNT(*) as c FROM logs l
            JOIN habits h ON h.id = l.habit_id
            WHERE h.user_id = ? AND l.date = ? AND l.completed = 1
            """,
            (user_id, iso),
        ).fetchone()["c"]
        labels.append(d.strftime("%a"))
        values.append(cnt)
    return labels, values


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        error = None
        if not username or not email or not password:
            error = "All fields are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."

        db = get_db()
        if error is None:
            existing = db.execute(
                "SELECT id FROM users WHERE username = ? OR email = ?",
                (username, email),
            ).fetchone()
            if existing:
                error = "Username or email is already taken."

        if error:
            flash(error, "error")
            return render_template("signup.html", username=username, email=email)

        db.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username, email, generate_password_hash(password), datetime.now().isoformat()),
        )
        db.commit()
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (identifier, identifier.lower()),
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username/email or password.", "error")
        return render_template("login.html", username=identifier)

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    db = get_db()
    user = current_user()
    habits = db.execute(
        "SELECT * FROM habits WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()

    today_iso = date.today().isoformat()
    habit_data = []
    completed_today = 0

    for h in habits:
        completed_dates = get_completed_dates(db, h["id"])
        current, best = calculate_streaks(completed_dates)
        done_today = today_iso in completed_dates
        if done_today:
            completed_today += 1
        habit_data.append({
            "habit": h,
            "current_streak": current,
            "best_streak": best,
            "done_today": done_today,
        })

    total_habits = len(habits)
    progress_pct = round((completed_today / total_habits) * 100) if total_habits else 0

    heatmap = build_aggregate_heatmap(db, user["id"])
    weeks, month_labels = cells_to_weeks(heatmap)
    week_labels, week_values = last_7_days_activity(db, user["id"])

    return render_template(
        "dashboard.html",
        habit_data=habit_data,
        total_habits=total_habits,
        completed_today=completed_today,
        progress_pct=progress_pct,
        weeks=weeks,
        month_labels=month_labels,
        max_heat=max(total_habits, 1),
        week_labels=week_labels,
        week_values=week_values,
    )


# ---------------------------------------------------------------------------
# Habit CRUD
# ---------------------------------------------------------------------------

CATEGORIES = ["Health", "Study", "Fitness", "Work", "Personal", "Other"]


@app.route("/habit/add", methods=["GET", "POST"])
@login_required
def add_habit():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "Other")
        hours = request.form.get("goal_hours", "0")
        minutes = request.form.get("goal_minutes", "0")

        error = None
        if not name:
            error = "Habit name is required."
        if category not in CATEGORIES:
            category = "Other"
        try:
            hours = max(0, int(hours or 0))
            minutes = max(0, min(59, int(minutes or 0)))
        except ValueError:
            error = "Goal time must be numeric."

        if error:
            flash(error, "error")
            return render_template("add_habit.html", categories=CATEGORIES, form=request.form)

        db = get_db()
        db.execute(
            """INSERT INTO habits (user_id, name, category, goal_hours, goal_minutes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session["user_id"], name, category, hours, minutes, datetime.now().isoformat()),
        )
        db.commit()
        flash(f'Habit "{name}" added!', "success")
        return redirect(url_for("dashboard"))

    return render_template("add_habit.html", categories=CATEGORIES, form={})


def get_owned_habit_or_404(habit_id):
    db = get_db()
    habit = db.execute(
        "SELECT * FROM habits WHERE id = ? AND user_id = ?",
        (habit_id, session["user_id"]),
    ).fetchone()
    return habit


@app.route("/habit/<int:habit_id>/edit", methods=["GET", "POST"])
@login_required
def edit_habit(habit_id):
    habit = get_owned_habit_or_404(habit_id)
    if habit is None:
        flash("Habit not found.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "Other")
        hours = request.form.get("goal_hours", "0")
        minutes = request.form.get("goal_minutes", "0")

        error = None
        if not name:
            error = "Habit name is required."
        if category not in CATEGORIES:
            category = "Other"
        try:
            hours = max(0, int(hours or 0))
            minutes = max(0, min(59, int(minutes or 0)))
        except ValueError:
            error = "Goal time must be numeric."

        if error:
            flash(error, "error")
            return render_template("edit_habit.html", habit=habit, categories=CATEGORIES)

        db = get_db()
        db.execute(
            """UPDATE habits SET name = ?, category = ?, goal_hours = ?, goal_minutes = ?
               WHERE id = ? AND user_id = ?""",
            (name, category, hours, minutes, habit_id, session["user_id"]),
        )
        db.commit()
        flash("Habit updated.", "success")
        return redirect(url_for("dashboard"))

    return render_template("edit_habit.html", habit=habit, categories=CATEGORIES)


@app.route("/habit/<int:habit_id>/delete", methods=["POST"])
@login_required
def delete_habit(habit_id):
    habit = get_owned_habit_or_404(habit_id)
    if habit is None:
        flash("Habit not found.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute("DELETE FROM habits WHERE id = ? AND user_id = ?", (habit_id, session["user_id"]))
    db.commit()
    flash(f'Habit "{habit["name"]}" deleted.', "success")
    return redirect(url_for("dashboard"))


@app.route("/habit/<int:habit_id>/toggle", methods=["POST"])
@login_required
def toggle_habit(habit_id):
    habit = get_owned_habit_or_404(habit_id)
    if habit is None:
        return jsonify({"error": "not found"}), 404

    db = get_db()
    today_iso = date.today().isoformat()
    existing = db.execute(
        "SELECT * FROM logs WHERE habit_id = ? AND date = ?", (habit_id, today_iso)
    ).fetchone()

    if existing:
        db.execute("DELETE FROM logs WHERE habit_id = ? AND date = ?", (habit_id, today_iso))
        done = False
    else:
        db.execute(
            "INSERT INTO logs (habit_id, date, completed) VALUES (?, ?, 1)",
            (habit_id, today_iso),
        )
        done = True
    db.commit()

    completed_dates = get_completed_dates(db, habit_id)
    current, best = calculate_streaks(completed_dates)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"done": done, "current_streak": current, "best_streak": best})

    return redirect(request.referrer or url_for("dashboard"))


@app.route("/habit/<int:habit_id>")
@login_required
def habit_detail(habit_id):
    habit = get_owned_habit_or_404(habit_id)
    if habit is None:
        flash("Habit not found.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    completed_dates = get_completed_dates(db, habit_id)
    current, best = calculate_streaks(completed_dates)
    heatmap = build_heatmap(completed_dates)
    weeks, month_labels = cells_to_weeks(heatmap)
    total_completions = len(completed_dates)
    today_iso = date.today().isoformat()

    return render_template(
        "habit_detail.html",
        habit=habit,
        current_streak=current,
        best_streak=best,
        weeks=weeks,
        month_labels=month_labels,
        max_heat=1,
        total_completions=total_completions,
        done_today=today_iso in completed_dates,
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

@app.route("/statistics")
@login_required
def statistics():
    db = get_db()
    user = current_user()
    habits = db.execute(
        "SELECT * FROM habits WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
    ).fetchall()

    stats = []
    category_totals = {}
    best_overall = {"name": None, "streak": 0}
    total_completions_all = 0

    for h in habits:
        completed_dates = get_completed_dates(db, h["id"])
        current, best = calculate_streaks(completed_dates)
        days_since_created = max(
            1,
            (date.today() - date.fromisoformat(h["created_at"][:10])).days + 1,
        )
        completion_rate = round((len(completed_dates) / days_since_created) * 100)
        total_completions_all += len(completed_dates)

        if best > best_overall["streak"]:
            best_overall = {"name": h["name"], "streak": best}

        category_totals[h["category"]] = category_totals.get(h["category"], 0) + len(completed_dates)

        stats.append({
            "habit": h,
            "current_streak": current,
            "best_streak": best,
            "total_completions": len(completed_dates),
            "completion_rate": completion_rate,
        })

    heatmap = build_aggregate_heatmap(db, user["id"])
    weeks, month_labels = cells_to_weeks(heatmap)
    week_labels, week_values = last_7_days_activity(db, user["id"])

    return render_template(
        "statistics.html",
        stats=stats,
        total_habits=len(habits),
        total_completions_all=total_completions_all,
        best_overall=best_overall,
        category_totals=category_totals,
        weeks=weeks,
        month_labels=month_labels,
        max_heat=max(len(habits), 1),
        week_labels=week_labels,
        week_values=week_values,
    )


init_db()  # ensures tables exist whether run via `python app.py` or gunicorn

if __name__ == "__main__":
    app.run(debug=True)
