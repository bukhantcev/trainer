import sqlite3
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()
    # users
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER UNIQUE NOT NULL,
        name TEXT,
        age INTEGER,
        height INTEGER,
        weight INTEGER,
        goal TEXT,
        experience TEXT,
        gender TEXT
    )
    """)
    # migrations
    for col in [
        "bench_max_kg INTEGER",
        "squat_max_kg INTEGER",
        "pullups_reps INTEGER",
        "deadlift_max_kg INTEGER",
        "dips_reps INTEGER",
        "ohp_max_kg INTEGER",
        "cgbp_max_kg INTEGER",
        "prompt TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    # training type
    try:
        conn.execute("ALTER TABLE users ADD COLUMN training_type TEXT")
    except sqlite3.OperationalError:
        pass

    # workouts
    conn.execute("""
    CREATE TABLE IF NOT EXISTS workouts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        notes TEXT
    )
    """)

    # exercises
    conn.execute("""
    CREATE TABLE IF NOT EXISTS exercises(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workout_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        set_index INTEGER NOT NULL,
        weight INTEGER,
        target_reps INTEGER,
        actual_reps INTEGER,
        date TEXT,
        training_type TEXT,
        FOREIGN KEY(workout_id) REFERENCES workouts(id) ON DELETE CASCADE
    )
    """)

    # migration: ensure exercises.training_type exists
    try:
        info = conn.execute("PRAGMA table_info(exercises)").fetchall()
        has_training_type = any(row[1] == "training_type" for row in info)
        if not has_training_type:
            conn.execute("ALTER TABLE exercises ADD COLUMN training_type TEXT")
    except sqlite3.OperationalError:
        pass

    # ensure columns/indexes
    try:
        conn.execute("ALTER TABLE exercises ADD COLUMN date TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workouts_tg_date ON workouts(tg_id, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exercises_workout ON exercises(workout_id)")
    conn.commit()
    conn.close()