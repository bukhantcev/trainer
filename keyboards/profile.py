from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def profile_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить", callback_data="profile:edit")],
        [InlineKeyboardButton(text="Обновить анкету", callback_data="profile:refresh_form")],
        [InlineKeyboardButton(text="Выбор режима", callback_data="profile:mode")],
    ])