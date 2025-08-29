from aiogram.fsm.state import StatesGroup, State

class ProfileFSM(StatesGroup):
    wait_input = State()
    edit_prompt = State()

class OnboardFSM(StatesGroup):
    bench = State()
    squat = State()
    pullups = State()
    deadlift = State()
    ohp = State()
    dips = State()
    cgbp = State()

class ProfileFullFSM(StatesGroup):
    name = State()
    age = State()
    height = State()
    weight = State()
    gender = State()
    goal = State()
    experience = State()
