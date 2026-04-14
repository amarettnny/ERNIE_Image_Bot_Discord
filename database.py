import sqlite3
from datetime import datetime, timedelta

DB = "bot.db"


def init_db():
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users "
            "(user_id TEXT PRIMARY KEY, points INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS generations "
            "(message_id TEXT PRIMARY KEY, user_id TEXT, channel TEXT, "
            "prompt TEXT, created_at TEXT, reactions INTEGER DEFAULT 0, "
            "bonus_awarded INTEGER DEFAULT 0)"
        )


# ── Token (global, admin-only) ──

def set_token(token: str):
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('token', ?)", (token,))


def get_token():
    with sqlite3.connect(DB) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='token'").fetchone()
        return row[0] if row else None


# ── Users ──

def ensure_user(uid: str):
    with sqlite3.connect(DB) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))


# ── Points ──

def get_points(uid: str) -> int:
    with sqlite3.connect(DB) as conn:
        row = conn.execute("SELECT points FROM users WHERE user_id=?", (uid,)).fetchone()
        return row[0] if row else 0


def add_points(uid: str, pts: int):
    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (pts, uid))


# ── Generations ──

def add_generation(message_id: str, uid: str, channel: str, prompt: str):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO generations VALUES (?, ?, ?, ?, ?, 0, 0)",
            (message_id, uid, channel, prompt, datetime.utcnow().isoformat()),
        )


def get_generation(message_id: str):
    """Returns (user_id, channel, bonus_awarded) or None."""
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT user_id, channel, bonus_awarded FROM generations WHERE message_id=?",
            (message_id,),
        ).fetchone()


def has_daily_checkin(uid: str) -> bool:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with sqlite3.connect(DB) as conn:
        row = conn.execute(
            "SELECT 1 FROM generations WHERE user_id=? AND channel='daily-showcase' "
            "AND created_at LIKE ?",
            (uid, f"{today}%"),
        ).fetchone()
        return row is not None


def update_reactions(message_id: str, count: int):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "UPDATE generations SET reactions=? WHERE message_id=?", (count, message_id)
        )


def mark_bonus(message_id: str):
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "UPDATE generations SET bonus_awarded=1 WHERE message_id=?", (message_id,)
        )


# ── Queries ──

def get_gallery(limit: int = 10):
    """Top daily-showcase posts by reaction count."""
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT user_id, prompt, reactions, message_id FROM generations "
            "WHERE channel='daily-showcase' ORDER BY reactions DESC LIMIT ?",
            (limit,),
        ).fetchall()


def get_leaderboard(limit: int = 10):
    """Top theme-battle posts this week (Mon–Sun)."""
    now = datetime.utcnow()
    monday = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            "SELECT user_id, prompt, reactions, message_id FROM generations "
            "WHERE channel='theme-battle' AND created_at >= ? "
            "ORDER BY reactions DESC LIMIT ?",
            (monday, limit),
        ).fetchall()