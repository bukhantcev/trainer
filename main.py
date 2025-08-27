# --- Imports ---
import asyncio
import os

import sqlite3
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
import re
import json
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from prompt import PROMPT


# --- Init ---
load_dotenv()

DB_PATH = os.getenv("DB_URL", "trainer.db")

BOT_TOKEN = os.getenv("BOT_TOKEN")

# OpenAI config
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Посмотреть профиль"), KeyboardButton(text="Новая тренировка")]
    ],
    resize_keyboard=True
)

# --- DB ---
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE NOT NULL,
            name TEXT,
            age INTEGER,
            height INTEGER,
            weight INTEGER,
            goal TEXT,
            experience TEXT
        )
        """
    )
    # Add onboarding columns if not exist
    try:
        conn.execute("ALTER TABLE users ADD COLUMN bench_max_kg INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN squat_max_kg INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN pullups_reps INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN deadlift_max_kg INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN dips_reps INTEGER")
    except sqlite3.OperationalError:
        pass

    # Create workouts table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            notes TEXT
        )
        """
    )

    # Create exercises table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            set_index INTEGER NOT NULL,
            weight INTEGER,
            target_reps INTEGER,
            actual_reps INTEGER,
            date TEXT
        )
        """
    )
    # Ensure 'date' column exists for old DBs
    try:
        conn.execute("ALTER TABLE exercises ADD COLUMN date TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# --- Utils ---
def format_profile_card(row: sqlite3.Row | None) -> str:
    if not row:
        return "Профиль не найден."
    name = row.get("name") if isinstance(row, dict) else row["name"]
    age = row.get("age") if isinstance(row, dict) else row["age"]
    height = row.get("height") if isinstance(row, dict) else row["height"]
    weight = row.get("weight") if isinstance(row, dict) else row["weight"]
    goal = row.get("goal") if isinstance(row, dict) else row["goal"]
    exp = row.get("experience") if isinstance(row, dict) else row["experience"]
    def show(v):
        return str(v) if v not in (None, "") else "не указано"
    return (
        f"<b>Профиль</b>\n"
        f"Имя: {show(name)}\n"
        f"Возраст: {show(age)}\n"
        f"Рост: {show(height)}\n"
        f"Вес: {show(weight)}\n"
        f"Цель: {show(goal)}\n"
        f"Опыт: {show(exp)}"
    )


# --- Parsing ---
def parse_profile_update(text: str) -> dict:
    # Lowercase text for matching
    text_lower = text.lower()
    # Split by comma or newline
    parts = re.split(r'[,\n]+', text)
    result = {}

    # Define regex patterns for each field
    patterns = {
        'name': re.compile(r'имя\s+(.+)', re.I),
        'age': re.compile(r'возраст\s+(\d+)', re.I),
        'height': re.compile(r'рост\s+(\d+)', re.I),
        'weight': re.compile(r'вес\s+(\d+)', re.I),
        'goal': re.compile(r'цель\s+(.+)', re.I),
        'experience': re.compile(r'опыт\s+(.+)', re.I),
    }

    # Normalize goal values
    goal_map = {
        'сила': 'сила',
        'масса': 'масса',
        'сушка': 'сушка',
        'общая форма': 'общая форма',
        'общая': 'общая форма',
    }

    # Normalize experience values
    exp_map = {
        'новичок': 'новичок',
        'средний': 'средний',
        'продвинутый': 'продвинутый',
    }

    for part in parts:
        part = part.strip()
        for key, pattern in patterns.items():
            m = pattern.match(part)
            if m:
                val = m.group(1).strip()
                if key == 'goal':
                    val_lower = val.lower()
                    for k, v in goal_map.items():
                        if k in val_lower:
                            val = v
                            break
                    else:
                        val = val_lower  # fallback to raw lowercased
                elif key == 'experience':
                    val_lower = val.lower()
                    for k, v in exp_map.items():
                        if k in val_lower:
                            val = v
                            break
                    else:
                        val = val_lower
                elif key == 'age':
                    try:
                        val = int(val)
                    except ValueError:
                        continue
                elif key == 'height':
                    try:
                        val = int(val)
                    except ValueError:
                        continue
                elif key == 'weight':
                    try:
                        val = int(val)
                    except ValueError:
                        continue
                elif key == 'name':
                    val = val.strip()
                result[key] = val
                break

    return result


# Inline keyboard for profile editing
def profile_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить", callback_data="profile:edit")]
    ])


# --- Handlers ---

class ProfileFSM(StatesGroup):
    wait_input = State()

class OnboardFSM(StatesGroup):
    bench = State()
    squat = State()
    pullups = State()
    deadlift = State()
    dips = State()



@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    init_db()
    tg_id = message.from_user.id
    name = message.from_user.first_name
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE tg_id = ?", (tg_id,))
    exists = cur.fetchone()
    if not exists:
        cur.execute("INSERT INTO users (tg_id, name) VALUES (?, ?)", (tg_id, name))
        conn.commit()
        conn.close()
        await state.set_state(OnboardFSM.bench)
        await message.answer(
            "Онбординг профиля. Ответь, пожалуйста, на несколько вопросов.\n\n"
            "Жим лёжа — твой максимальный вес (кг)? Введи целое число."
        )
    else:
        conn.close()
        await message.answer("Готово! Профиль создан. Выбирай действие ниже.", reply_markup=main_kb)


# Handler for "Посмотреть профиль"
@dp.message(F.text == "Посмотреть профиль")
async def view_profile(message: Message):
    tg_id = message.from_user.id
    conn = get_connection()
    row = conn.execute("SELECT name, age, height, weight, goal, experience FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    conn.close()
    await message.answer(format_profile_card(row), parse_mode="HTML", reply_markup=profile_inline_kb())


# Callback handler for profile:edit
@dp.callback_query(F.data == "profile:edit")
async def edit_profile_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Режим редактирования профиля", show_alert=False)
    await state.set_state(ProfileFSM.wait_input)
    await callback.message.answer(
        "Напиши, что изменить, в формате: Имя Алеша, Возраст 39, Рост 173, Вес 82, Цель сила, Опыт новичок.\n"
        "Можно прислать только нужные поля.\n\n"
        "Варианты цели: сила, масса, сушка, общая форма.\n"
        "Варианты опыта: новичок, средний, продвинутый.\n"
        "Рост и вес вводи целыми числами."
    )


@dp.message(ProfileFSM.wait_input)
async def profile_update_input(message: Message, state: FSMContext):
    data = parse_profile_update(message.text)
    if not data:
        await message.answer("Неправильный формат. Пример: Имя Алеша, Возраст 39, Рост 173")
        return
    tg_id = message.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    # Build SET clause dynamically
    keys = data.keys()
    set_clause = ", ".join(f"{k} = ?" for k in keys)
    values = list(data.values())
    values.append(tg_id)
    query = f"UPDATE users SET {set_clause} WHERE tg_id = ?"
    cur.execute(query, values)
    conn.commit()
    # Fetch updated row
    row = cur.execute("SELECT name, age, height, weight, goal, experience FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    conn.close()
    await state.clear()
    await message.answer(format_profile_card(row), parse_mode="HTML", reply_markup=profile_inline_kb())


# Onboarding handlers

@dp.message(OnboardFSM.bench)
async def onboard_bench(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введи целое число. Жим лёжа — твой максимальный вес (кг)?")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET bench_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit()
    conn.close()
    await state.set_state(OnboardFSM.squat)
    await message.answer("Присед со штангой на плечах — максимальный вес (кг)? Введи целое число.")


@dp.message(OnboardFSM.squat)
async def onboard_squat(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введи целое число. Присед со штангой на плечах — максимальный вес (кг)?")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET squat_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit()
    conn.close()
    await state.set_state(OnboardFSM.pullups)
    await message.answer("Сколько раз подтягиваешься (чистые повторения)? Введи целое число.")


@dp.message(OnboardFSM.pullups)
async def onboard_pullups(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введи целое число. Сколько раз подтягиваешься (чистые повторения)?")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET pullups_reps = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit()
    conn.close()
    await state.set_state(OnboardFSM.deadlift)
    await message.answer("Становая тяга — максимальный вес (кг)? Введи целое число.")


@dp.message(OnboardFSM.deadlift)
async def onboard_deadlift(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введи целое число. Становая тяга — максимальный вес (кг)?")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET deadlift_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit()
    conn.close()
    await state.set_state(OnboardFSM.dips)
    await message.answer("Отжимания на брусьях — сколько повторений? Введи целое число.")


@dp.message(OnboardFSM.dips)
async def onboard_dips(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введи целое число. Отжимания на брусьях — сколько повторений?")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET dips_reps = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("Спасибо! Данные сохранены. Выбирай действие ниже.", reply_markup=main_kb)


@dp.message(F.text == "Новая тренировка")
async def new_training_collect(message: Message):
    tg_id = message.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    # Fetch user core info (exclude onboarding strength metrics)
    user_row = cur.execute(
        "SELECT name, age, height, weight, goal, experience FROM users WHERE tg_id = ?",
        (tg_id,)
    ).fetchone()
    user_info = dict(user_row) if user_row else {}

    user_info_ru = {
        "Имя": user_info.get("name"),
        "Возраст": user_info.get("age"),
        "Рост": user_info.get("height"),
        "Вес": user_info.get("weight"),
        "Цель": user_info.get("goal"),
        "Опыт": user_info.get("experience"),
    }

    # Fetch last 30 days history
    since = (datetime.now(timezone.utc).date() - timedelta(days=30)).strftime("%Y-%m-%d")
    cur.execute(
        """
        SELECT w.date AS date, e.name AS exercise, e.set_index AS set_number,
               e.weight AS weight, e.target_reps AS target_reps, e.actual_reps AS actual_reps
        FROM workouts w
        JOIN exercises e ON e.workout_id = w.id
        WHERE w.tg_id = ? AND w.date >= ?
        ORDER BY w.date ASC, w.id ASC, e.set_index ASC
        """,
        (tg_id, since)
    )
    history_rows = [dict(r) for r in cur.fetchall()]

    history_ru = [
        {
            "дата": row["date"],
            "упражнение": row["exercise"],
            "подход": row["set_number"],
            "вес": row["weight"],
            "целевые_повторения": row["target_reps"],
            "выполненные_повторения": row["actual_reps"],
        }
        for row in history_rows
    ]

    payload = {
        "пользователь": user_info_ru,
        "история": history_ru,
    }

    # If no history — include onboarding answers from profile
    if not history_rows:
        ob = cur.execute(
            "SELECT bench_max_kg, squat_max_kg, pullups_reps, deadlift_max_kg, dips_reps FROM users WHERE tg_id = ?",
            (tg_id,)
        ).fetchone()
        onboarding_ru = {
            "жим_лёжа_макс_кг": ob["bench_max_kg"],
            "присед_макс_кг": ob["squat_max_kg"],
            "подтягивания_повторы": ob["pullups_reps"],
            "становая_макс_кг": ob["deadlift_max_kg"],
            "брусья_повторы": ob["dips_reps"],
        } if ob else {}
        payload["анкета"] = onboarding_ru

    conn.close()

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not OPENAI_API_KEY:
        print("[OpenAI] ERROR: OPENAI_API_KEY is not set")
        await message.answer("Ошибка OpenAI: проверь ключ в .env")
        return
    try:
        client = OpenAI()
        content = (
            "Ниже данные пользователя и история за 30 дней в формате JSON (на русском). "
            "Используй мой промпт после данных.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n\nПромпт:\n"
            + (PROMPT or "")
        )
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Ты умный тренер-ассистент. Отвечай кратко и по делу."},
                {"role": "user", "content": content},
            ],
        )
        text = resp.choices[0].message.content if resp and resp.choices else "(пустой ответ)"
        # --- Parse OpenAI JSON and persist to DB ---
        plan_items = []
        try:
            # Extract JSON array even if response contains extra text
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
                plan_items = json.loads(json_str)
            else:
                # try parse as-is
                plan_items = json.loads(text)
        except Exception as e_parse:
            print(f"[OpenAI] Parse error: {e_parse}\nRaw text:\n{text}")
            plan_items = []

        if plan_items:
            # Create workout for today
            today_iso = datetime.now(timezone.utc).date().strftime('%Y-%m-%d')
            conn2 = get_connection()
            cur2 = conn2.cursor()
            cur2.execute(
                "INSERT INTO workouts (tg_id, date, notes) VALUES (?, ?, ?)",
                (tg_id, today_iso, 'auto from OpenAI')
            )
            workout_id = cur2.lastrowid

            # Insert exercises/sets
            inserted = 0
            for item in plan_items:
                try:
                    name = item.get('Название упражнения')
                    set_number = int(item.get('Номер подхода')) if item.get('Номер подхода') is not None else None
                    weight = int(item.get('Вес')) if item.get('Вес') is not None else None
                    target_reps = int(item.get('Количество повторений')) if item.get('Количество повторений') is not None else None
                    if not name or set_number is None:
                        continue
                    cur2.execute(
                        """
                        INSERT INTO exercises (workout_id, name, set_index, weight, target_reps, actual_reps, date)
                        VALUES (?, ?, ?, ?, ?, NULL, ?)
                        """,
                        (workout_id, name, set_number, weight, target_reps, today_iso)
                    )
                    inserted += 1
                except Exception as e_row:
                    print(f"[DB] Skip row error: {e_row} | row={item}")
            conn2.commit()
            conn2.close()
            print(f"[DB] Saved workout #{workout_id} with {inserted} sets for tg_id={tg_id} on {today_iso}")
        else:
            print("[OpenAI] No plan items parsed; nothing saved to DB.")

        print("[OpenAI] Ответ:\n" + text)
        await message.answer("Готово. Ответ в консоли.")
    except Exception as e:
        print(f"[OpenAI] ERROR: {e}")
        await message.answer("Ошибка OpenAI. См. логи консоли.")




# --- Main ---
async def main():
    print("running")
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())