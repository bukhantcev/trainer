from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from states import OnboardFSM
from db import get_connection

router = Router()

@router.message(OnboardFSM.bench)
async def onboard_bench(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Жим лёжа — твой максимальный вес (кг)?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET bench_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.set_state(OnboardFSM.cgbp)
    await message.answer("Жим узким хватом — максимальный вес (кг)? Введи целое число.")


# Новый обработчик для OnboardFSM.cgbp
@router.message(OnboardFSM.cgbp)
async def onboard_cgbp(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try:
        val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Жим узким хватом — максимальный вес (кг)?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET cgbp_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.set_state(OnboardFSM.squat)
    await message.answer("Присед со штангой на плечах — максимальный вес (кг)? Введи целое число.")

@router.message(OnboardFSM.squat)
async def onboard_squat(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try: val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Присед со штангой на плечах — максимальный вес (кг)?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET squat_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.set_state(OnboardFSM.pullups)
    await message.answer("Сколько раз подтягиваешься (чистые повторения)? Введи целое число.")

@router.message(OnboardFSM.pullups)
async def onboard_pullups(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try: val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Сколько раз подтягиваешься (чистые повторения)?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET pullups_reps = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.set_state(OnboardFSM.deadlift)
    await message.answer("Становая тяга — максимальный вес (кг)? Введи целое число.")

@router.message(OnboardFSM.deadlift)
async def onboard_deadlift(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try: val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Становая тяга — максимальный вес (кг)?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET deadlift_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.set_state(OnboardFSM.ohp)
    await message.answer("Подъём штанги стоя (армейский жим) — максимальный вес (кг)? Введи целое число.")

@router.message(OnboardFSM.ohp)
async def onboard_ohp(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try: val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Подъём штанги стоя (армейский жим) — максимальный вес (кг)?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET ohp_max_kg = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.set_state(OnboardFSM.dips)
    await message.answer("Отжимания на брусьях — сколько повторений? Введи целое число.")

@router.message(OnboardFSM.dips)
async def onboard_dips(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    try: val = int((message.text or "").strip())
    except:
        await message.answer("Пожалуйста, введи целое число. Отжимания на брусьях — сколько повторений?")
        return
    conn = get_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET dips_reps = ? WHERE tg_id = ?", (val, tg_id))
    conn.commit(); conn.close()
    await state.clear()
    from keyboards import main_kb
    await message.answer("Спасибо! Данные сохранены. Выбирай действие ниже.", reply_markup=main_kb)