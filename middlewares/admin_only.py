from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from config import ADMIN_IDS


class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id and user_id in ADMIN_IDS:
            return await handler(event, data)
        # если не админ — просто игнорируем событие
        return