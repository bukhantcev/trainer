from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from states import ProfileFSM, ProfileFullFSM, OnboardFSM
from db import get_connection
from keyboards import profile_inline_kb
from utils.formatting import format_profile_card
from utils.parsing import parse_profile_update

# Источник дефолтной инструкции из модуля prompt.py
try:
    from prompt import PROMPT as DEFAULT_PROMPT
except Exception:
    DEFAULT_PROMPT = ""

router = Router()

@router.message(F.text == "Посмотреть профиль")
async def view_profile(message: Message):
    tg_id = message.from_user.id
    conn = get_connection()
    row = conn.execute(
        "SELECT name, age, height, weight, goal, experience, gender FROM users WHERE tg_id = ?",
        (tg_id,)
    ).fetchone()
    conn.close()
    await message.answer(format_profile_card(row), parse_mode="HTML", reply_markup=profile_inline_kb())

# --- Изменение пользовательской инструкции (prompt) ------------------------
@router.message(F.text.casefold() == "изменить инструкцию")
async def edit_prompt_from_reply(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    conn = get_connection()
    row = conn.execute("SELECT prompt FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    conn.close()

    current_prompt = (row["prompt"] if row and row["prompt"] else None)
    if current_prompt is None:
        current_prompt = DEFAULT_PROMPT

    await message.answer("Вот ваши инструкции:")
    await message.answer(current_prompt if current_prompt else "— пусто —")
    await state.set_state(ProfileFSM.edit_prompt)
    await message.answer("Пришлите новый текст инструкции одним сообщением.\nМожно отправить /cancel для отмены или /default — чтобы вернуть дефолт из prompt.py.")

@router.callback_query(F.data == "profile:edit_prompt")
async def edit_prompt_from_inline(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    tg_id = callback.from_user.id
    conn = get_connection()
    row = conn.execute("SELECT prompt FROM users WHERE tg_id = ?", (tg_id,)).fetchone()
    conn.close()

    current_prompt = (row["prompt"] if row and row["prompt"] else None)
    if current_prompt is None:
        current_prompt = DEFAULT_PROMPT

    await callback.message.answer("Вот ваши инструкции:")
    await callback.message.answer(current_prompt if current_prompt else "— пусто —")
    await state.set_state(ProfileFSM.edit_prompt)
    await callback.message.answer("Пришлите новый текст инструкции одним сообщением.\nМожно отправить /cancel для отмены или /default — чтобы вернуть дефолт.")

@router.message(ProfileFSM.edit_prompt)
async def edit_prompt_save(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    tg_id = message.from_user.id

    # Отмена изменений
    if text.lower() == "/cancel":
        await state.clear()
        await message.answer("Ок, оставил без изменений. ✅")
        return

    # Сброс на дефолтный промпт (храним NULL)
    if text.lower() == "/default":
        conn = get_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET prompt = NULL WHERE tg_id = ?", (tg_id,))
        conn.commit(); conn.close()
        await state.clear()
        await message.answer("Сбросил на дефолт")
        return

    if not text:
        await message.answer("Инструкция не может быть пустой. Пришлите текст, либо /cancel, либо /default.")
        return

    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET prompt = ? WHERE tg_id = ?", (text, tg_id))
    conn.commit(); conn.close()

    await state.clear()
    await message.answer("Инструкция сохранена ✅")

@router.callback_query(F.data == "profile:edit")
async def edit_profile_cb(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Режим редактирования профиля", show_alert=False)
    await state.set_state(ProfileFSM.wait_input)
    await callback.message.answer(
        "Напиши, что изменить, в формате: Имя Алеша, Возраст 39, Рост 173, Вес 82, Цель сила, Опыт новичок, Пол мужской.\n"
        "Можно прислать только нужные поля.\n\n"
        "Варианты цели: сила, масса, сушка, общая форма.\n"
        "Варианты опыта: новичок, средний, продвинутый.\n"
        "Пол: мужской/женский. Рост и вес вводи целыми числами."
    )

@router.message(ProfileFSM.wait_input)
async def profile_update_input(message: Message, state: FSMContext):
    data = parse_profile_update(message.text or "")
    if not data:
        await message.answer("Неправильный формат. Пример: Имя Алеша, Возраст 39, Рост 173")
        return
    tg_id = message.from_user.id
    conn = get_connection(); cur = conn.cursor()
    set_clause = ", ".join(f"{k} = ?" for k in data.keys())
    values = list(data.values()) + [tg_id]
    cur.execute(f"UPDATE users SET {set_clause} WHERE tg_id = ?", values)
    conn.commit()
    row = cur.execute(
        "SELECT name, age, height, weight, goal, experience, gender FROM users WHERE tg_id = ?",
        (tg_id,)
    ).fetchone()
    conn.close()
    await state.clear()
    await message.answer(format_profile_card(row), parse_mode="HTML", reply_markup=profile_inline_kb())

@router.callback_query(F.data == "profile:refresh_form")
async def profile_refresh_form(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    conn = get_connection()
    ob = conn.execute(
        "SELECT bench_max_kg, squat_max_kg, pullups_reps, deadlift_max_kg, ohp_max_kg, dips_reps FROM users WHERE tg_id = ?",
        (tg_id,)
    ).fetchone()
    conn.close()
    prev = dict(ob) if ob else {}
    lines = [
        "Обновим анкету. Пришли новые значения по очереди на вопросы.\n",
        "Текущие значения:",
        f"Жим лёжа: {prev.get('bench_max_kg', '—')} кг",
        f"Присед со штангой: {prev.get('squat_max_kg', '—')} кг",
        f"Подтягивания: {prev.get('pullups_reps', '—')} повт.",
        f"Становая тяга: {prev.get('deadlift_max_kg', '—')} кг",
        f"Армейский жим (стоя): {prev.get('ohp_max_kg', '—')} кг",
        f"Брусья: {prev.get('dips_reps', '—')} повт.",
    ]
    await state.set_state(OnboardFSM.bench)
    await callback.message.answer("\n".join(lines) + "\n\nЖим лёжа — твой максимальный вес (кг)? Введи целое число.")
    await callback.answer()

# Полная анкета (после выбора strength)
def _is_int(s: str) -> bool:
    try:
        int(s); return True
    except Exception:
        return False

@router.message(ProfileFullFSM.name)
async def pf_name(message: Message, state: FSMContext):
    v = (message.text or "").strip()
    if not v:
        await message.answer("Имя не должно быть пустым. Введи имя ещё раз.")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET name = ? WHERE tg_id = ?", (v, message.from_user.id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.age)
    await message.answer("Возраст (целое число, лет):")

@router.message(ProfileFullFSM.age)
async def pf_age(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if not _is_int(t) or not (1 <= int(t) <= 120):
        await message.answer("Введите корректный возраст (целое число 1–120).")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET age = ? WHERE tg_id = ?", (int(t), message.from_user.id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.height)
    await message.answer("Рост (см, целое число):")

@router.message(ProfileFullFSM.height)
async def pf_height(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if not _is_int(t) or not (100 <= int(t) <= 250):
        await message.answer("Введите рост в см (целое число 100–250).")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET height = ? WHERE tg_id = ?", (int(t), message.from_user.id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.weight)
    await message.answer("Вес (кг, целое число):")

@router.message(ProfileFullFSM.weight)
async def pf_weight(message: Message, state: FSMContext):
    t = (message.text or "").strip()
    if not _is_int(t) or not (30 <= int(t) <= 400):
        await message.answer("Введите вес (целое число 30–400).")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET weight = ? WHERE tg_id = ?", (int(t), message.from_user.id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.gender)
    await message.answer("Пол (мужской/женский):")

@router.message(ProfileFullFSM.gender)
async def pf_gender(message: Message, state: FSMContext):
    raw = (message.text or "").strip().lower()
    mapping = {
        "м":"мужской","муж":"мужской","мужчина":"мужской","мужской":"мужской",
        "ж":"женский","жен":"женский","женщина":"женский","женский":"женский",
    }
    gender = mapping.get(raw, raw)
    if gender not in ("мужской", "женский"):
        await message.answer("Пол должен быть: мужской/женский. Введи ещё раз.")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET gender = ? WHERE tg_id = ?", (gender, message.from_user.id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.goal)
    await message.answer("Цель тренировки: сила / масса / сушка / общая форма — введи одно из них:")

@router.message(ProfileFullFSM.goal)
async def pf_goal(message: Message, state: FSMContext):
    raw = (message.text or "").strip().lower()
    goal = "общая форма" if raw in {"форма", "общая форма"} else raw
    if goal not in {"сила","масса","сушка","общая форма"}:
        await message.answer("Варианты цели: сила, масса, сушка, общая форма. Введи одно из них.")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET goal = ? WHERE tg_id = ?", (goal, message.from_user.id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.experience)
    await message.answer("Опыт: новичок / средний / продвинутый")

@router.message(ProfileFullFSM.experience)
async def pf_experience(message: Message, state: FSMContext):
    raw = (message.text or "").strip().lower()
    if raw not in {"новичок","средний","продвинутый"}:
        await message.answer("Варианты опыта: новичок / средний / продвинутый. Введи одно из них.")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET experience = ? WHERE tg_id = ?", (raw, message.from_user.id))
    conn.commit(); conn.close()
    # переход к силовой анкете (онбординг по базовым лифтам)
    from states import OnboardFSM
    await state.set_state(OnboardFSM.bench)
    await message.answer("Отлично! Теперь базовые вводные по силе.\n\nЖим лёжа — максимальный вес (кг)? Введи целое число.")