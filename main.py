import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from db import init_db
from handlers import register_all_handlers
from middlewares.admin_only import AdminOnlyMiddleware

async def main():
    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.message.middleware(AdminOnlyMiddleware())
    dp.callback_query.middleware(AdminOnlyMiddleware())
    register_all_handlers(dp)
    print("Trainer bot is running…")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())