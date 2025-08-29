from aiogram import Dispatcher
from .start import router as start_router
from .profile import router as profile_router
from .onboarding import router as onboarding_router
from .plan import router as plan_router

def register_all_handlers(dp: Dispatcher):
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(onboarding_router)
    dp.include_router(plan_router)