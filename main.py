import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardRemove
from config import BOT_TOKEN
from keyboards import ready_keyboard

# логиии
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token= '8399959628:AAGWjoIqGDQaMxZS4PqQopa0HVCuFnvu7mA')
dp = Dispatcher(bot)


# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"User {user_id} started bot")

        welcome_text = (
            "<b>Я опоздал!</b>\n\n"
            "О... Кажется, это вы меня ждали? Прошу прощения! Я кролик ваш проводник.\n"
            "Нажми кнопку <b>'Я готов/а ✅'</b> чтобы получить ссылку!"
        )

        await message.answer(welcome_text, parse_mode="HTML", reply_markup=ready_keyboard)

    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")


# кнопка я готова
@dp.message_handler(lambda message: message.text and "Я готов/а" in message.text)
async def handle_ready(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"User {user_id} requested link")

        # ссылка
        link = "https://t.me/milliclubkorston"

        response_text = (
            f"<b><a href='{link}'>Добро пожаловать</a></b>\n\n"
        )

        await message.answer(response_text, parse_mode="HTML", disable_web_page_preview=False,
                             reply_markup=ReplyKeyboardRemove())

    except Exception as e:
        logger.error(f"Error in handle_ready: {e}")


#  игнор сообщений
@dp.message_handler()
async def handle_other_messages(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"User {user_id} sent message: {message.text}")


    except Exception as e:
        logger.error(f"Error in handle_other_messages: {e}")


# запуск бота
async def main():
    try:
        logger.info("Бот запускается...")
        await dp.start_polling()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")


if __name__ == "__main__":
    asyncio.run(main())