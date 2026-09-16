# Habitgrid — Habit Tracker with GitHub-Style Heatmap

A beginner-friendly Flask + SQLite project: add daily habits, mark them
done, and watch a GitHub-style contribution heatmap and streak counters
build up over time.

## Features

- Login / Signup with hashed passwords (Werkzeug `generate_password_hash`)
- Add / Edit / Delete habits
- Categories: Health, Study, Fitness, Work, Personal, Other
- Daily goal time (hours + minutes) per habit
- Mark a habit done / undone for today
- Current streak & best streak per habit (auto-calculated)
- 365-day GitHub-style heatmap (per habit, and an aggregate one on the
  dashboard / statistics page)
- Last 7 days activity bar chart (Chart.js)
- Statistics page: totals, best streak overall, completions by category,
  per-habit completion-rate table
- Today's progress ring — how many habits you've finished today
- SQLite database (auto-created on first run, zero setup)
- Responsive UI — works on mobile and desktop, collapsible sidebar on
  small screens

## Setup

```bash
# 1. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

Open **http://127.0.0.1:5000** in your browser. The SQLite database file
(`habit_tracker.db`) is created automatically the first time you run the
app — no manual setup needed.

## Project structure

```
habit_tracker/
├── app.py                  # Flask app: routes, auth, streak & heatmap logic
├── requirements.txt
├── templates/
│   ├── base.html            # Sidebar layout + shared shell
│   ├── _flash.html          # Flash message partial
│   ├── _heatmap.html        # Reusable heatmap partial
│   ├── login.html
│   ├── signup.html
│   ├── dashboard.html
│   ├── add_habit.html
│   ├── edit_habit.html
│   ├── habit_detail.html
│   └── statistics.html
└── static/
    └── css/style.css        # Full design system
```

## Database schema

```sql
users (id, username, email, password_hash, created_at)
habits (id, user_id, name, category, goal_hours, goal_minutes, created_at)
logs (id, habit_id, date, completed)   -- one row per habit per completed day
```

## Notes

- Change `app.secret_key` in `app.py` before deploying anywhere public.
- Streak logic: a "current streak" stays alive if yesterday was
  completed, even if today hasn't been marked yet — so it doesn't reset
  to zero the moment midnight passes.
- Built as a college project (BCA 2nd year) — kept intentionally simple
  and readable rather than over-engineered.
