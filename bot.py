import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),  
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


TOKEN = "8471318802:AAEPQeC1OdlEInX6B7vkGBOJ3EZ3T3h7yVk" 
ADMIN_PASSWORD = Path("admin_password.txt").read_text(encoding="utf-8").strip()
PHOTOS_DIR = Path("photos")
PHOTOS_DIR.mkdir(exist_ok=True)
DATABASE = "database.db"
CHANNEL_ID_FILE = Path("channel_id.txt")
CHANNEL_LINK_FILE = Path("channel_link.txt")


def load_channel_id() -> int | None:
    try:
        if CHANNEL_ID_FILE.exists():
            raw = CHANNEL_ID_FILE.read_text(encoding="utf-8").strip()
            return int(raw)
    except Exception as e:
        logger.error(f"Не удалось прочитать channel_id: {e}")
    return None

def save_channel_id(cid: int) -> bool:
    try:
        CHANNEL_ID_FILE.write_text(str(cid), encoding="utf-8")
        logger.info(f"channel_id сохранён: {cid}")
        return True
    except Exception as e:
        logger.error(f"Не удалось сохранить channel_id: {e}")
        return False

def load_channel_link() -> str | None:
    try:
        if CHANNEL_LINK_FILE.exists():
            return CHANNEL_LINK_FILE.read_text(encoding="utf-8").strip() or None
    except Exception as e:
        logger.error(f"Не удалось прочитать channel_link: {e}")
    return None

def save_channel_link(link: str | None) -> None:
    try:
        CHANNEL_LINK_FILE.write_text(link or "", encoding="utf-8")
        logger.info(f"channel_link сохранён: {link}")
    except Exception as e:
        logger.error(f"Не удалось сохранить channel_link: {e}")

async def generate_channel_link(chat_id: int) -> str | None:

    try:
        chat = await bot.get_chat(chat_id)
        username = getattr(chat, "username", None)
        if username:
            return f"https://t.me/{username}"

        try:
            invite = await bot.create_chat_invite_link(chat_id=chat_id, name="VotingBot link")
            return getattr(invite, "invite_link", None)
        except Exception as e:
            logger.error(f"Не удалось создать инвайт-ссылку: {e}")
            return None
    except Exception as e:
        logger.error(f"Не удалось получить данные чата: {e}")
        return None

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


CHANNEL_ID = load_channel_id()
CHANNEL_LINK = load_channel_link()


class AdminForm(StatesGroup):
    waiting_for_password = State()
    choosing_category_for_add = State()
    waiting_for_photo = State()
    waiting_for_name = State()
    choosing_category_for_delete = State()
    waiting_for_channel_bind = State()


def init_db():
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category INTEGER NOT NULL,
                    photo_filename TEXT NOT NULL,
                    votes INTEGER DEFAULT 0,
                    added_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    user_id INTEGER,
                    participant_id INTEGER,
                    PRIMARY KEY (user_id, participant_id)
                )
            """)
            conn.commit()
        logger.info("База данных инициализирована.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")

def add_participant(name: str, category: int, photo_filename: str):
    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.execute(
                "INSERT INTO participants (name, category, photo_filename, votes, added_at) VALUES (?, ?, ?, 0, ?)",
                (name, category, photo_filename, datetime.now().isoformat())
            )
            conn.commit()
        logger.info(f"Добавлена участница: {name}, категория {category}")
    except Exception as e:
        logger.error(f"Ошибка при добавлении участницы: {e}")

def get_participants(category: int, limit=None, offset=0):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            query = "SELECT id, name, photo_filename, votes FROM participants WHERE category = ? ORDER BY votes DESC"
            if limit:
                query += " LIMIT ? OFFSET ?"
                cursor.execute(query, (category, limit, offset))
            else:
                cursor.execute(query, (category,))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Ошибка при получении участниц: {e}")
        return []

def get_top_3(category: int):
    return get_participants(category, limit=3)

def get_total_count(category: int):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM participants WHERE category = ?", (category,))
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Ошибка при подсчёте количества: {e}")
        return 0

def delete_participant(participant_id: int):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT photo_filename FROM participants WHERE id = ?", (participant_id,))
            row = cursor.fetchone()
            if row:
                photo_path = PHOTOS_DIR / row[0]
                if photo_path.exists():
                    photo_path.unlink()
                conn.execute("DELETE FROM participants WHERE id = ?", (participant_id,))
                conn.execute("DELETE FROM votes WHERE participant_id = ?", (participant_id,))
                conn.commit()
                logger.info(f"Участница с ID {participant_id} удалена.")
                return True
        return False
    except Exception as e:
        logger.error(f"Ошибка при удалении участницы: {e}")
        return False

def record_vote(user_id: int, participant_id: int):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT participant_id FROM votes WHERE user_id = ?", (user_id,))
            voted = cursor.fetchall()
            if voted:
                return False, "already_voted"
            cursor.execute("INSERT INTO votes (user_id, participant_id) VALUES (?, ?)", (user_id, participant_id))
            cursor.execute("UPDATE participants SET votes = votes + 1 WHERE id = ?", (participant_id,))
            conn.commit()
            logger.info(f"Пользователь {user_id} проголосовал за {participant_id}")
            return True, None
    except Exception as e:
        logger.error(f"Ошибка при голосовании: {e}")
        return False, "db_error"

def remove_vote(user_id: int):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT participant_id FROM votes WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False
            participant_id = row[0]
            conn.execute("DELETE FROM votes WHERE user_id = ?", (user_id,))
            conn.execute("UPDATE participants SET votes = votes - 1 WHERE id = ?", (participant_id,))
            conn.commit()
            logger.info(f"Голос пользователя {user_id} отменён.")
            return True
    except Exception as e:
        logger.error(f"Ошибка при отмене голоса: {e}")
        return False

def get_user_vote(user_id: int):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT participant_id FROM votes WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Ошибка при проверке голоса: {e}")
        return None

def get_category_name(category: int) -> str:
    """Возвращает название категории по номеру"""
    category_names = {
        1: "Недельная номинация",
        2: "Месячная номинация"
    }
    return category_names.get(category, f"Категория {category}")


def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗳️ Проголосовать", callback_data="check_subscription")]
    ])

def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главная"), KeyboardButton(text="🏆 Рейтинг")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_category_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="🗳️ Проголосовать")],
            [KeyboardButton(text="🏠 Главная")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_admin_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить"), KeyboardButton(text="🗑️ Удалить")],
            [KeyboardButton(text="🏠 Главная")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_category_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating")],
        [InlineKeyboardButton(text="🗳️ Проголосовать", callback_data="vote")],
        [InlineKeyboardButton(text="⬅️ Вернуться", callback_data="start")]
    ])

def get_back_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Вернуться", callback_data="category")]
    ])

def get_cancel_vote_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить свой голос", callback_data="unvote")],
        [InlineKeyboardButton(text="⬅️ Вернуться", callback_data="category")]
    ])

def get_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить участницу", callback_data="add_participant")],
        [InlineKeyboardButton(text="🗑️ Удалить участницу", callback_data="delete_participant")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔗 Привязать канал", callback_data="bind_channel")],
        [InlineKeyboardButton(text="⬅️ Вернуться", callback_data="start")]
    ])

def get_cancel_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить добавление", callback_data="cancel_add")],
        [InlineKeyboardButton(text="⬅️ Вернуться в админку", callback_data="admin_back")]
    ])

def get_categories_menu(action: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Недельная номинация", callback_data=f"{action}_cat_1")],
        [InlineKeyboardButton(text="Месячная номинация", callback_data=f"{action}_cat_2")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_add")],
        [InlineKeyboardButton(text="⬅️ Вернуться в админку", callback_data="admin_back")]
    ])

def get_pagination_buttons(category: int, page: int, for_delete: bool = False):
    total = get_total_count(category)
    pages = (total - 1) // 10 + 1
    buttons = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"del_page_{category}_{page-1}"
        ))
    if page < pages - 1:
        row.append(InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"del_page_{category}_{page+1}"
        ))
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_delete")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)



@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} запустил бота.")
    await message.answer(
        "Добро пожаловать в конкурс красоты! 🏆\n\nЗдесь вы можете:\n• Просматривать рейтинги участниц\n• Голосовать за понравившихся участниц\n• Отслеживать результаты конкурса\n\nНажмите кнопку ниже, чтобы проголосовать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗳️ Проголосовать", callback_data="check_subscription")]
        ])
    )
    if CHANNEL_ID is None:
        await message.answer(
            "ℹ️ Канал для проверки подписки пока не привязан.\n"
            "Отправьте команду /set_channel_id -100XXXXXXXXXX или перешлите сюда пост из нужного канала из админ панели.")

@dp.callback_query(F.data.startswith("category_"))
async def category_selected(callback: CallbackQuery, state: FSMContext):
    category = int(callback.data.split("_")[1])
    

    data = await state.get_data()
    if data.get("rating_mode"):

        top_3 = get_top_3(category)
        if not top_3:
            await callback.message.edit_text("Пока нет участниц в этой категории.", reply_markup=get_back_button())
            await callback.answer()
            return


        media_group = []
        for pid, name, photo_file, votes in top_3:
            photo_path = PHOTOS_DIR / photo_file
            if photo_path.exists():
                media_group.append(
                    InputMediaPhoto(
                        media=FSInputFile(photo_path),
                        caption=f"🏆 {name}\nГолосов: {votes}"
                    )
                )
        
        msg_ids = []
        if media_group:

            sent_messages = await callback.message.answer_media_group(media_group)
            msg_ids = [msg.message_id for msg in sent_messages]


        text = f"🏆 **Топ-3 участниц ({get_category_name(category)}):**\n\n"
        for idx, (pid, name, photo_file, votes) in enumerate(top_3, 1):
            text += f"**{idx}.** {name}\nГолосов: {votes}\n\n"

  
        await callback.message.answer(text, reply_markup=get_back_button(), parse_mode="Markdown")
        
     
        await state.update_data(rating_photo_msg_ids=msg_ids)
        await callback.answer()
    else:
       
        await state.update_data(category=category)
        await callback.message.edit_text(
            f"Вы выбрали {get_category_name(category)}. Что хотите сделать?",
            reply_markup=get_category_menu()
        )
        await callback.answer()

@dp.callback_query(F.data == "rating")
async def show_rating(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    if not category:
        await callback.message.edit_text("Выберите категорию заново.", reply_markup=get_main_menu())
        await callback.answer()
        return

    top_3 = get_top_3(category)
    if not top_3:
        await callback.message.edit_text("Пока нет участниц в этой категории.", reply_markup=get_back_button())
        await callback.answer()
        return

  
    media_group = []
    for pid, name, photo_file, votes in top_3:
        photo_path = PHOTOS_DIR / photo_file
        if photo_path.exists():
            media_group.append(
                InputMediaPhoto(
                    media=FSInputFile(photo_path),
                    caption=f"🏆 {name}\nГолосов: {votes}"
                )
            )
    
    msg_ids = []
    if media_group:
  
        sent_messages = await callback.message.answer_media_group(media_group)
        msg_ids = [msg.message_id for msg in sent_messages]


    text = f"🏆 **Топ-3 участниц ({get_category_name(category)}):**\n\n"
    for idx, (pid, name, photo_file, votes) in enumerate(top_3, 1):
        text += f"**{idx}.** {name}\nГолосов: {votes}\n\n"


    await callback.message.answer(text, reply_markup=get_back_button(), parse_mode="Markdown")
    

    await state.update_data(rating_photo_msg_ids=msg_ids)
    await callback.answer()

@dp.callback_query(F.data == "vote")
async def start_voting(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    if not category:
        await callback.message.edit_text(
            "❌ Сессия устарела. Пожалуйста, выберите категорию заново.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        await callback.answer()
        return

    participants = get_participants(category)
    if not participants:
        await callback.message.edit_text("Пока нет участниц для голосования.", reply_markup=get_back_button())
        await callback.answer()
        return

    user_vote = get_user_vote(callback.from_user.id)
    if user_vote:
        voted_part = next((p for p in participants if p[0] == user_vote), None)
        result = f"✅ Вы уже проголосовали за {voted_part[1]}." if voted_part else "Вы уже голосовали."
        await callback.message.edit_text(result, reply_markup=get_cancel_vote_button())
        await callback.answer()
        return

   
    media_group = []
    for pid, name, photo_file, votes in participants:
        photo_path = PHOTOS_DIR / photo_file
        if photo_path.exists():
            media_group.append(
                InputMediaPhoto(
                    media=FSInputFile(photo_path),
                    caption=f"🗳️ {name}\nГолосов: {votes}"
                )
            )
    
    if media_group:

        sent_messages = await callback.message.answer_media_group(media_group)
        msg_ids = [msg.message_id for msg in sent_messages]
    else:
        msg_ids = []

    keyboard = []
    for pid, name, _, _ in participants:
        keyboard.append([InlineKeyboardButton(text=f"🗳️ {name}", callback_data=f"vote_for_{pid}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Вернуться", callback_data="category")])
    vote_msg = await callback.message.answer(
        "Выберите участницу, за которую хотите проголосовать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

    await state.update_data(vote_msg_id=vote_msg.message_id, photo_msg_ids=msg_ids)
    await callback.answer()

@dp.callback_query(F.data.startswith("vote_for_"))
async def process_vote(callback: CallbackQuery, state: FSMContext):
    participant_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    if get_user_vote(user_id):
        await callback.answer("Вы уже проголосовали!", show_alert=True)
        return

    success, _ = record_vote(user_id, participant_id)
    if success:
        data = await state.get_data()
        category = data["category"]

  
        for msg_id in data.get("photo_msg_ids", []):
            try:
                await bot.delete_message(callback.message.chat.id, msg_id)
            except Exception as e:
                logger.warning(f"Не удалось удалить фото: {e}")

        
        try:
            await bot.delete_message(callback.message.chat.id, data["vote_msg_id"])
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение голосования: {e}")

      
        participants = get_participants(category)
        participant = next((p for p in participants if p[0] == participant_id), None)
        name = participant[1] if participant else "участницу"

       
        await callback.message.answer(
            f"✅ Вы проголосовали за {name}!",
            reply_markup=get_cancel_vote_button()
        )

       
        try:
            await bot.delete_message(callback.message.chat.id, callback.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить исходное сообщение: {e}")

        await callback.answer()

@dp.callback_query(F.data == "unvote")
async def unvote(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if remove_vote(user_id):
        data = await state.get_data()
        category = data.get("category")

        await callback.message.answer(
            "❌ Ваш голос отменён. Теперь можно проголосовать снова.",
            reply_markup=get_category_menu()
        )
        try:
            await bot.delete_message(callback.message.chat.id, callback.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение при отмене: {e}")

        logger.info(f"Пользователь {user_id} отменил свой голос.")
    else:
        await callback.message.edit_text(
            "❌ Не удалось отменить голос (возможно, вы не голосовали).",
            reply_markup=get_back_button()
        )
    await callback.answer()


@dp.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("Админка доступна только в личных сообщениях.")
        return
    await message.answer("Введите пароль:")
    await state.set_state(AdminForm.waiting_for_password)

@dp.message(AdminForm.waiting_for_password)
async def check_password(message: Message, state: FSMContext):
    if message.text == ADMIN_PASSWORD:
        await message.answer("✅ Доступ разрешён.", reply_markup=get_admin_menu())
        await message.answer(
            text=".",
            reply_markup=get_admin_reply_keyboard()
        )
        await state.set_state(None)
        logger.info(f"Админ {message.from_user.id} вошёл в панель.")
    else:
        await message.answer("❌ Неверный пароль.")
        logger.warning(f"Неудачная попытка входа в админку: {message.from_user.id}")
        await state.set_state(None)

@dp.callback_query(F.data == "add_participant")
async def choose_category_for_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.choosing_category_for_add)
    await callback.message.edit_text("В какую категорию добавить участницу?", reply_markup=get_categories_menu("add"))
    await callback.answer()

@dp.callback_query(F.data.startswith("add_cat_"))
async def add_participant_choose_category(callback: CallbackQuery, state: FSMContext):
    category = int(callback.data.split("_")[2])
    await state.update_data(add_category=category)
    await state.set_state(AdminForm.waiting_for_photo)
    await callback.message.edit_text("Отправьте фото участницы.", reply_markup=get_cancel_button())
    await callback.answer()

@dp.callback_query(F.data == "cancel_add")
async def cancel_add(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Добавление отменено.", reply_markup=get_admin_menu())
    await callback.answer()
    logger.info(f"Админ {callback.from_user.id} отменил добавление участницы.")

@dp.message(AdminForm.waiting_for_photo, F.photo)
async def get_photo(message: Message, state: FSMContext):
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        ext = file.file_path.split('.')[-1]
        filename = f"{message.from_user.id}_{int(datetime.now().timestamp())}.{ext}"
        file_path = PHOTOS_DIR / filename
        await bot.download_file(file.file_path, file_path)

        await state.update_data(photo_filename=filename)
        await state.set_state(AdminForm.waiting_for_name)
        await message.answer("Теперь отправьте ФИО участницы.", reply_markup=get_cancel_button())
        logger.info(f"Фото получено: {filename}")
    except Exception as e:
        logger.error(f"Ошибка при загрузке фото: {e}")
        await message.answer("Произошла ошибка при сохранении фото. Попробуйте снова.")

@dp.message(AdminForm.waiting_for_photo)
async def get_photo_invalid(message: Message):
    await message.answer("Пожалуйста, отправьте фото (изображение), а не текст.", reply_markup=get_cancel_button())

@dp.message(AdminForm.waiting_for_name)
async def get_name_and_save(message: Message, state: FSMContext):
    try:
        name = message.text.strip()
        if not name:
            await message.answer("Имя не может быть пустым. Попробуйте снова.", reply_markup=get_cancel_button())
            return

        data = await state.get_data()
        photo_filename = data["photo_filename"]
        category = data["add_category"]

        add_participant(name, category, photo_filename)
        await message.answer(
            f"✅ Участница *{name}* добавлена в {get_category_name(category)}.",
            reply_markup=get_admin_menu(),
            parse_mode="Markdown"
        )
        await state.clear()
        logger.info(f"Участница добавлена: {name}, категория {category}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении участницы: {e}")
        await message.answer("Произошла ошибка. Попробуйте снова.")
        await state.clear()

@dp.callback_query(F.data == "delete_participant")
async def choose_category_for_delete(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.choosing_category_for_delete)
    await callback.message.edit_text("Из какой категории удалить участницу?", reply_markup=get_categories_menu("delete"))
    await callback.answer()

@dp.callback_query(F.data.startswith("delete_cat_"))
async def delete_participant_choose_category(callback: CallbackQuery, state: FSMContext):
    category = int(callback.data.split("_")[2])
    await state.update_data(delete_category=category, delete_page=0)
    await show_delete_page(callback, category, 0)
    await callback.answer()

async def show_delete_page(callback: CallbackQuery, category: int, page: int):
    participants = get_participants(category, limit=10, offset=page*10)
    total = get_total_count(category)
    pages = (total - 1) // 10 + 1

    keyboard = []
    for pid, name, _, _ in participants:
        keyboard.append([InlineKeyboardButton(text=f"❌ {name}", callback_data=f"confirm_delete_{pid}")])
    keyboard.append([InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_delete")])
    if page > 0 or page < pages - 1:
        pagination = []
        if page > 0:
            pagination.append(InlineKeyboardButton(text="⬅️", callback_data=f"del_page_{category}_{page-1}"))
        if page < pages - 1:
            pagination.append(InlineKeyboardButton(text="➡️", callback_data=f"del_page_{category}_{page+1}"))
        keyboard.append(pagination)

    text = f"Выберите участницу для удаления ({get_category_name(category)}, стр. {page+1}/{pages}):"
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        else:
            await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except Exception as e:
        logger.error(f"Ошибка при показе страницы удаления: {e}")

@dp.callback_query(F.data.startswith("del_page_"))
async def paginate_delete(callback: CallbackQuery):
    try:
        _, cat, page = callback.data.split("_")
        await show_delete_page(callback, int(cat), int(page))
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка пагинации: {e}")
        await callback.answer("Произошла ошибка.", show_alert=True)

@dp.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Удаление отменено.", reply_markup=get_admin_menu())
    await callback.answer()
    logger.info(f"Админ {callback.from_user.id} отменил удаление.")

@dp.callback_query(F.data.startswith("confirm_delete_"))
async def confirm_delete(callback: CallbackQuery):
    participant_id = int(callback.data.split("_")[2])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, удалить", callback_data=f"do_delete_{participant_id}")],
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_delete")]
    ])
    await callback.message.edit_text("Вы уверены, что хотите удалить эту участницу?", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("do_delete_"))
async def do_delete(callback: CallbackQuery, state: FSMContext):
    participant_id = int(callback.data.split("_")[2])
    if delete_participant(participant_id):
        await callback.message.edit_text("✅ Участница удалена.", reply_markup=get_admin_menu())
    else:
        await callback.message.edit_text("❌ Ошибка удаления.", reply_markup=get_admin_menu())
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "category")
async def back_to_category(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")

    # Удаляем фотографии участниц, если они были отправлены
    photo_msg_ids = data.get("photo_msg_ids", [])
    for msg_id in photo_msg_ids:
        try:
            await bot.delete_message(callback.message.chat.id, msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить фото при возврате: {e}")

    # Удаляем фотографии рейтинга, если они были отправлены
    rating_photo_msg_ids = data.get("rating_photo_msg_ids", [])
    for msg_id in rating_photo_msg_ids:
        try:
            await bot.delete_message(callback.message.chat.id, msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить фото рейтинга при возврате: {e}")

    if not category:
        await state.clear()
        await callback.message.edit_text("Выберите категорию:", reply_markup=get_main_menu())
        await callback.answer()
        return

    await callback.message.edit_text(
        f"{get_category_name(category)}. Что хотите сделать?",
        reply_markup=get_category_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    photo_msg_ids = data.get("photo_msg_ids", [])
    for msg_id in photo_msg_ids:
        try:
            await bot.delete_message(callback.message.chat.id, msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить фото при возврате в главное меню: {e}")

    rating_photo_msg_ids = data.get("rating_photo_msg_ids", [])
    for msg_id in rating_photo_msg_ids:
        try:
            await bot.delete_message(callback.message.chat.id, msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить фото рейтинга при возврате в главное меню: {e}")

    await state.clear()
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_main_menu())
    await callback.answer()

@dp.callback_query(F.data == "show_categories")
async def show_categories(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите категорию:", reply_markup=get_main_menu())
    await callback.answer()


@dp.message(F.text == "🏠 Главная")
async def main_menu_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    photo_msg_ids = data.get("photo_msg_ids", [])
    for msg_id in photo_msg_ids:
        try:
            await bot.delete_message(message.chat.id, msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить фото при нажатии 'Главная': {e}")


    rating_photo_msg_ids = data.get("rating_photo_msg_ids", [])
    for msg_id in rating_photo_msg_ids:
        try:
            await bot.delete_message(message.chat.id, msg_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить фото рейтинга при нажатии 'Главная': {e}")

    await state.clear()
    await message.answer("Выберите категорию:", reply_markup=get_main_menu())



@dp.message(F.text == "🏆 Рейтинг")
async def rating_handler(message: Message, state: FSMContext):
    await state.update_data(rating_mode=True)
    await message.answer("Выберите категорию для просмотра рейтинга:", reply_markup=get_main_menu())
    await message.answer(text=".", reply_markup=get_main_reply_keyboard())

@dp.message(F.text == "🗳️ Проголосовать")
async def vote_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    
    if not category:
        await message.answer("Сначала выберите категорию!")
        return
    
    participants = get_participants(category)
    if not participants:
        await message.answer("Пока нет участниц для голосования.")
        return

    user_vote = get_user_vote(message.from_user.id)
    if user_vote:
        voted_part = next((p for p in participants if p[0] == user_vote), None)
        result = f"✅ Вы уже проголосовали за {voted_part[1]}." if voted_part else "Вы уже голосовали."
        await message.answer(result)
        return


    media_group = []
    for pid, name, photo_file, votes in participants:
        photo_path = PHOTOS_DIR / photo_file
        if photo_path.exists():
            media_group.append(
                InputMediaPhoto(
                    media=FSInputFile(photo_path),
                    caption=f"🗳️ {name}\nГолосов: {votes}"
                )
            )
    
    if media_group:
        sent_messages = await message.answer_media_group(media_group)
        msg_ids = [msg.message_id for msg in sent_messages]
    else:
        msg_ids = []

 
    keyboard = []
    for pid, name, _, _ in participants:
        keyboard.append([InlineKeyboardButton(text=f"🗳️ {name}", callback_data=f"vote_for_{pid}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Вернуться", callback_data="category")])
    
    vote_msg = await message.answer(
        "Выберите участницу, за которую хотите проголосовать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

    await state.update_data(vote_msg_id=vote_msg.message_id, photo_msg_ids=msg_ids)


@dp.message(F.text == "➕ Добавить")
async def admin_add_handler(message: Message, state: FSMContext):
    await state.set_state(AdminForm.choosing_category_for_add)
    await message.answer("В какую категорию добавить участницу?", reply_markup=get_categories_menu("add"))

@dp.message(F.text == "🗑️ Удалить")
async def admin_delete_handler(message: Message, state: FSMContext):
    await state.set_state(AdminForm.choosing_category_for_delete)
    await message.answer("Из какой категории удалить участницу?", reply_markup=get_categories_menu("delete"))



@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Панель администратора:", reply_markup=get_admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def show_admin_stats(callback: CallbackQuery):
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            
 
            cursor.execute("SELECT COUNT(*) FROM participants")
            total_participants = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM votes")
            total_votes = cursor.fetchone()[0]
            
    
            cursor.execute("SELECT category, COUNT(*) FROM participants GROUP BY category")
            category_stats = cursor.fetchall()
            
   
            cursor.execute("SELECT name, votes, category FROM participants ORDER BY votes DESC LIMIT 5")
            top_participants = cursor.fetchall()
            
        stats_text = f"""
📊 **Статистика конкурса:**

👥 **Общая информация:**
• Всего участниц: {total_participants}
• Всего голосов: {total_votes}

📈 **По категориям:**
"""
        
        for category, count in category_stats:
            stats_text += f"• {get_category_name(category)}: {count} участниц\n"
        
        if top_participants:
            stats_text += "\n🏆 **Топ-5 участниц:**\n"
            for i, (name, votes, category) in enumerate(top_participants, 1):
                stats_text += f"{i}. {name} ({get_category_name(category)}) - {votes} голосов\n"
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Вернуться в админку", callback_data="admin_back")]
            ]),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при показе статистики: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при загрузке статистики",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Вернуться в админку", callback_data="admin_back")]
            ])
        )
    await callback.answer()

@dp.message(Command("set_channel_id"))
async def set_channel_id_cmd(message: Message):
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.answer("Использование: /set_channel_id -100XXXXXXXXXX")
        return
    try:
        cid = int(parts[1])
        if save_channel_id(cid):
            global CHANNEL_ID, CHANNEL_LINK
            CHANNEL_ID = cid
            CHANNEL_LINK = await generate_channel_link(CHANNEL_ID)
            save_channel_link(CHANNEL_LINK)
            suffix = f"\nСсылка: {CHANNEL_LINK}" if CHANNEL_LINK else "\nСсылку получить не удалось (нужен @username или право на создание инвайта)."
            await message.answer(f"✅ Канал привязан: {cid}{suffix}")
        else:
            await message.answer("❌ Не удалось сохранить channel_id")
    except ValueError:
        await message.answer("❌ Неверный формат channel_id. Пример: -1001234567890")



@dp.callback_query(F.data == "bind_channel")
async def ask_bind_channel(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.waiting_for_channel_bind)
    text = (
        "🔗 Привязка канала\n\n"
        "Перешлите сюда ЛЮБОЙ пост из целевого канала, чтобы привязать его для проверки подписки.\n\n"
        "Совет: Бот должен быть админом в канале."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Вернуться в админку", callback_data="admin_back")]]))
    await callback.answer()

@dp.message(AdminForm.waiting_for_channel_bind)
async def bind_channel_from_forward(message: Message, state: FSMContext):
    channel_id_from_forward = None
    try:
        fo = getattr(message, "forward_origin", None)
        if fo and getattr(fo, "type", None) == "channel":
            chat_obj = getattr(fo, "chat", None)
            if chat_obj and getattr(chat_obj, "id", None):
                channel_id_from_forward = chat_obj.id
        if channel_id_from_forward is None:
            ffc = getattr(message, "forward_from_chat", None)
            if ffc and getattr(ffc, "id", None):
                channel_id_from_forward = ffc.id
    except Exception:
        channel_id_from_forward = None

    if channel_id_from_forward is None:
        await message.answer("❌ Не удалось определить канал. Перешлите именно пост из канала (не скрин и не ссылку).", reply_markup=get_admin_menu())
        return

    if save_channel_id(channel_id_from_forward):
        global CHANNEL_ID, CHANNEL_LINK
        CHANNEL_ID = channel_id_from_forward
        CHANNEL_LINK = await generate_channel_link(CHANNEL_ID)
        save_channel_link(CHANNEL_LINK)
        suffix = f"\nСсылка: {CHANNEL_LINK}" if CHANNEL_LINK else "\nСсылку получить не удалось (нужен @username или право на создание инвайта)."
        await message.answer(f"✅ Канал привязан: {CHANNEL_ID}{suffix}", reply_markup=get_admin_menu())
        await state.clear()
    else:
        await message.answer("❌ Не удалось сохранить channel_id", reply_markup=get_admin_menu())

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if CHANNEL_ID is None:
        prompt = (
            "ℹ️ Канал для проверки подписки не привязан.\n\n"
            "Сделайте одно из:\n"
            "• Отправьте команду /set_channel_id -100XXXXXXXXXX\n"
            "• В админке нажмите '🔗 Привязать канал' и перешлите пост."
        )
        try:
            await callback.message.edit_text(prompt)
        except TelegramBadRequest:
            await callback.message.answer(prompt)
        await callback.answer()
        return

    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ("member", "administrator", "creator"):
            try:
                await callback.message.edit_text(
                    "✅ Подписка на канал проверена!\n\nТеперь выберите категорию:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Недельная номинация", callback_data="category_1")],
                        [InlineKeyboardButton(text="Месячная номинация", callback_data="category_2")]
                    ])
                )
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    await callback.message.answer(
                        "✅ Подписка на канал проверена!\n\nТеперь выберите категорию:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="Недельная номинация", callback_data="category_1")],
                            [InlineKeyboardButton(text="Месячная номинация", callback_data="category_2")]
                        ])
                    )
                else:
                    raise
            await state.set_state(None)
        else:
            raise Exception("Not subscribed")
    except TelegramBadRequest as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        link = load_channel_link() or ""
        link_html = f"<a href=\"{link}\">Перейти в канал</a>\n\n" if link else ""
        prompt_text = (
            "❗️Чтобы голосовать, подпишитесь на канал и вернитесь сюда.\n\n"
            "Если канал приватный — убедитесь, что bot добавлен админом.\n\n"
            f"{link_html}"
            "После подписки нажмите кнопку ниже."
        )
        try:
            await callback.message.edit_text(
                prompt_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")]]
                ),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except TelegramBadRequest as e2:
            if "message is not modified" in str(e2):
                await callback.message.answer(
                    prompt_text,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")]]
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            else:
                raise
    except Exception:
        link = load_channel_link() or ""
        link_html = f"<a href=\"{link}\">Перейти в канал</a>\n\n" if link else ""
        prompt_text = (
            "❗️Вы не подписаны на канал. Подпишитесь, чтобы продолжить.\n\n"
            f"{link_html}"
            "После подписки нажмите кнопку ниже."
        )
        try:
            await callback.message.edit_text(
                prompt_text,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")]]
                ),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except TelegramBadRequest as e3:
            if "message is not modified" in str(e3):
                await callback.message.answer(
                    prompt_text,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")]]
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            else:
                raise
    finally:
        await callback.answer()


async def main():
    init_db()
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())