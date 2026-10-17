from aiogram.fsm.state import State, StatesGroup


class StarsSt(StatesGroup):
    qty = State()
    recipient = State()
    confirm = State()


class ExSt(StatesGroup):
    amount = State()
    confirm = State()


class UnSt(StatesGroup):
    wish = State()
    confirm = State()


class DevSt(StatesGroup):
    task = State()
    budget = State()
    deadline = State()
    confirm = State()


class BuySt(StatesGroup):
    confirm = State()


class SupportSt(StatesGroup):
    chat = State()


class ReviewSt(StatesGroup):
    text = State()


class AdmSt(StatesGroup):
    input = State()
    wizard = State()
    reply = State()
    post = State()
    post_confirm = State()
    broadcast = State()
    broadcast_confirm = State()
