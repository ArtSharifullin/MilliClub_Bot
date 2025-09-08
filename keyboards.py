from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# кнопка я готова
ready_keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
ready_keyboard.add(KeyboardButton("Я готов/а ✅"))