import re, json
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from db import get_connection
from keyboards import main_kb
from utils.formatting import exercise_status_icon
from services.local_planer import generate_plan
from services.openai_client import ask_openai
from config import OPENAI_API_KEY
# если хочешь промпт из файла/переменной — импортни здесь как дефолт
try:
    from prompt import PROMPT as DEFAULT_PROMPT
except Exception:
    DEFAULT_PROMPT = ""

router = Router()

# кеши на сессию процесса
EX_CACHE = {}   # {tg_id: {"date": str, "names": [str], "workout_id": int|None}}
EXPECT_INPUT = {}  # {tg_id: {"workout_id": int|None, "name": str, "set_indices": [int], "date": str}}

@router.message(F.text == "Показать тренировки")
async def list_workouts(message: Message):
    tg_id = message.from_user.id
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, date FROM workouts
        WHERE tg_id = ?
        ORDER BY date DESC, id DESC
        LIMIT 10
    """, (tg_id,))
    rows = cur.fetchall()
    if not rows:
        conn.close()
        await message.answer("У тебя ещё нет сохранённых тренировок.")
        return
    buttons = []
    for r in rows:
        wid, wdate = r["id"], r["date"]
        cnt = conn.execute("SELECT COUNT(DISTINCT name) AS c FROM exercises WHERE workout_id = ?", (wid,)).fetchone()["c"]
        buttons.append([InlineKeyboardButton(text=f"{wdate} — {cnt} упр.", callback_data=f"workouts:open:{wid}")])
    conn.close()
    await message.answer("Последние тренировки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("workouts:open:"))
async def workouts_open(callback: CallbackQuery):
    tg_id = callback.from_user.id
    try:
        wid = int(callback.data.split(":")[-1])
    except Exception:
        await callback.answer("Ошибка id тренировки", show_alert=False)
        return

    conn = get_connection(); cur = conn.cursor()
    wrow = cur.execute("SELECT id, date FROM workouts WHERE id = ? AND tg_id = ?", (wid, tg_id)).fetchone()
    if not wrow:
        conn.close()
        await callback.answer("Нет доступа к этой тренировке", show_alert=False)
        return

    cur.execute("SELECT DISTINCT e.name FROM exercises e WHERE e.workout_id = ? ORDER BY e.name COLLATE NOCASE", (wid,))
    names = [row[0] for row in cur.fetchall()]

    rows_btn = []
    for i, name in enumerate(names, start=1):
        cur.execute("""
            SELECT e.set_index, e.target_reps, e.actual_reps
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE e.workout_id = ? AND w.tg_id = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (wid, tg_id, name))
        rset = cur.fetchall()
        icon = exercise_status_icon(rset)
        label = f"{icon} {name}" if icon else name
        rows_btn.append([InlineKeyboardButton(text=label, callback_data=f"plan:ex:{i}")])
    conn.close()

    EX_CACHE[tg_id] = {"date": wrow["date"], "names": names, "workout_id": wid}
    rows_btn.append([InlineKeyboardButton(text="🗑 Удалить тренировку", callback_data=f"plan:del:{wid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows_btn)
    try:
        await callback.message.edit_text(f"Тренировка за {wrow['date']}:", reply_markup=kb)
    except Exception:
        await callback.message.answer(f"Тренировка за {wrow['date']}:", reply_markup=kb)
    await callback.answer()

@router.message(F.text == "Новая тренировка")
async def new_training_local(message: Message):
    tg_id = message.from_user.id
    conn = get_connection(); cur = conn.cursor()
    user = cur.execute("SELECT name, age, height, weight, goal, experience FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    user_info = dict(user) if user else {}
    user_info_ru = {"Имя": user_info.get("name"), "Возраст": user_info.get("age"), "Рост": user_info.get("height"),
                    "Вес": user_info.get("weight"), "Цель": user_info.get("goal"), "Опыт": user_info.get("experience")}
    since = (datetime.now(timezone.utc).date() - timedelta(days=30)).strftime("%Y-%m-%d")
    cur.execute("""
        SELECT w.date AS date, e.name AS exercise, e.set_index AS set_number,
               e.weight AS weight, e.target_reps AS target_reps, e.actual_reps AS actual_reps
        FROM workouts w JOIN exercises e ON e.workout_id = w.id
        WHERE w.tg_id = ? AND w.date >= ?
        ORDER BY w.date ASC, w.id ASC, e.set_index ASC
    """, (tg_id, since))
    history_rows = [dict(r) for r in cur.fetchall()]
    history_ru = [{"дата": r["date"], "упражнение": r["exercise"], "подход": r["set_number"],
                   "вес": r["weight"], "целевые_повторения": r["target_reps"], "выполненные_повторения": r["actual_reps"]}
                  for r in history_rows]
    payload = {"пользователь": user_info_ru, "история": history_ru}
    ob = cur.execute(
        "SELECT bench_max_kg, cgbp_max_kg, squat_max_kg, pullups_reps, deadlift_max_kg, dips_reps, ohp_max_kg FROM users WHERE tg_id = ?",
        (tg_id,)
    ).fetchone()
    payload["анкета"] = {
        "жим_лёжа_макс_кг": ob["bench_max_kg"] if ob else None,
        "узкий_жим_лёжа_макс_кг": ob["cgbp_max_kg"] if ob else None,
        "присед_макс_кг": ob["squat_max_kg"] if ob else None,
        "подтягивания_повторы": ob["pullups_reps"] if ob else None,
        "становая_макс_кг": ob["deadlift_max_kg"] if ob else None,
        "брусья_повторы": ob["dips_reps"] if ob else None,
        "ohp_max_kg": ob["ohp_max_kg"] if ob else None,
    }
    conn.close()

    try:
        plan_items = generate_plan(payload)
    except Exception as e:
        await message.answer(f"Локальный планировщик упал: {e}")
        return

    if not plan_items:
        await message.answer("Локальный планировщик вернул пустой список.")
        return

    today_iso = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
    conn2 = get_connection(); cur2 = conn2.cursor()
    cur2.execute("INSERT INTO workouts (tg_id, date, notes) VALUES (?, ?, ?)", (tg_id, today_iso, "auto from local_planer"))
    workout_id = cur2.lastrowid

    inserted = 0
    for item in plan_items:
        try:
            name = item.get("Название упражнения"); si = int(item.get("Номер подхода"))
            weight = item.get("Вес"); weight = int(weight) if weight is not None else None
            target = item.get("Количество повторений"); target = int(target) if target is not None else None
            if not name or si is None: continue
            cur2.execute("""
                INSERT INTO exercises(workout_id,name,set_index,weight,target_reps,actual_reps,date)
                VALUES(?,?,?,?,?,NULL,?)
            """, (workout_id, name, si, weight, target, today_iso))
            inserted += 1
        except Exception as ex:
            print(f"[DB] Skip row: {ex} | {item}")
    conn2.commit(); conn2.close()

    # UI
    conn3 = get_connection(); cur3 = conn3.cursor()
    cur3.execute("SELECT DISTINCT name FROM exercises WHERE workout_id = ? ORDER BY name COLLATE NOCASE", (workout_id,))
    names = [r[0] for r in cur3.fetchall()]; conn3.close()

    if not names:
        await message.answer("План сохранён, но упражнений не найдено.")
        return

    EX_CACHE[tg_id] = {"date": today_iso, "names": names, "workout_id": workout_id}
    rows = [[InlineKeyboardButton(text=n, callback_data=f"plan:ex:{i}") ] for i, n in enumerate(names, start=1)]
    rows.append([InlineKeyboardButton(text="🗑 Удалить тренировку", callback_data=f"plan:del:{workout_id}")])
    await message.answer("Упражнения на сегодня (локальный план):",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.message(F.text == "Новая AI тренировка")
async def new_training_ai(message: Message):
    tg_id = message.from_user.id
    conn = get_connection(); cur = conn.cursor()
    user = cur.execute("SELECT name, age, height, weight, goal, experience FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    user_info = dict(user) if user else {}
    user_info_ru = {"Имя": user_info.get("name"), "Возраст": user_info.get("age"), "Рост": user_info.get("height"),
                    "Вес": user_info.get("weight"), "Цель": user_info.get("goal"), "Опыт": user_info.get("experience")}
    since = (datetime.now(timezone.utc).date() - timedelta(days=30)).strftime("%Y-%m-%d")
    cur.execute("""
        SELECT w.date AS date, e.name AS exercise, e.set_index AS set_number,
               e.weight AS weight, e.target_reps AS target_reps, e.actual_reps AS actual_reps
        FROM workouts w JOIN exercises e ON e.workout_id = w.id
        WHERE w.tg_id = ? AND w.date >= ?
        ORDER BY w.date ASC, w.id ASC, e.set_index ASC
    """, (tg_id, since))
    history_rows = [dict(r) for r in cur.fetchall()]
    history_ru = [{"дата": r["date"], "упражнение": r["exercise"], "подход": r["set_number"],
                   "вес": r["weight"], "целевые_повторения": r["target_reps"], "выполненные_повторения": r["actual_reps"]}
                  for r in history_rows]
    payload = {"пользователь": user_info_ru, "история": history_ru}
    ob = cur.execute(
        "SELECT bench_max_kg, cgbp_max_kg, squat_max_kg, pullups_reps, deadlift_max_kg, dips_reps, ohp_max_kg FROM users WHERE tg_id = ?",
        (tg_id,)
    ).fetchone()
    payload["анкета"] = {
        "жим_лёжа_макс_кг": ob["bench_max_kg"] if ob else None,
        "узкий_жим_лёжа_макс_кг": ob["cgbp_max_kg"] if ob else None,
        "присед_макс_кг": ob["squat_max_kg"] if ob else None,
        "подтягивания_повторы": ob["pullups_reps"] if ob else None,
        "становая_макс_кг": ob["deadlift_max_kg"] if ob else None,
        "брусья_повторы": ob["dips_reps"] if ob else None,
        "ohp_max_kg": ob["ohp_max_kg"] if ob else None,
    }
    conn.close()

    # Получить пользовательский prompt из профиля; если пусто — взять дефолт из prompt.py
    conn_p = get_connection(); cur_p = conn_p.cursor()
    row_p = cur_p.execute("SELECT prompt FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    conn_p.close()
    user_prompt = (row_p["prompt"] if row_p else None)
    prompt_text = (user_prompt or "").strip() or DEFAULT_PROMPT

    if not OPENAI_API_KEY:
        await message.answer("Ошибка OpenAI: проверь ключ в .env (для AI-плана)")
        return

    raw, items = ask_openai(payload, prompt_text)
    print("[OpenAI] RAW:\n", raw)

    if not items:
        await message.answer("План от OpenAI не разобрался. См. логи.")
        return

    today_iso = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
    conn2 = get_connection(); cur2 = conn2.cursor()
    cur2.execute("INSERT INTO workouts (tg_id, date, notes) VALUES (?, ?, ?)", (tg_id, today_iso, "auto from OpenAI"))
    workout_id = cur2.lastrowid

    inserted = 0
    for it in items:
        try:
            name = it.get("Название упражнения")
            si = int(it.get("Номер подхода"))
            weight = it.get("Вес"); weight = int(weight) if weight is not None else None
            target = it.get("Количество повторений"); target = int(target) if target is not None else None
            if not name or si is None: continue
            cur2.execute("""
                INSERT INTO exercises(workout_id,name,set_index,weight,target_reps,actual_reps,date)
                VALUES(?,?,?,?,?,NULL,?)
            """, (workout_id, name, si, weight, target, today_iso))
            inserted += 1
        except Exception as ex:
            print(f"[DB] Skip row: {ex} | {it}")
    conn2.commit(); conn2.close()

    conn3 = get_connection(); cur3 = conn3.cursor()
    cur3.execute("SELECT DISTINCT name FROM exercises WHERE workout_id = ? ORDER BY name COLLATE NOCASE", (workout_id,))
    names = [r[0] for r in cur3.fetchall()]; conn3.close()

    EX_CACHE[tg_id] = {"date": today_iso, "names": names, "workout_id": workout_id}
    rows = [[InlineKeyboardButton(text=n, callback_data=f"plan:ex:{i}") ] for i, n in enumerate(names, start=1)]
    rows.append([InlineKeyboardButton(text="🗑 Удалить тренировку", callback_data=f"plan:del:{workout_id}")])
    await message.answer("Упражнения на сегодня:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("plan:ex:"))
async def plan_open_exercise(callback: CallbackQuery):
    tg_id = callback.from_user.id
    try: idx = int(callback.data.split(":")[-1])
    except:
        await callback.answer("Ошибка индекса", show_alert=False); return

    cache = EX_CACHE.get(tg_id)
    if not cache or not cache.get("names"):
        await callback.message.answer("План не найден. Сформируй новую тренировку.")
        await callback.answer(); return

    names = cache["names"]
    if not (1 <= idx <= len(names)):
        await callback.answer("Нет такого упражнения", show_alert=False); return

    name = names[idx-1]
    workout_id = cache.get("workout_id")
    conn = get_connection(); cur = conn.cursor()
    if workout_id:
        cur.execute("""
            SELECT e.set_index, e.weight, e.target_reps, e.actual_reps
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE e.workout_id = ? AND w.tg_id = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (workout_id, tg_id, name))
    else:
        cur.execute("""
            SELECT e.set_index, e.weight, e.target_reps, e.actual_reps
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE w.tg_id = ? AND w.date = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (tg_id, cache.get("date"), name))
    rows = cur.fetchall(); conn.close()
    if not rows:
        await callback.answer("Нет подходов", show_alert=False); return

    set_indices = [r["set_index"] for r in rows]
    EXPECT_INPUT[tg_id] = {"workout_id": workout_id if workout_id else None, "name": name,
                           "set_indices": set_indices, "date": EX_CACHE.get(tg_id, {}).get("date")}

    icon = exercise_status_icon(rows)
    lines = [f"<b>{icon + ' ' if icon else ''}{name}</b>"] + [
        f"Подход {r['set_index']}: вес {r['weight']} × повторы {r['target_reps']} (вып.: {r['actual_reps'] if r['actual_reps'] is not None else '—'})"
        for r in rows
    ]
    lines += ["", "Пришли количество выполненных повторений через пробел, по порядку сетов. Например: 8 8 7 6"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data="plan:back")]])
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(F.text)
async def input_actual_reps(message: Message):
    tg_id = message.from_user.id
    pending = EXPECT_INPUT.get(tg_id)
    if not pending:
        return
    expected_cnt = len(pending.get("set_indices", []))

    parts = re.split(r"[\s,]+", (message.text or "").strip())
    reps = []
    for p in parts:
        if not p: continue
        try: reps.append(int(p))
        except:
            await message.answer("Только целые числа через пробел. Пример: 8 8 7 6"); return
        if reps[-1] < 0:
            await message.answer("Числа должны быть неотрицательными. Пример: 8 8 7 6"); return

    if not reps:
        await message.answer("Ничего не понял. Пришли числа через пробел, напр.: 8 8 7 6"); return
    if expected_cnt and len(reps) != expected_cnt:
        await message.answer(
            f"Количество значений не совпадает с числом подходов.\n"
            f"Ожидаю: <b>{expected_cnt}</b>, прислано: <b>{len(reps)}</b>.\n"
            "Пришли повторы через пробел, строго по порядку сетов.", parse_mode="HTML"
        )
        return

    name = pending["name"]; workout_id = pending.get("workout_id"); date = pending.get("date")
    conn = get_connection(); cur = conn.cursor()
    if workout_id:
        cur.execute("""
            SELECT e.id, e.set_index
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE e.workout_id = ? AND w.tg_id = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (workout_id, tg_id, name))
    else:
        cur.execute("""
            SELECT e.id, e.set_index
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE w.tg_id = ? AND w.date = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (tg_id, date, name))
    rows = cur.fetchall()
    if not rows:
        conn.close()
        EXPECT_INPUT.pop(tg_id, None)
        await message.answer("Не нашёл подходы для обновления. Сформируй план заново.")
        return

    cnt = 0
    for i, row in enumerate(rows):
        if i >= len(reps): break
        cur.execute("UPDATE exercises SET actual_reps = ? WHERE id = ?", (reps[i], row["id"]))
        cnt += 1
    conn.commit(); conn.close()
    EXPECT_INPUT.pop(tg_id, None)

    # re-render
    conn2 = get_connection(); cur2 = conn2.cursor()
    if workout_id:
        cur2.execute("""
            SELECT e.set_index, e.weight, e.target_reps, e.actual_reps
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE e.workout_id = ? AND w.tg_id = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (workout_id, tg_id, name))
    else:
        cur2.execute("""
            SELECT e.set_index, e.weight, e.target_reps, e.actual_reps
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE w.tg_id = ? AND w.date = ? AND e.name = ?
            ORDER BY e.set_index ASC
        """, (tg_id, date, name))
    rows2 = cur2.fetchall(); conn2.close()

    icon2 = exercise_status_icon(rows2)
    lines = [f"<b>{icon2 + ' ' if icon2 else ''}{name}</b>"] + [
        f"Подход {r['set_index']}: вес {r['weight']} × повторы {r['target_reps']} (вып.: {r['actual_reps'] if r['actual_reps'] is not None else '—'})"
        for r in rows2
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data="plan:back")]])
    await message.answer(f"Сохранил {cnt} значений.\n\n" + "\n".join(lines), reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "plan:back")
async def plan_back(callback: CallbackQuery):
    tg_id = callback.from_user.id
    cache = EX_CACHE.get(tg_id)
    if not cache:
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        conn = get_connection(); cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT e.name
            FROM exercises e JOIN workouts w ON w.id = e.workout_id
            WHERE w.tg_id = ? AND w.date = ?
            ORDER BY e.name COLLATE NOCASE
        """, (tg_id, today))
        names = [r[0] for r in cur.fetchall()]; conn.close()
        if not names:
            await callback.message.edit_text("На сегодня упражнений не найдено."); await callback.answer(); return
        EX_CACHE[tg_id] = {"date": today, "names": names, "workout_id": None}
    else:
        names = cache.get("names", [])

    rows = []; wid = cache.get("workout_id") if cache else None
    if wid:
        conn = get_connection(); cur = conn.cursor()
        for i, name in enumerate(names, start=1):
            cur.execute("""
                SELECT e.set_index, e.target_reps, e.actual_reps
                FROM exercises e JOIN workouts w ON w.id = e.workout_id
                WHERE e.workout_id = ? AND w.tg_id = ? AND e.name = ?
                ORDER BY e.set_index ASC
            """, (wid, tg_id, name))
            rset = cur.fetchall()
            icon = exercise_status_icon(rset)
            label = f"{icon} {name}" if icon else name
            rows.append([InlineKeyboardButton(text=label, callback_data=f"plan:ex:{i}")])
        conn.close()
        rows.append([InlineKeyboardButton(text="🗑 Удалить тренировку", callback_data=f"plan:del:{wid}")])
    else:
        rows = [[InlineKeyboardButton(text=n, callback_data=f"plan:ex:{i}")] for i, n in enumerate(names, start=1)]
    try:
        await callback.message.edit_text("Упражнения на сегодня:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:
        await callback.message.answer("Упражнения на сегодня:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()

@router.callback_query(F.data.startswith("plan:del:"))
async def plan_delete(callback: CallbackQuery):
    tg_id = callback.from_user.id
    try:
        wid = int(callback.data.split(":")[-1])
    except Exception:
        await callback.answer("Ошибка id тренировки", show_alert=False); return

    conn = get_connection(); cur = conn.cursor()
    row = cur.execute("SELECT id, date FROM workouts WHERE id = ? AND tg_id = ?", (wid, tg_id)).fetchone()
    conn.close()
    if not row:
        await callback.answer("Нет доступа к этой тренировке", show_alert=False); return

    w_date = row["date"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Удалить", callback_data=f"plan:del_confirm:{wid}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data="plan:back")],
    ])
    try:
        await callback.message.edit_text(f"Удалить тренировку за {w_date}?", reply_markup=kb)
    except Exception:
        await callback.message.answer(f"Удалить тренировку за {w_date}?", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("plan:del_confirm:"))
async def plan_delete_confirm(callback: CallbackQuery):
    tg_id = callback.from_user.id
    try:
        wid = int(callback.data.split(":")[-1])
    except Exception:
        await callback.answer("Ошибка id тренировки", show_alert=False); return

    conn = get_connection(); cur = conn.cursor()
    row = cur.execute("SELECT id FROM workouts WHERE id = ? AND tg_id = ?", (wid, tg_id)).fetchone()
    if not row:
        conn.close(); await callback.answer("Нет доступа к этой тренировке", show_alert=False); return

    cur.execute("DELETE FROM exercises WHERE workout_id = ?", (wid,))
    cur.execute("DELETE FROM workouts WHERE id = ?", (wid,))
    conn.commit(); conn.close()

    if EX_CACHE.get(tg_id, {}).get("workout_id") == wid:
        EX_CACHE.pop(tg_id, None)
    EXPECT_INPUT.pop(tg_id, None)

    await callback.message.edit_text("Тренировка удалена.")
    await callback.answer()