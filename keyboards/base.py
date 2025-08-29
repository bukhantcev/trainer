from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Посмотреть профиль")],
        [KeyboardButton(text="Новая тренировка"), KeyboardButton(text="Новая AI тренировка")],
        [KeyboardButton(text="Показать тренировки")],
        [KeyboardButton(text="Изменить инструкцию")],
    ],
    resize_keyboard=True
)

def training_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧘 Пилатес/йога", callback_data="start:type:mindbody")],
        [InlineKeyboardButton(text="🏋️ Силовые тренировки", callback_data="start:type:strength")],
    ])