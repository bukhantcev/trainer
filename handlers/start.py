from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from db import get_connection, init_db
from keyboards import main_kb, training_type_kb
from states import ProfileFullFSM

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    init_db()
    tg_id = message.from_user.id
    name = message.from_user.first_name
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT id, training_type FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (tg_id, name) VALUES (?, ?)", (tg_id, name))
        conn.commit()
        training_type = None
    else:
        training_type = row["training_type"]
    conn.close()

    if not training_type:
        await message.answer("Чем вы хотите заниматься?", reply_markup=training_type_kb())
        return

    await state.clear()
    await message.answer("Готово! Профиль создан. Выбирай действие ниже.", reply_markup=main_kb)

@router.callback_query(F.data == "start:type:mindbody")
async def start_type_mindbody(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET training_type = ? WHERE tg_id = ?", ("mindbody", tg_id))
    conn.commit(); conn.close()
    await callback.message.edit_text("Окей! Пилатес/йога. Этот сценарий пока в разработке ✨")
    await callback.answer()

@router.callback_query(F.data == "start:type:strength")
async def start_type_strength(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET training_type = ? WHERE tg_id = ?", ("strength", tg_id))
    conn.commit(); conn.close()
    await state.set_state(ProfileFullFSM.name)
    await callback.message.edit_text("Давай заполним профиль полностью.\n\nКак тебя зовут?")
    await callback.answer()