from aiogram.fsm.state import State, StatesGroup


class RegState(StatesGroup):
    name   = State()
    phone  = State()
    region = State()
    terms  = State()

class AdminState(StatesGroup):
    setting_input = State()

class AdState(StatesGroup):
    audience   = State()   # Kim: clinic/zubtex/seller
    regions    = State()   # Viloyatlar (checkbox)
    content    = State()   # Matn/rasm/link
    confirm    = State()   # Tasdiqlash

class AdState(StatesGroup):
    """Reklama e'lon berish."""
    audience  = State()   # Kimlar: klinika/zubtex/seller
    regions   = State()   # Viloyatlar
    content   = State()   # Rasm/matn/link
    confirm   = State()   # Tasdiqlash

class NeedState(StatesGroup):
    product  = State()
    qty      = State()
    deadline = State()

class BulkState(StatesGroup):
    items    = State()   # Mahsulotlar ro'yxati (list of dicts)
    deadline = State()

class TopupState(StatesGroup):
    amount  = State()
    receipt = State()

class OfferState(StatesGroup):
    price = State()
    note  = State()

class ShopState(StatesGroup):
    cat  = State()
    name = State()

class MyProductsState(StatesGroup):
    editing = State()   # ro'yxat tahrirlash

class CheckoutState(StatesGroup):
    address      = State()
    phone        = State()
    recipient    = State()
    delivery     = State()
    delivery_fee = State()
    confirm      = State()

class SupportState(StatesGroup):
    waiting_message = State()
    waiting_reply   = State()

class PhotoOrderState(StatesGroup):
    waiting_photo   = State()
    waiting_caption = State()

class ReviewState(StatesGroup):
    waiting_comment = State()

class ComplaintState(StatesGroup):
    waiting_reason = State()

class QuickOrderState(StatesGroup):
    waiting_qty = State()

class AgentState(StatesGroup):
    """🤖 AI agent — mahsulot kartochkasini suhbat orqali yaratish."""
    active = State()   # matn/rasm qabul qilinadi
    field  = State()   # muayyan maydonni tahrirlash (data['ef'])

