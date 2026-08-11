import asyncio
import logging
import os
import random
import sqlite3
import time

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

logging.basicConfig(level=logging.INFO)

print("🚀 ЗАПУСК RP БОТА С ЛОГИРОВАНИЕМ В ТЕМЫ")

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("❌ Не найден токен бота! Укажите переменную окружения BOT_TOKEN.")

DEFAULT_ADMIN_IDS = [1417695368, 8752640370]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DATA_DIR = "/app/data" if os.path.exists("/app") else "."
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "rp_bot.db")

last_sender_in_location = {}
fishing_cooldowns = {}

DEFAULT_SPAWN_LOCATION = "camp_1"

# --- СОСТОЯНИЯ FSM ---
class AdminStates(StatesGroup):
    waiting_for_char_name = State()
    waiting_for_char_role = State()
    waiting_for_char_moons = State()
    waiting_for_char_photo = State()
    
    waiting_for_assign_char_id = State()
    waiting_for_assign_user_id = State()
    
    waiting_for_edit_field_val = State()
    waiting_for_give_item_name = State()
    waiting_for_take_item_id = State()

    waiting_for_wl_add = State()
    waiting_for_wl_remove = State()

    waiting_for_tp_char_id = State()
    waiting_for_tp_loc_id = State()

class UserStates(StatesGroup):
    waiting_for_avatar = State()
    waiting_for_user_char_name = State()
    waiting_for_user_char_role = State()
    waiting_for_user_char_moons = State()
    waiting_for_user_char_photo = State()

# --- БАЗА ДАННЫХ И МИГРАЦИИ ---
def init_db():
    global DEFAULT_SPAWN_LOCATION
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA journal_mode=WAL;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            log_chat_id INTEGER DEFAULT NULL,
            flood_topic_id INTEGER DEFAULT NULL,
            rp_topic_id INTEGER DEFAULT NULL
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO log_settings (id) VALUES (1)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    for admin_id in DEFAULT_ADMIN_IDS:
        cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (admin_id,))

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            user_id INTEGER PRIMARY KEY
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            image_url TEXT,
            connections TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'Одиночка',
            base_moons INTEGER DEFAULT 0,
            assigned_at INTEGER DEFAULT NULL,
            user_id INTEGER DEFAULT NULL,
            current_location_id TEXT DEFAULT 'camp_1',
            photo_url TEXT DEFAULT NULL,
            hunger REAL DEFAULT 100.0,
            thirst REAL DEFAULT 100.0,
            toilet REAL DEFAULT 100.0,
            last_needs_update INTEGER DEFAULT NULL,
            created_at INTEGER DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT NULL,
            active_char_id INTEGER DEFAULT NULL,
            last_active INTEGER,
            rp_messages INTEGER DEFAULT 0,
            flood_messages INTEGER DEFAULT 0,
            total_online_seconds INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            item_type TEXT NOT NULL,
            char_id INTEGER DEFAULT NULL,
            location_id TEXT DEFAULT NULL
        )
    """)

    cursor.execute("SELECT value FROM settings WHERE key = 'default_spawn'")
    spawn_row = cursor.fetchone()
    if spawn_row:
        DEFAULT_SPAWN_LOCATION = spawn_row[0]
    else:
        cursor.execute("INSERT INTO settings (key, value) VALUES ('default_spawn', 'camp_1')")

    initial_locations = [
        ('camp_1', '🌳 Лагерь Племени [1]', 'Тропинка меж густых зеленых крон укутана прохладной тенью, где ветви могучих деревьев смыкаются сплошным пологом, скрывая землю от палящего солнца.', '', 'kit_tent_2,oruzh_tent_3,vetv_duba_12,chelit_tent_11,exit_camp_5'),
        ('kit_tent_2', 'Палатка котят [2]', 'Ждёт обновы', '', 'camp_1'),
        ('oruzh_tent_3', 'Палатка Оруженосцев [3]', 'Ждёт обновы', '', 'camp_1, voyn_tent_4'),
        ('voyn_tent_4', 'Палатка Воинов [4]', 'Ждёт обновы', '', 'oruzh_tent_3'),
        ('chelit_tent_11', 'Палатка Целителей [11]', 'Ждёт обновы', '', 'camp_1'),
        ('vetv_duba_12', 'Ветви Могучего Дуба [12]', 'Ждёт обновы', '', 'camp_1, predv_tent_13'),
        ('predv_tent_13', 'Палатка Предводителя [13]', 'Ждёт обновы', '', 'vetv_duba_12'),
        ('exit_camp_5', 'Выход из лагеря [5]', 'Ждёт обновы', '', 'camp_1, forest_6, forest_14'),
        ('forest_6', 'Лес [6]', 'Ждёт обновы', '', 'exit_camp_5, forest_7'),
        ('forest_7', 'Лес [7]', 'Ждёт обновы', '', 'forest_6, forest_14, peshera_9'),
        ('forest_14', 'Лес [14]', 'Ждёт обновы', '', 'exit_camp_5, forest_7, forest_15'),
        ('peshera_9', 'Пещера [9]', 'Ждёт обновы', '', 'forest_7'),
        ('forest_15', 'Лес [15]', 'Ждёт обновы', '', 'forest_14, forest_16'),
        ('forest_16', 'Лес [16]', 'Ждёт обновы', '', 'forest_15, tri_sos_17, cum_bereg_8'),
        ('cum_bereg_8', 'Каменистый берег [8]', 'Ждёт обновы', '', 'forest_16, rechka_24, cum_perep_10'),
        ('rechka_24', 'Речка [24]', 'Ждёт обновы', '', 'cum_bereg_8'),
        ('cum_perep_10', 'Каменная Переправа [10]', 'Ждёт обновы', '', 'cum_bereg_8'),
        ('tri_sos_17', 'Три сосны [17]', 'Ждёт обновы', '', 'gus_forest_18, forest_21, gus_forest_19, forest_16'),
        ('forest_21', 'Лес [21]', 'Ждёт обновы', '', 'tri_sos_17, okolok_22'),
        ('gus_forest_19', 'Густой Лес [19]', 'Ждёт обновы', '', 'tri_sos_17, gus_forest_18'),
        ('gus_forest_18', 'Густой Лес [18]', 'Ждёт обновы', '', 'gus_forest_20, tri_sos_17, gus_forest_19'),
        ('okolok_22', 'Околок [22]', 'Ждёт обновы', '', 'forest_21, big_pus_23'),
        ('big_pus_23', 'Большой Пустырь [23]', 'Ждёт обновы', '', 'okolok_22'),
        ('gus_forest_20', 'Густой Лес [20]', 'Ждёт обновы', '', 'gus_forest_18')
    ]

    for loc in initial_locations:
        cursor.execute("""
            INSERT INTO locations (id, name, description, image_url, connections) 
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET 
                name=excluded.name,
                description=excluded.description,
                image_url=excluded.image_url,
                connections=excluded.connections
        """, loc)

    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return row is not None or user_id in DEFAULT_ADMIN_IDS

def user_has_access(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM whitelist WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return row is not None

def add_to_whitelist(user_id: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO whitelist (user_id) VALUES (?)", (user_id,))
        conn.commit()

def remove_from_whitelist(user_id: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
        conn.commit()

def get_default_spawn() -> str:
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'default_spawn'")
        row = cursor.fetchone()
        return row[0] if row else "camp_1"

def set_default_spawn(loc_id: str):
    global DEFAULT_SPAWN_LOCATION
    DEFAULT_SPAWN_LOCATION = loc_id
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_spawn', ?)", (loc_id,))
        conn.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ЛОГИРОВАНИЯ ---
def get_log_config():
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT log_chat_id, flood_topic_id, rp_topic_id FROM log_settings WHERE id = 1")
        return cursor.fetchone()

async def send_to_log(category: str, text: str, photo: str = None):
    log_chat_id, flood_topic_id, rp_topic_id = get_log_config()
    if not log_chat_id:
        return

    target_topic = rp_topic_id if category == "rp" else flood_topic_id

    try:
        kwargs = {"chat_id": log_chat_id, "parse_mode": "Markdown"}
        if target_topic:
            kwargs["message_thread_id"] = target_topic

        if photo:
            await bot.send_photo(photo=photo, caption=text, **kwargs)
        else:
            await bot.send_message(text=text, **kwargs)
    except Exception as e:
        logging.error(f"⚠️ Ошибка отправки лога категории '{category}': {e}")

# --- КОМАНДЫ НАСТРОЙКИ ЧАТА ЛОГОВ И ТЕМ ---
@dp.message(F.text.in_({"+logs", "/logs"}))
async def cmd_set_log_chat(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав админа.")
    if message.chat.type == "private":
        return await message.answer("⚠️ Команду `+logs` нужно отправлять в группе/супергруппе для логов!")

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE log_settings SET log_chat_id = ? WHERE id = 1", (message.chat.id,))
        conn.commit()

    await message.answer(f"✅ Этот чат (`{message.chat.id}`) успешно установлен как чат логов!")

@dp.message(F.text.in_({"+флудлог", "/floodlog", "/флудлог"}))
async def cmd_set_flood_topic(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав админа.")
    
    topic_id = message.message_thread_id

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE log_settings SET log_chat_id = ?, flood_topic_id = ? WHERE id = 1", (message.chat.id, topic_id))
        conn.commit()

    topic_str = f"в теме #{topic_id}" if topic_id else "в основном чате"
    await message.answer(f"💬 Категория **[Логи флуда]** успешно привязана к текущему чату ({topic_str})!")

@dp.message(F.text.in_({"+рплог", "/rplog", "/рплог"}))
async def cmd_set_rp_topic(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав админа.")

    topic_id = message.message_thread_id

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE log_settings SET log_chat_id = ?, rp_topic_id = ? WHERE id = 1", (message.chat.id, topic_id))
        conn.commit()

    topic_str = f"в теме #{topic_id}" if topic_id else "в основном чате"
    await message.answer(f"🎭 Категория **[Логи Ролеплея]** успешно привязана к текущему чату ({topic_str})!")

def calculate_in_game_time():
    now = time.time()
    seconds_in_game_day = 86400 / 4
    current_game_seconds = int((now % seconds_in_game_day) * 4)

    hours = current_game_seconds // 3600
    minutes = (current_game_seconds % 3600) // 60

    if 5 <= hours < 11:
        part = "🌅 Утро"
    elif 11 <= hours < 17:
        part = "☀️ День"
    elif 17 <= hours < 22:
        part = "🌆 Вечер"
    else:
        part = "🌙 Ночь"

    return f"{hours:02d}:{minutes:02d} ({part})"

def calculate_moons(base_moons: int, assigned_at: int):
    if not assigned_at:
        return base_moons
    now = int(time.time())
    passed_days = (now - assigned_at) // (14 * 86400)
    return base_moons + passed_days

def update_needs(char_id: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT hunger, thirst, toilet, last_needs_update FROM characters WHERE id = ?", (char_id,))
        row = cursor.fetchone()

        if not row:
            return 100.0, 100.0, 100.0

        hunger, thirst, toilet, last_update = row
        now = int(time.time())

        if last_update is None:
            cursor.execute("UPDATE characters SET last_needs_update = ? WHERE id = ?", (now, char_id))
            conn.commit()
            return hunger, thirst, toilet

        hours_passed = (now - last_update) / 3600.0

        if hours_passed > 0:
            new_thirst = max(0.0, thirst - (hours_passed * 10.0))
            new_toilet = max(0.0, toilet - (hours_passed * 12.0))

            cursor.execute("""
                UPDATE characters 
                SET thirst = ?, toilet = ?, last_needs_update = ? 
                WHERE id = ?
            """, (new_thirst, new_toilet, now, char_id))
            conn.commit()
            
            thirst, toilet = new_thirst, new_toilet

    return hunger, thirst, toilet

def update_activity(user_id: int, username: str = None, active_char_id: int = None, is_rp: bool = None):
    now = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT last_active, total_online_seconds, rp_messages, flood_messages, username FROM user_activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        clean_username = username.lstrip("@").lower() if username else None

        if not row:
            rp_cnt = 1 if is_rp is True else 0
            flood_cnt = 1 if is_rp is False else 0
            cursor.execute("""
                INSERT INTO user_activity (user_id, username, active_char_id, last_active, rp_messages, flood_messages, total_online_seconds)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (user_id, clean_username, active_char_id, now, rp_cnt, flood_cnt))
        else:
            last_active, total_seconds, rp_cnt, flood_cnt, existing_username = row
            added_time = 0
            
            if last_active and (now - last_active <= 600):
                added_time = now - last_active

            new_total_time = (total_seconds or 0) + added_time
            new_rp = (rp_cnt or 0) + (1 if is_rp is True else 0)
            new_flood = (flood_cnt or 0) + (1 if is_rp is False else 0)
            final_username = clean_username if clean_username else existing_username
            
            if active_char_id is not None:
                cursor.execute("""
                    UPDATE user_activity 
                    SET username = ?, active_char_id = ?, last_active = ?, total_online_seconds = ?, rp_messages = ?, flood_messages = ?
                    WHERE user_id = ?
                """, (final_username, active_char_id, now, new_total_time, new_rp, new_flood, user_id))
            else:
                cursor.execute("""
                    UPDATE user_activity 
                    SET username = ?, last_active = ?, total_online_seconds = ?, rp_messages = ?, flood_messages = ?
                    WHERE user_id = ?
                """, (final_username, now, new_total_time, new_rp, new_flood, user_id))

        conn.commit()

def set_offline(user_id: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_activity SET active_char_id = NULL, last_active = 0 WHERE user_id = ?", (user_id,))
        conn.commit()

def delete_character_by_id(char_id: int) -> str:
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, user_id FROM characters WHERE id = ?", (char_id,))
        row = cursor.fetchone()

        if not row:
            return "❌ Персонаж с таким ID не найден!"

        char_name, owner_uid = row
        cursor.execute("DELETE FROM characters WHERE id = ?", (char_id,))
        cursor.execute("DELETE FROM items WHERE char_id = ?", (char_id,))
        cursor.execute("UPDATE user_activity SET active_char_id = NULL WHERE active_char_id = ?", (char_id,))
        conn.commit()

    owner_str = f" (был у игрока {owner_uid})" if owner_uid else " (был свободен)"
    return f"🗑️ Персонаж «{char_name}» #{char_id}{owner_str} был успешно удалён!"

def get_location_info(location_id: str):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, description, image_url, connections FROM locations WHERE id = ?", (location_id,))
        loc = cursor.fetchone()
    return loc

def get_players_at_location(location_id: str, current_char_id: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT c.name, c.role, c.base_moons, c.assigned_at, c.user_id, a.last_active, a.active_char_id, c.id
            FROM characters c
            LEFT JOIN user_activity a ON c.user_id = a.user_id
            WHERE c.current_location_id = ? AND c.id != ? AND c.user_id IS NOT NULL
        """, (location_id, current_char_id))
        
        rows = cursor.fetchall()

    now = int(time.time())
    online_players = []
    sleeping_players = []

    for name, role, base_m, assigned_at, uid, last_active, active_char_id, char_id in rows:
        moons = calculate_moons(base_m, assigned_at)
        is_online = (active_char_id == char_id) and last_active and (now - last_active <= 600)
        
        info = f"  • {name} [{role}] ({moons} лун) [#{char_id}]"
        if is_online:
            online_players.append(info)
        else:
            sleeping_players.append(info)

    return online_players, sleeping_players

async def render_location_message(callback_or_message, char_id: int, location_id: str, is_new_message: bool = False):
    loc = get_location_info(location_id)
    if not loc:
        return

    loc_id, name, description, image_url, connections = loc
    hunger, thirst, toilet = update_needs(char_id)

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, role, base_moons, assigned_at FROM characters WHERE id = ?", (char_id,))
        c_info = cursor.fetchone()
        
        cursor.execute("SELECT id, item_name, item_type FROM items WHERE location_id = ?", (location_id,))
        loc_items = cursor.fetchall()

    char_name = c_info[0] if c_info else "Персонаж"
    char_role = c_info[1] if c_info else "Одиночка"
    char_moons = calculate_moons(c_info[2], c_info[3]) if c_info else 0

    online_p, sleeping_p = get_players_at_location(location_id, char_id)
    game_time = calculate_in_game_time()

    quote_text = f"{description}\n\n"
    
    if loc_items:
        items_str = ", ".join([f"{item[1]} [ID: {item[0]}]" for item in loc_items])
        quote_text += f"🌿 **Лежит на земле:** {items_str}\n\n"

    quote_text += "👥 **Игроки на локации:**\n"

    if online_p:
        quote_text += "🟢 **В сети:**\n" + "\n".join(online_p) + "\n\n"
    else:
        quote_text += "🟢 **В сети:** Никого\n\n"

    if sleeping_p:
        quote_text += "💤 **Спят:**\n" + "\n".join(sleeping_p) + "\n\n"
    else:
        quote_text += "💤 **Спят:** Никого\n\n"

    text = f"📍 {name}\n"
    text += f"⏳ Игровое время: {game_time}\n\n"
    text += f">** {quote_text.strip()} \n\n"
    text += "━━━━━━━━━━━━━━━━━━\n"
    text += f"🎭 Персонаж: {char_name} [{char_role} • {char_moons} лун]\n"
    text += f"🍖 Голод: {int(hunger)}% | 💧 Жажда: {int(thirst)}% | 🚽 Туалет: {int(toilet)}%"

    kb = [
        [InlineKeyboardButton(text="🗺️ Переходы", callback_data=f"transitions_menu:{char_id}:{location_id}")],
        [InlineKeyboardButton(text="⚡ Действия", callback_data=f"actions_menu:{char_id}:{location_id}")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh:{char_id}:{location_id}")]
    ]

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    has_photo = image_url and image_url.strip() != ""

    if is_new_message:
        if isinstance(callback_or_message, types.CallbackQuery):
            try:
                await callback_or_message.message.delete()
            except Exception:
                pass
            if has_photo:
                await callback_or_message.message.answer_photo(photo=image_url, caption=text, reply_markup=markup, parse_mode="Markdown")
            else:
                await callback_or_message.message.answer(text=text, reply_markup=markup, parse_mode="Markdown")
            await callback_or_message.answer()
        else:
            if has_photo:
                await callback_or_message.answer_photo(photo=image_url, caption=text, reply_markup=markup, parse_mode="Markdown")
            else:
                await callback_or_message.answer(text=text, reply_markup=markup, parse_mode="Markdown")
    else:
        if isinstance(callback_or_message, types.CallbackQuery):
            try:
                if has_photo:
                    media = InputMediaPhoto(media=image_url, caption=text, parse_mode="Markdown")
                    await callback_or_message.message.edit_media(media=media, reply_markup=markup)
                else: 
                    await callback_or_message.message.edit_text(text=text, reply_markup=markup, parse_mode="Markdown")
            except Exception as e:
                if "message is not modified" not in str(e):
                    try:
                        if has_photo:
                            await callback_or_message.message.edit_caption(caption=text, reply_markup=markup, parse_mode="Markdown")
                        else:
                            await callback_or_message.message.edit_text(text=text, reply_markup=markup, parse_mode="Markdown")
                    except Exception:
                        pass
            await callback_or_message.answer()

async def broadcast_action_to_location(char_id: int, loc_id: str, action_text: str):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, role, base_moons, assigned_at, photo_url FROM characters WHERE id = ?", (char_id,))
        c_info = cursor.fetchone()

        if not c_info:
            return

        char_name, role, base_m, assigned_at, photo_url = c_info
        moons = calculate_moons(base_m, assigned_at)

        formatted_msg = (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎭 *{char_name}* [{role} • {moons} лун]\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"✨ *{action_text}*"
        )

        now = int(time.time())
        cursor.execute("""
            SELECT DISTINCT c.user_id 
            FROM characters c
            JOIN user_activity a ON c.user_id = a.user_id
            WHERE c.current_location_id = ? 
              AND a.active_char_id = c.id 
              AND (a.last_active >= ? - 600)
        """, (loc_id, now))
        
        receivers = cursor.fetchall()

    # Дублируем действие в логи RP
    loc_info = get_location_info(loc_id)
    loc_title = loc_info[1] if loc_info else loc_id
    await send_to_log("rp", f"📍 **[{loc_title}]**\n{formatted_msg}", photo=photo_url)

    for (receiver_uid,) in receivers:
        try:
            if photo_url:
                await bot.send_photo(chat_id=receiver_uid, photo=photo_url, caption=formatted_msg, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=receiver_uid, text=formatted_msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения игроку {receiver_uid}: {e}")

async def random_item_spawner():
    while True:
        await asyncio.sleep(random.randint(180, 420))
        items_pool = [("Мох", "moss"), ("Листочек", "leaf"), ("Веточка", "stick")]
        chosen_item_name, chosen_item_type = random.choice(items_pool)

        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM locations")
            locs = cursor.fetchall()
            if locs:
                random_loc = random.choice(locs)[0]
                
                cursor.execute("SELECT COUNT(*) FROM items WHERE location_id = ?", (random_loc,))
                item_count = cursor.fetchone()[0]

                if item_count < 10:
                    cursor.execute(
                        "INSERT INTO items (item_name, item_type, location_id) VALUES (?, ?, ?)",
                        (chosen_item_name, chosen_item_type, random_loc)
                    )
                    conn.commit()

# --- ВАЙТЛИСТ И НАСТРОЙКА СПАВНА ---

@dp.message(Command("whitelist"))
async def cmd_whitelist_add(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа к этой команде.")
    
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("⚠️ Использование: `/whitelist [Telegram ID]`", parse_mode="Markdown")
    
    target_id = int(parts[1])
    add_to_whitelist(target_id)
    await message.answer(f"✅ Пользователь `{target_id}` успешно добавлен в белый список!", parse_mode="Markdown")

@dp.message(Command("-whitelist"))
async def cmd_whitelist_remove(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа к этой команде.")

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("⚠️ Использование: `/-whitelist [Telegram ID]`", parse_mode="Markdown")

    target_id = int(parts[1])
    remove_from_whitelist(target_id)
    await message.answer(f"🗑️ Пользователь `{target_id}` удалён из белого списка!", parse_mode="Markdown")

@dp.message(Command("setspawn"))
async def cmd_setspawn(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа к этой команде.")

    parts = message.text.strip().split()
    if len(parts) < 2:
        current_sp = get_default_spawn()
        return await message.answer(f"⚠️ Использование: `/setspawn [id_локации]`\nТекущая точка спавна: `{current_sp}`", parse_mode="Markdown")

    target_loc_id = parts[1].strip()
    loc_info = get_location_info(target_loc_id)
    if not loc_info:
        return await message.answer(f"❌ Локация `{target_loc_id}` не найдена!", parse_mode="Markdown")

    set_default_spawn(target_loc_id)
    await message.answer(f"✅ Точка спавна новых персонажей успешно изменена на **{loc_info[1]}** (`{target_loc_id}`)", parse_mode="Markdown")

# --- МЕНЮ ПЕРЕХОДОВ И ДЕЙСТВИЙ ---

@dp.callback_query(F.data.startswith("transitions_menu:"))
async def cb_transitions_menu(callback: types.CallbackQuery):
    _, char_id, loc_id = callback.data.split(":")
    char_id = int(char_id)

    loc = get_location_info(loc_id)
    if not loc:
        return await callback.answer("❌ Локация не найдена", show_alert=True)

    _, _, _, _, connections = loc
    kb = []
    if connections:
        conn_ids = [c.strip() for c in connections.split(",")]
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            for c_id in conn_ids:
                cursor.execute("SELECT name FROM locations WHERE id = ?", (c_id,))
                target_loc = cursor.fetchone()
                if target_loc:
                    kb.append([InlineKeyboardButton(text=f"🐾 {target_loc[0]}", callback_data=f"move:{char_id}:{c_id}")])

    kb.append([InlineKeyboardButton(text="⬅️ Назад к локации", callback_data=f"refresh:{char_id}:{loc_id}")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "🐾 **Выберите тропу для перехода:**"

    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=markup, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("actions_menu:"))
async def cb_actions_menu(callback: types.CallbackQuery):
    _, char_id, loc_id = callback.data.split(":")
    char_id = int(char_id)

    kb = []
    kb.append([InlineKeyboardButton(text="🚽 Сходить в туалет", callback_data=f"do_act:toilet:{char_id}:{loc_id}")])

    if loc_id in ["rechka_24", "cum_bereg_8"]:
        kb.append([InlineKeyboardButton(text="💧 Попить водички", callback_data=f"do_act:drink:{char_id}:{loc_id}")])
        kb.append([InlineKeyboardButton(text="🎣 Ловить рыбу", callback_data=f"do_act:fish:{char_id}:{loc_id}")])

        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM items WHERE char_id = ? AND item_name = 'Мох' LIMIT 1", (char_id,))
            moss_item = cursor.fetchone()
            if moss_item:
                kb.append([InlineKeyboardButton(text="💧 Намочить мох", callback_data=f"do_act:wet_moss:{char_id}:{loc_id}:{moss_item[0]}")])

    kb.append([InlineKeyboardButton(text="⬅️ Назад к локации", callback_data=f"refresh:{char_id}:{loc_id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "⚡ **Выберите доступное действие:**"

    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=markup, parse_mode="Markdown")
        
    await callback.answer()

@dp.callback_query(F.data.startswith("do_act:"))
async def cb_do_action(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    action_type = parts[1]
    char_id = int(parts[2])
    loc_id = parts[3]
    user_id = callback.from_user.id

    update_activity(user_id, username=callback.from_user.username, active_char_id=char_id)

    if action_type == "drink":
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE characters SET thirst = 100.0 WHERE id = ?", (char_id,))
            conn.commit()
        await callback.answer("💧 Вы напились свежей воды!", show_alert=True)
        await broadcast_action_to_location(char_id, loc_id, "с удовольствием пьет чистую речную воду.")

    elif action_type == "toilet":
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE characters SET toilet = 100.0 WHERE id = ?", (char_id,))
            conn.commit()
        await callback.answer("🚽 Вы облегчились!", show_alert=True)
        await broadcast_action_to_location(char_id, loc_id, "отходит в кустики и с облегчением возвращается.")

    elif action_type == "wet_moss":
        moss_id = int(parts[4])
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE items SET item_name = 'Намоченный мох', item_type = 'wet_moss' WHERE id = ? AND char_id = ?", (moss_id, char_id))
            conn.commit()
        await callback.answer("💧 Вы обильно намочили мох в реке!", show_alert=True)
        await broadcast_action_to_location(char_id, loc_id, "опускает сухой мох в воду, давая ему тщательно пропитаться.")

    elif action_type == "fish":
        now = time.time()
        if char_id in fishing_cooldowns and now < fishing_cooldowns[char_id]:
            left = int(fishing_cooldowns[char_id] - now)
            return await callback.answer(f"⏳ Вы устали! Отдохните еще {left} сек. перед рыбалкой.", show_alert=True)

        fishing_cooldowns[char_id] = now + 45.0

        await callback.answer("🎣 Вы закинули лапы в воду и замерли в ожидании...", show_alert=True)
        await broadcast_action_to_location(char_id, loc_id, "напряженно вглядывается в речную гладь, выжидая рыбу.")
        asyncio.create_task(async_fishing_process(user_id, callback.from_user.username, char_id, loc_id, callback.message))

    await render_location_message(callback_or_message=callback, char_id=char_id, location_id=loc_id, is_new_message=False)

async def async_fishing_process(user_id: int, username: str, char_id: int, loc_id: str, message: types.Message):
    await asyncio.sleep(15)

    success = random.choice([True, False])

    if success:
        fish_list = ["Плотва", "Окунь", "Щука", "Красная форель", "Речной карась"]
        caught_fish = random.choice(fish_list)

        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM items WHERE char_id = ?", (char_id,))
            inv_count = cursor.fetchone()[0]

            if inv_count >= 5:
                cursor.execute("INSERT INTO items (item_name, item_type, location_id) VALUES (?, ?, ?)", (caught_fish, "fish", loc_id))
                conn.commit()
                full_inventory = True
            else:
                cursor.execute("INSERT INTO items (item_name, item_type, char_id) VALUES (?, ?, ?)", (caught_fish, "fish", char_id))
                conn.commit()
                full_inventory = False

        if full_inventory:
            await message.answer(f"🎉 Вы поймали **{caught_fish}**, но в вашей пасти и лапах нет места! Добыча упала на землю.")
            await broadcast_action_to_location(char_id, loc_id, f"вытаскивает из воды рыбу ({caught_fish}), но та падает на землю из-за переполненного рта!")
        else:
            await message.answer(f"🎉 Удача! Вы поймали рыбу: **{caught_fish}** и взяли её в зубы!")
            await broadcast_action_to_location(char_id, loc_id, f"победно вытаскивает из воды рыбу ({caught_fish}) и зажимает её в зубах!")
    else:
        await message.answer("💨 Рыба сорвалась, а коготочек остался пустым...")
        await broadcast_action_to_location(char_id, loc_id, "разочарованно вздыхает — рыба сорвалась.")

    update_activity(user_id, username=username, active_char_id=char_id)

# --- ИСПОЛЬЗОВАНИЕ И КРАФТ ПРЕДМЕТОВ ---

@dp.message(Command("исп", "использовать"))
async def cmd_use_item(message: types.Message):
    user_id = message.from_user.id
    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.answer("⚠️ Использование:\n`/исп [IDпредмета]` или крафт: `/исп id1+id2+id3`", parse_mode="Markdown")

    args = parts[1]

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active_char_id FROM user_activity WHERE user_id = ?", (user_id,))
        act_row = cursor.fetchone()
        if not act_row or not act_row[0]:
            return await message.answer("⚠️ Выберите персонажа через /repers!")
        char_id = act_row[0]

        cursor.execute("SELECT current_location_id FROM characters WHERE id = ?", (char_id,))
        char_loc_row = cursor.fetchone()
        loc_id = char_loc_row[0]

    if "+" in args:
        raw_ids = args.split("+")
        if not all(i.isdigit() for i in raw_ids):
            return await message.answer("⚠️ Укажите правильные числовые ID через плюс! Пример: `/исп 1+2+3`", parse_mode="Markdown")
        
        item_ids = [int(i) for i in raw_ids]

        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in item_ids)
            cursor.execute(f"SELECT id, item_name, item_type FROM items WHERE id IN ({placeholders}) AND (char_id = ? OR location_id = ?)", item_ids + [char_id, loc_id])
            found_items = cursor.fetchall()

            if len(found_items) != len(item_ids):
                return await message.answer("❌ Часть предметов не найдена в вашем инвентаре или на текущей локации!")

            names = [it[1].lower() for it in found_items]
            types = [it[2].lower() for it in found_items]

            sticks_cnt = sum(1 for t in types if t in ['stick', 'веточка', 'палка']) or sum(1 for n in names if 'веточка' in n or 'палка' in n)
            leaves_cnt = sum(1 for t in types if t in ['leaf', 'листочек', 'лист']) or sum(1 for n in names if 'листочек' in n or 'лист' in n)

            if sticks_cnt >= 1 and leaves_cnt >= 2:
                cursor.execute(f"DELETE FROM items WHERE id IN ({placeholders})", item_ids)
                
                crafted_name = "Самолётик"
                cursor.execute("SELECT COUNT(*) FROM items WHERE char_id = ?", (char_id,))
                inv_c = cursor.fetchone()[0]

                if inv_c < 5:
                    cursor.execute("INSERT INTO items (item_name, item_type, char_id) VALUES (?, 'crafted', ?)", (crafted_name, char_id))
                    msg_target = "помещено в ваш инвентарь!"
                else:
                    cursor.execute("INSERT INTO items (item_name, item_type, location_id) VALUES (?, 'crafted', ?)", (crafted_name, loc_id))
                    msg_target = "упало на землю (инвентарь полон)."

                conn.commit()

            else:
                return await message.answer("❌ Из этих ингредиентов ничего нельзя скрафтить!\nПодсказка: нужен 1 лист/веточка и 2 листика.")

        await message.answer(f"🛠️ **Вы успешно скрафтили «{crafted_name}»!** ({msg_target})", parse_mode="Markdown")
        await broadcast_action_to_location(char_id, loc_id, f"мастерит из веточек и листьев новое полезное изделие ({crafted_name}).")
        return

    if not args.isdigit():
        return await message.answer("⚠️ Укажите корректный числовой ID предмета.")

    item_id = int(args)

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT item_name, item_type FROM items WHERE id = ? AND char_id = ?", (item_id, char_id))
        item_row = cursor.fetchone()

        if not item_row:
            return await message.answer("❌ Предмет с таким ID не найден у вас в инвентаре!")

        item_name, item_type = item_row

        if item_type == "wet_moss" or "Намоченный мох" in item_name:
            cursor.execute("UPDATE characters SET thirst = 100.0 WHERE id = ?", (char_id,))
            cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
            conn.commit()
            await message.answer("💧 Вы выжали намокший мох в пасть и полностью утолили жажду!")
            await broadcast_action_to_location(char_id, loc_id, "с удовольствием выжимает сочный мох себе в пасть.")
        else:
            await message.answer(f"ℹ️ Вы посмотрели на **{item_name}**, но пока не придумали, как его применить в одиночку.")

# --- ИНВЕНТАРЬ ---

@dp.message(Command("inv"))
async def cmd_inv(message: types.Message):
    user_id = message.from_user.id
    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active_char_id FROM user_activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if not row or not row[0]:
            return await message.answer("⚠️ Сначала выберите персонажа через /repers!")

        char_id = row[0]
        cursor.execute("SELECT id, item_name, item_type FROM items WHERE char_id = ?", (char_id,))
        items = cursor.fetchall()

    text = "🎒 **Ваш инвентарь (до 5 штук):**\n\n"
    if items:
        for idx, (item_id, name, itype) in enumerate(items, 1):
            text += f"{idx}. 🌿 {name} [ID: `{item_id}`]\n"
    else:
        text += "Пусто... Ваши зубы и лапы свободны."

    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("поднять"))
async def cmd_take_item(message: types.Message):
    user_id = message.from_user.id
    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("⚠️ Использование: `/поднять [idпредмета]`", parse_mode="Markdown")

    item_id = int(parts[1])

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active_char_id FROM user_activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if not row or not row[0]:
            return await message.answer("⚠️ Выберите персонажа через /repers!")

        char_id = row[0]
        cursor.execute("SELECT current_location_id FROM characters WHERE id = ?", (char_id,))
        char_loc_row = cursor.fetchone()
        if not char_loc_row:
            return await message.answer("⚠️ Ошибка персонажа.")

        loc_id = char_loc_row[0]

        cursor.execute("SELECT id, item_name, item_type FROM items WHERE id = ? AND location_id = ?", (item_id, loc_id))
        item_row = cursor.fetchone()

        if not item_row:
            return await message.answer("❌ Такого предмета нет на вашей локации!")

        _, item_name, item_type = item_row

        cursor.execute("SELECT COUNT(*) FROM items WHERE char_id = ?", (char_id,))
        inv_count = cursor.fetchone()[0]

        if inv_count >= 5:
            return await message.answer("❌ Ваш инвентарь полон! (Максимум 5 предметов). Положите что-нибудь на землю.")

        cursor.execute("UPDATE items SET location_id = NULL, char_id = ? WHERE id = ?", (char_id, item_id))
        conn.commit()

    update_activity(user_id, username=message.from_user.username, active_char_id=char_id)
    await message.answer(f"✅ Вы подняли **{item_name}** и зажали его в зубах.")
    await broadcast_action_to_location(char_id, loc_id, f"подбирает с земли {item_name} и крепко зажимает в зубах.")

@dp.message(Command("положить"))
async def cmd_drop_item(message: types.Message):
    user_id = message.from_user.id
    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("⚠️ Использование: `/положить [idпредмета]`", parse_mode="Markdown")

    item_id = int(parts[1])

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active_char_id FROM user_activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if not row or not row[0]:
            return await message.answer("⚠️ Выберите персонажа через /repers!")

        char_id = row[0]
        cursor.execute("SELECT current_location_id FROM characters WHERE id = ?", (char_id,))
        char_loc_row = cursor.fetchone()
        if not char_loc_row:
            return await message.answer("⚠️ Ошибка персонажа.")

        loc_id = char_loc_row[0]

        cursor.execute("SELECT id, item_name, item_type FROM items WHERE id = ? AND char_id = ?", (item_id, char_id))
        item_row = cursor.fetchone()

        if not item_row:
            return await message.answer("❌ У вас в инвентаре нет предмета с таким ID!")

        _, item_name, item_type = item_row

        cursor.execute("UPDATE items SET char_id = NULL, location_id = ? WHERE id = ?", (loc_id, item_id))
        conn.commit()

    update_activity(user_id, username=message.from_user.username, active_char_id=char_id)
    await message.answer(f"✅ Вы положили **{item_name}** на землю локации.")
    await broadcast_action_to_location(char_id, loc_id, f"аккуратно кладет на землю {item_name}.")

# --- КАРТОЧКИ И ПРОФИЛИ ---

async def send_user_profile_card(event, target_uid: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT rp_messages, flood_messages, total_online_seconds, active_char_id FROM user_activity WHERE user_id = ?", (target_uid,))
        act = cursor.fetchone()
        
        rp_cnt = act[0] if act and act[0] else 0
        flood_cnt = act[1] if act and act[1] else 0
        total_sec = act[2] if act and act[2] else 0
        active_char_id = act[3] if act else None

        char_photo = None
        if active_char_id:
            cursor.execute("SELECT photo_url FROM characters WHERE id = ?", (active_char_id,))
            cp_row = cursor.fetchone()
            if cp_row:
                char_photo = cp_row[0]

    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60

    text = f"👤 **Профиль игрока** (`{target_uid}`)\n\n"
    text += f"📊 **Статистика:**\n"
    text += f" 🎭 Ролевых сообщений (!!): **{rp_cnt}**\n"
    text += f" 💬 Флуд сообщений (!): **{flood_cnt}**\n"
    text += f" ⏱️ Общий онлайн: **{hours} ч. {minutes} мин.**\n"

    kb_rows = []
    kb_rows.append([InlineKeyboardButton(text="📜 Персонажи", callback_data=f"user_ankety:{target_uid}")])
    if event.from_user.id == target_uid:
        kb_rows.append([InlineKeyboardButton(text="➕ Создать персонажа", callback_data="user_create_char")])
        kb_rows.append([InlineKeyboardButton(text="🖼️ Добавить аватарку профиля", callback_data="set_avatar")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if char_photo:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer_photo(photo=char_photo, caption=text, reply_markup=kb, parse_mode="Markdown")
            await event.answer()
        else:
            await event.answer_photo(photo=char_photo, caption=text, reply_markup=kb, parse_mode="Markdown")
    else:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await event.message.answer(text, reply_markup=kb, parse_mode="Markdown")
            await event.answer()
        else:
            await event.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- СОЗДАНИЕ ПЕРСОНАЖА ИГРОКАМИ (СПАВН ФИКСИРОВАН) ---

@dp.callback_query(F.data == "user_create_char")
async def user_create_char_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_for_user_char_name)
    await callback.message.answer("✏️ Введите имя вашего будущего персонажа:")
    await callback.answer()

@dp.message(UserStates.waiting_for_user_char_name)
async def user_create_char_name(message: types.Message, state: FSMContext):
    await state.update_data(char_name=message.text.strip())
    await state.set_state(UserStates.waiting_for_user_char_role)
    await message.answer("💼 Введите должность персонажа (напр., Котёнок, Оруженосец, Воитель):")

@dp.message(UserStates.waiting_for_user_char_role)
async def user_create_char_role(message: types.Message, state: FSMContext):
    await state.update_data(char_role=message.text.strip())
    await state.set_state(UserStates.waiting_for_user_char_moons)
    await message.answer("🌙 Введите начальный возраст персонажа в лунах (число):")

@dp.message(UserStates.waiting_for_user_char_moons)
async def user_create_char_moons(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Введите корректное число!")
    await state.update_data(char_moons=int(message.text.strip()))
    await state.set_state(UserStates.waiting_for_user_char_photo)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить фото", callback_data="skip_user_char_photo")]
    ])
    await message.answer("🖼️ Отправьте аватарку/фото персонажа (или нажмите кнопку пропустить):", reply_markup=kb)

@dp.message(UserStates.waiting_for_user_char_photo, F.photo)
async def user_create_char_photo_msg(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    user_id = message.from_user.id
    now = int(time.time())
    spawn_loc = get_default_spawn()

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO characters (name, role, base_moons, photo_url, user_id, current_location_id, assigned_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data["char_name"], data["char_role"], data["char_moons"], photo_id, user_id, spawn_loc, now, now)
        )
        char_id = cursor.lastrowid
        conn.commit()

    update_activity(user_id, username=message.from_user.username, active_char_id=char_id)
    await state.clear()
    await message.answer(f"🎉 Вы успешно создали персонажа **{data['char_name']}**! Он появился на локации спавна.")

@dp.callback_query(UserStates.waiting_for_user_char_photo, F.data == "skip_user_char_photo")
async def user_create_char_photo_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    now = int(time.time())
    spawn_loc = get_default_spawn()

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO characters (name, role, base_moons, user_id, current_location_id, assigned_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data["char_name"], data["char_role"], data["char_moons"], user_id, spawn_loc, now, now)
        )
        char_id = cursor.lastrowid
        conn.commit()

    update_activity(user_id, username=callback.from_user.username, active_char_id=char_id)
    await state.clear()
    await callback.message.answer(f"🎉 Вы успешно создали персонажа **{data['char_name']}**! Он появился на локации спавна.")
    await callback.answer()

# --- АДМИН ПАНЕЛЬ И УПРАВЛЕНИЕ ---

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа к командам администратора.")

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать персонажа", callback_data="admin_create_char")],
        [InlineKeyboardButton(text="🔗 Привязать персонажа", callback_data="admin_assign_char")],
        [InlineKeyboardButton(text="⚡ Управление персонажами", callback_data="admin_manage_chars")],
        [InlineKeyboardButton(text="🛡️ Управление вайтлистом", callback_data="admin_manage_wl")],
        [InlineKeyboardButton(text="⚡ Телепортировать", callback_data="admin_tp_char")]
    ])
    await message.answer("👑 Панель Администратора:", reply_markup=kb)

# --- ТЕЛЕПОРТ ---

@dp.callback_query(F.data == "admin_tp_char")
async def cb_admin_tp_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminStates.waiting_for_tp_char_id)
    await callback.message.answer("⚡ Введите ID персонажа, которого хотите телепортировать:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_tp_char_id)
async def process_tp_char_id(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("⚠️ Введите числовой ID персонажа!")
    
    char_id = int(message.text.strip())
    
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, current_location_id FROM characters WHERE id = ?", (char_id,))
        char_row = cursor.fetchone()

    if not char_row:
        return await message.answer("❌ Персонаж с таким ID не найден!")

    await state.update_data(tp_char_id=char_id, tp_char_name=char_row[0])
    await state.set_state(AdminStates.waiting_for_tp_loc_id)
    await message.answer(f"📍 Персонаж: **{char_row[0]}** [#{char_id}]\nТекущая локация: `{char_row[1]}`\n\nВведите ID локации назначения (например, `camp_1` или `rechka_24`):", parse_mode="Markdown")

@dp.message(AdminStates.waiting_for_tp_loc_id)
async def process_tp_loc_id(message: types.Message, state: FSMContext):
    target_loc_id = message.text.strip()
    loc_info = get_location_info(target_loc_id)

    if not loc_info:
        return await message.answer(f"❌ Локация с ID `{target_loc_id}` не найдена! Проверьте написание.", parse_mode="Markdown")

    data = await state.get_data()
    char_id = data.get("tp_char_id")
    char_name = data.get("tp_char_name", "Персонаж")

    if not char_id:
        await state.clear()
        return await message.answer("⚠️ Ошибка состояния! Попробуйте с начального меню /admin.")

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE characters SET current_location_id = ? WHERE id = ?", (target_loc_id, char_id))
        cursor.execute("SELECT user_id FROM characters WHERE id = ?", (char_id,))
        owner_row = cursor.fetchone()
        conn.commit()

    owner_uid = owner_row[0] if owner_row else None

    await message.answer(f"✨ Персонаж **{char_name}** [#{char_id}] успешно телепортирован на локацию **{loc_info[1]}** (`{target_loc_id}`)!", parse_mode="Markdown")
    await send_to_log("rp", f"⚡ **[АДМИН-ТЕЛЕПОРТ]** Персонаж **{char_name}** [#{char_id}] перемещён на локацию **{loc_info[1]}** (`{target_loc_id}`).")
    await state.clear()

    if owner_uid:
        try:
            await bot.send_message(chat_id=owner_uid, text=f"⚡ Вы были телепортированы на локацию **{loc_info[1]}**!", parse_mode="Markdown")
            await render_location_message(callback_or_message=types.Message(chat=types.Chat(id=owner_uid, type="private"), bot=bot), char_id=char_id, location_id=target_loc_id, is_new_message=True)
        except Exception as e:
            logging.error(f"Ошибка отправки сообщения после ТП пользователю {owner_uid}: {e}")

@dp.callback_query(F.data == "admin_manage_wl")
async def cb_admin_manage_wl(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в вайтлист", callback_data="wl_add_btn")],
        [InlineKeyboardButton(text="➖ Удалить из вайтлиста", callback_data="wl_remove_btn")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text("🛡️ **Управление вайтлистом проекта:**", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def cb_admin_back(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать персонажа", callback_data="admin_create_char")],
        [InlineKeyboardButton(text="🔗 Привязать персонажа", callback_data="admin_assign_char")],
        [InlineKeyboardButton(text="⚡ Управление персонажами", callback_data="admin_manage_chars")],
        [InlineKeyboardButton(text="🛡️ Управление вайтлистом", callback_data="admin_manage_wl")],
        [InlineKeyboardButton(text="⚡ Телепортировать", callback_data="admin_tp_char")]
    ])
    await callback.message.edit_text("👑 Панель Администратора:", reply_markup=kb)

@dp.callback_query(F.data == "wl_add_btn")
async def cb_wl_add_btn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_wl_add)
    await callback.message.answer("✏️ Введите Telegram ID пользователя для добавления в вайтлист:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_wl_add)
async def process_wl_add_msg(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Введите числовой Telegram ID!")
    uid = int(message.text.strip())
    add_to_whitelist(uid)
    await state.clear()
    await message.answer(f"✅ Пользователь с ID `{uid}` добавлен в Вайтлист!", parse_mode="Markdown")

@dp.callback_query(F.data == "wl_remove_btn")
async def cb_wl_remove_btn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_wl_remove)
    await callback.message.answer("✏️ Введите Telegram ID пользователя для удаления из вайтлиста:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_wl_remove)
async def process_wl_remove_msg(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Введите числовой Telegram ID!")
    uid = int(message.text.strip())
    remove_from_whitelist(uid)
    await state.clear()
    await message.answer(f"🗑️ Пользователь с ID `{uid}` удален из Вайтлиста!", parse_mode="Markdown")

# --- УПРАВЛЕНИЕ ПЕРСОНАЖАМИ АДМИНАМИ ---

@dp.callback_query(F.data == "admin_manage_chars")
async def cb_admin_manage_chars(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT c.id, c.name, c.user_id, u.username FROM characters c LEFT JOIN user_activity u ON c.user_id = u.user_id")
        chars = cursor.fetchall()

    if not chars:
        await callback.answer("В базе нет персонажей!", show_alert=True)
        return

    kb = []
    for cid, cname, uid, uname in chars:
        owner_name = f"@{uname}" if uname else f"ID:{uid}" if uid else "Нет владельца"
        btn_text = f"{cname} (Владелец: {owner_name})"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"adm_view_c:{cid}")])

    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await callback.message.edit_text("⚙️ **Управление персонажами:**\nВыберите персонажа из списка ниже:", reply_markup=markup, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_view_c:"))
async def cb_adm_view_c(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    char_id = int(callback.data.split(":")[1])
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role, base_moons, assigned_at, user_id, created_at FROM characters WHERE id = ?", (char_id,))
        c = cursor.fetchone()

        if not c:
            return await callback.answer("Персонаж не найден!", show_alert=True)

        cursor.execute("SELECT item_name, id FROM items WHERE char_id = ?", (char_id,))
        items = cursor.fetchall()

    cid, name, role, base_m, assigned_at, uid, created_at = c
    moons = calculate_moons(base_m, assigned_at)
    
    created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at)) if created_at else "Неизвестно"
    inv_str = ", ".join([f"{it[0]} [id{it[1]}]" for it in items]) if items else "Пусто"

    text = f"🎭 **Информация о персонаже #{cid}**\n\n"
    text += f"📛 **Имя:** {name}\n"
    text += f"💼 **Должность:** {role}\n"
    text += f"🌙 **Возраст:** {moons} лун (базово: {base_m})\n"
    text += f"📅 **Дата создания:** {created_str}\n"
    text += f"🎒 **Инвентарь:** {inv_str}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить Имя", callback_data=f"adm_ed:{cid}:name"), InlineKeyboardButton(text="💼 Изменить Должность", callback_data=f"adm_ed:{cid}:role")],
        [InlineKeyboardButton(text="🌙 Изменить Луны", callback_data=f"adm_ed:{cid}:base_moons")],
        [InlineKeyboardButton(text="🎁 Выдать предмет", callback_data=f"adm_give_it:{cid}"), InlineKeyboardButton(text="❌ Забрать предмет", callback_data=f"adm_take_it:{cid}")],
        [InlineKeyboardButton(text="🗑️ Удалить персонажа", callback_data=f"confirm_delete:{cid}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="admin_manage_chars")]
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_ed:"))
async def cb_adm_edit_prompt(callback: types.CallbackQuery, state: FSMContext):
    _, cid, field = callback.data.split(":")
    await state.update_data(edit_char_id=int(cid), edit_field=field)
    await state.set_state(AdminStates.waiting_for_edit_field_val)
    await callback.message.answer(f"✏️ Введите новое значение для поля **{field}** персонажа #{cid}:", parse_mode="Markdown")
    await callback.answer()

@dp.message(AdminStates.waiting_for_edit_field_val)
async def process_adm_edit_val(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cid = data["edit_char_id"]
    field = data["edit_field"]
    val = message.text.strip()

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        if field == "base_moons":
            if not val.isdigit():
                return await message.answer("⚠️ Значение должно быть числом!")
            cursor.execute("UPDATE characters SET base_moons = ? WHERE id = ?", (int(val), cid))
        else:
            cursor.execute(f"UPDATE characters SET {field} = ? WHERE id = ?", (val, cid))
        conn.commit()

    await state.clear()
    await message.answer(f"✅ Поле **{field}** персонажа #{cid} успешно изменено!", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("adm_give_it:"))
async def cb_adm_give_it(callback: types.CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await state.update_data(target_cid=cid)
    await state.set_state(AdminStates.waiting_for_give_item_name)
    await callback.message.answer("🎁 Введите название предмета для выдачи:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_give_item_name)
async def process_adm_give_it_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cid = data["target_cid"]
    item_name = message.text.strip()

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO items (item_name, item_type, char_id) VALUES (?, 'given', ?)", (item_name, cid))
        conn.commit()

    await state.clear()
    await message.answer(f"✅ Предмет **{item_name}** выдан персонажу #{cid}!", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("adm_take_it:"))
async def cb_adm_take_it(callback: types.CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await state.update_data(target_cid=cid)
    await state.set_state(AdminStates.waiting_for_take_item_id)
    await callback.message.answer("❌ Введите ID предмета, который нужно забрать из инвентаря:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_take_item_id)
async def process_adm_take_it_msg(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Введите числовой ID предмета!")

    item_id = int(message.text.strip())
    data = await state.get_data()
    cid = data["target_cid"]

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items WHERE id = ? AND char_id = ?", (item_id, cid))
        conn.commit()

    await state.clear()
    await message.answer(f"✅ Предмет #{item_id} изъят у персонажа #{cid}!", parse_mode="Markdown")

# --- СМЕНА АВАТАРКИ И КАРТОЧКА ПЕРСОНАЖА ---

@dp.callback_query(F.data == "set_avatar")
async def cb_set_avatar(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active_char_id FROM user_activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

    if not row or not row[0]:
        await callback.answer("⚠️ Выберите активного персонажа через /repers!", show_alert=True)
        return

    await state.set_state(UserStates.waiting_for_avatar)
    await state.update_data(active_char_id=row[0])
    await callback.message.answer("🖼️ **Отправьте изображение, которое станет аватаркой вашего текущего персонажа:**")
    await callback.answer()

@dp.message(UserStates.waiting_for_avatar, F.photo)
async def process_user_avatar(message: types.Message, state: FSMContext):
    data = await state.get_data()
    char_id = data["active_char_id"]
    photo_id = message.photo[-1].file_id

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE characters SET photo_url = ? WHERE id = ?", (photo_id, char_id))
        conn.commit()

    await state.clear()
    await message.answer("✅ **Аватарка персонажа успешно обновлена!**")

async def send_character_card(event, char_id: int):
    is_message = isinstance(event, types.Message)

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role, base_moons, assigned_at, user_id, current_location_id, photo_url FROM characters WHERE id = ?", (char_id,))
        row = cursor.fetchone()
        
        if not row:
            msg = "❌ Персонаж не найден."
            return await event.answer(msg) if is_message else await event.message.answer(msg)

        cid, name, role, base_m, assigned_at, owner_id, loc_id, photo_url = row
        
        cursor.execute("SELECT name FROM locations WHERE id = ?", (loc_id,))
        loc_row = cursor.fetchone()
        loc_name = loc_row[0] if loc_row else loc_id
        
        cursor.execute("SELECT item_name, id FROM items WHERE char_id = ? ORDER BY id DESC LIMIT 1", (char_id,))
        last_item_row = cursor.fetchone()

    moons = calculate_moons(base_m, assigned_at)
    owner_str = f"`{owner_id}`" if owner_id else "Свободен"
    
    if last_item_row:
        teeth_str = f"{last_item_row[0]} id{last_item_row[1]}"
    else:
        teeth_str = "пусто"

    caption = f"🎭 **Профиль персонажа** #{cid}\n\n"
    caption += f"📛 **Имя:** {name}\n"
    caption += f"💼 **Должность:** {role}\n"
    caption += f"🌙 **Возраст:** {moons} лун\n"
    caption += f"📍 **Локация:** {loc_name}\n"
    caption += f"🦷 **В зубах:** {teeth_str}\n"
    caption += f"👤 **Владелец:** {owner_str}"

    if photo_url:
        if is_message:
            await event.answer_photo(photo=photo_url, caption=caption, parse_mode="Markdown")
        else:
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer_photo(photo=photo_url, caption=caption, parse_mode="Markdown")
            await event.answer()
    else:
        if is_message:
            await event.answer(caption, parse_mode="Markdown")
        else:
            try:
                await event.message.edit_text(caption, parse_mode="Markdown")
            except Exception:
                await event.message.answer(caption, parse_mode="Markdown")
            await event.answer()

# --- ИГРОВЫЕ И ПОЛЬЗОВАТЕЛЬСКИЕ КОМАНДЫ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    update_activity(user_id, username=message.from_user.username)

    has_access = user_has_access(user_id)

    text = "🌲 **Добро пожаловать в Текстовую RolePlay Игру!**\n\n"
    text += "Здесь вы можете погрузиться в мир ролевых приключений, отыгрывать своих персонажей и исследовать локации.\n\n"

    if has_access:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM characters WHERE user_id = ?", (user_id,))
            has_chars = cursor.fetchone() is not None

        if has_chars:
            text += "✅ **У вас есть доступ к проекту!** Нажмите ниже для выбора персонажа:"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎭 Выбор персонажа", callback_data="select_char")]
            ])
        else:
            text += "✅ **У вас есть доступ к проекту!** У вас пока нет персонажей. Создайте своего первого персонажа:"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Создать персонажа", callback_data="user_create_char")]
            ])
            
        await message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        text += "⛔ **У вас пока нет доступа к проекту.**\nОбратитесь к администратору!"
        await message.answer(text, parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "❓ **Справка по доступным командам:**\n\n"
        "🔄 `/update` — Обновить локацию\n"
        "👥 `/repers` — Выбрать/сменить персонажа\n"
        "🎒 `/inv` — Посмотреть инвентарь\n"
        "📥 `/поднять id` — Поднять предмет\n"
        "📤 `/положить id` — Положить предмет\n"
        "🧪 `/исп id` — Использовать предмет / крафт (`/исп id1+id2+id3`)\n"
        "📊 `/my_profile` — Посмотреть свой профиль\n"
        "🔍 `/profile` [ID / @username] — Чужой профиль\n"
        "🚩 `/setspawn [id_локации]` — Установить спавн новичков (Админ)\n"
        "📢 `+logs` / `+флудлог` / `+рплог` — Настройка чата и тем для логов (Админ)\n"
        "❓ `/help` — Справка"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("update"))
async def cmd_update(message: types.Message):
    user_id = message.from_user.id
    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT active_char_id FROM user_activity WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        
        if not row or not row[0]:
            return await message.answer("⚠️ Сначала выберите персонажа с помощью команды /repers")

        active_char_id = row[0]
        cursor.execute("SELECT current_location_id FROM characters WHERE id = ?", (active_char_id,))
        char_row = cursor.fetchone()

    if not char_row:
        return await message.answer("⚠️ Ошибка персонажа.")

    try:
        await message.delete()
    except Exception:
        pass

    update_activity(user_id, username=message.from_user.username, active_char_id=active_char_id)
    await render_location_message(callback_or_message=message, char_id=active_char_id, location_id=char_row[0], is_new_message=True)

@dp.message(Command("repers"))
async def cmd_repers(message: types.Message):
    if not user_has_access(message.from_user.id):
        return await message.answer("⛔ У вас нет доступа к проекту.")
    await show_character_selection(message)

@dp.message(Command("my_profile"))
async def cmd_my_profile(message: types.Message):
    user_id = message.from_user.id
    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")
    
    update_activity(user_id, username=message.from_user.username)
    await send_user_profile_card(message, user_id)

@dp.callback_query(F.data.startswith("user_ankety:"))
async def cb_user_ankety(callback: types.CallbackQuery):
    target_uid = int(callback.data.split(":")[1])
    
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role FROM characters WHERE user_id = ?", (target_uid,))
        chars = cursor.fetchall()

    if not chars:
        await callback.answer("У этого пользователя нет привязанных персонажей.", show_alert=True)
        return

    kb = []
    for cid, name, role in chars:
        kb.append([InlineKeyboardButton(text=f"🎭 {name} [{role}] (ID: #{cid})", callback_data=f"view_char:{cid}")])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    try:
        await callback.message.edit_text("📜 **Список персонажей:**", reply_markup=markup, parse_mode="Markdown")
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer("📜 **Список персонажей:**", reply_markup=markup, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("view_char:"))
async def cb_view_char(callback: types.CallbackQuery):
    char_id = int(callback.data.split(":")[1])
    await send_character_card(callback, char_id)

@dp.message(Command("profile", "профиль"))
async def cmd_profile(message: types.Message):
    if not user_has_access(message.from_user.id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.answer("⚠️ Использование: `/profile [ID персонажа / ID игрока / @username]`", parse_mode="Markdown")

    target_raw = parts[1]

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()

        if target_raw.startswith("@"):
            clean_uname = target_raw.lstrip("@").lower()
            cursor.execute("SELECT user_id FROM user_activity WHERE username = ?", (clean_uname,))
            user_row = cursor.fetchone()

            if user_row:
                return await send_user_profile_card(message, user_row[0])
            else:
                return await message.answer(f"❌ Игрок с username `{target_raw}` не найден.", parse_mode="Markdown")

        if target_raw.isdigit():
            target_id = int(target_raw)

            cursor.execute("SELECT id FROM characters WHERE id = ?", (target_id,))
            char_row = cursor.fetchone()

            if char_row:
                return await send_character_card(message, target_id)

            cursor.execute("SELECT user_id FROM user_activity WHERE user_id = ?", (target_id,))
            user_act = cursor.fetchone()

            if user_act:
                return await send_user_profile_card(message, target_id)

    await message.answer(f"❌ Ничего не найдено по запросу `{target_raw}`.", parse_mode="Markdown")

# --- ДОПОЛНИТЕЛЬНЫЕ АДМИН-ФУНКЦИИ И ОПЕРАЦИИ С СОЗДАНИЕМ ---

@dp.callback_query(F.data == "admin_create_char")
async def admin_create_char_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_char_name)
    await callback.message.answer("✏️ Введите имя нового персонажа:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_char_name)
async def admin_create_char_name(message: types.Message, state: FSMContext):
    await state.update_data(char_name=message.text.strip())
    await state.set_state(AdminStates.waiting_for_char_role)
    await message.answer("💼 Введите должность персонажа:")

@dp.message(AdminStates.waiting_for_char_role)
async def admin_create_char_role(message: types.Message, state: FSMContext):
    await state.update_data(char_role=message.text.strip())
    await state.set_state(AdminStates.waiting_for_char_moons)
    await message.answer("🌙 Введите начальный возраст персонажа в лунах (число):")

@dp.message(AdminStates.waiting_for_char_moons)
async def admin_create_char_moons(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Пожалуйста, введите число:")

    await state.update_data(char_moons=int(message.text.strip()))
    await state.set_state(AdminStates.waiting_for_char_photo)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить фото", callback_data="skip_char_photo")]
    ])
    await message.answer("🖼️ Отправьте фото персонажа (или нажмите кнопку ниже):", reply_markup=kb)

@dp.message(AdminStates.waiting_for_char_photo, F.photo)
async def admin_create_char_photo_msg(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    now = int(time.time())
    spawn_loc = get_default_spawn()
    
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO characters (name, role, base_moons, photo_url, current_location_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", 
                       (data["char_name"], data["char_role"], data["char_moons"], photo_id, spawn_loc, now))
        char_id = cursor.lastrowid
        conn.commit()

    await state.clear()
    await message.answer(f"✅ Персонаж {data['char_name']} [{data['char_role']}] ({data['char_moons']} лун) создан!\n🆔 ID: {char_id}")

@dp.callback_query(AdminStates.waiting_for_char_photo, F.data == "skip_char_photo")
async def admin_create_char_photo_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    now = int(time.time())
    spawn_loc = get_default_spawn()
    
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO characters (name, role, base_moons, current_location_id, created_at) VALUES (?, ?, ?, ?, ?)", 
                       (data["char_name"], data["char_role"], data["char_moons"], spawn_loc, now))
        char_id = cursor.lastrowid
        conn.commit()

    await state.clear()
    await callback.message.answer(f"✅ Персонаж {data['char_name']} [{data['char_role']}] ({data['char_moons']} лун) создан без фото!\n🆔 ID: {char_id}")
    await callback.answer()

@dp.callback_query(F.data == "admin_assign_char")
async def admin_assign_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_assign_char_id)
    await callback.message.answer("🔢 Введите ID персонажа, которого нужно привязать:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_assign_char_id)
async def admin_assign_step2(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Введите числовой ID персонажа:")

    await state.update_data(assign_char_id=int(message.text.strip()))
    await state.set_state(AdminStates.waiting_for_assign_user_id)
    await message.answer("👤 Введите Telegram ID пользователя:")

@dp.message(AdminStates.waiting_for_assign_user_id)
async def admin_assign_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Введите числовой Telegram ID:")

    data = await state.get_data()
    char_id = data["assign_char_id"]
    user_id = int(message.text.strip())
    now = int(time.time())

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE characters SET user_id = ?, assigned_at = ? WHERE id = ?", (user_id, now, char_id))
        conn.commit()

    await state.clear()
    await message.answer(f"✅ Персонаж #{char_id} успешно привязан к игроку с ID {user_id}!")

@dp.callback_query(F.data.startswith("confirm_delete:"))
async def admin_confirm_delete_inline(callback: types.CallbackQuery, state: FSMContext):
    char_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Да, удалить", callback_data=f"do_delete:{char_id}"),
            InlineKeyboardButton(text="🟢 Отмена", callback_data="cancel_delete")
        ]
    ])
    await callback.message.edit_text(f"⚠️ **Вы уверены, что хотите безвозвратно удалить персонажа #{char_id}?**", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("do_delete:"))
async def admin_do_delete_inline(callback: types.CallbackQuery, state: FSMContext):
    char_id = int(callback.data.split(":")[1])
    res_text = delete_character_by_id(char_id)
    await state.clear()
    await callback.message.edit_text(res_text)
    await callback.answer()

@dp.callback_query(F.data == "cancel_delete")
async def admin_cancel_delete_inline(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Удаление отменено.")
    await callback.answer()

# --- ИГРОВЫЕ ХЕНДЛЕРЫ ПЕРЕХОДОВ И ВЫБОРА ---

async def show_character_selection(event):
    user_id = event.from_user.id
    if not user_has_access(user_id):
        text = "⛔ У вас нет доступа к проекту."
        return await event.answer(text) if isinstance(event, types.Message) else await event.message.answer(text)

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role, base_moons, assigned_at FROM characters WHERE user_id = ?", (user_id,))
        chars = cursor.fetchall()

    kb = []
    for char_id, name, role, base_m, assigned_at in chars:
        moons = calculate_moons(base_m, assigned_at)
        kb.append([InlineKeyboardButton(text=f"🎭 {name} [{role}] ({moons} лун)", callback_data=f"play:{char_id}")])

    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    text = "🎭 Выберите персонажа для входа в ролевую:"

    if isinstance(event, types.CallbackQuery):
        try:
            await event.message.delete()
        except Exception:
            pass
        await event.message.answer(text, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)

@dp.callback_query(F.data == "select_char")
async def cb_select_char(callback: types.CallbackQuery):
    set_offline(callback.from_user.id)
    await show_character_selection(callback)

@dp.callback_query(F.data.startswith("play:"))
async def cb_play_character(callback: types.CallbackQuery):
    char_id = int(callback.data.split(":")[1])
    update_activity(callback.from_user.id, username=callback.from_user.username, active_char_id=char_id)

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT current_location_id FROM characters WHERE id = ? AND user_id = ?", (char_id, callback.from_user.id))
        row = cursor.fetchone()

    if not row:
        return await callback.answer("⚠️ Персонаж не найден или не принадлежит вам!", show_alert=True)

    loc_id = row[0]
    await render_location_message(callback_or_message=callback, char_id=char_id, location_id=loc_id, is_new_message=True)

@dp.callback_query(F.data.startswith("move:"))
async def cb_move(callback: types.CallbackQuery):
    _, char_id, target_loc_id = callback.data.split(":")
    char_id = int(char_id)
    update_activity(callback.from_user.id, username=callback.from_user.username, active_char_id=char_id)

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT current_location_id FROM characters WHERE id = ? AND user_id = ?", (char_id, callback.from_user.id))
        row = cursor.fetchone()
        
        if not row:
            return await callback.answer("⚠️ Ошибка персонажа.", show_alert=True)

        current_loc_id = row[0]
        cursor.execute("SELECT connections FROM locations WHERE id = ?", (current_loc_id,))
        connections_row = cursor.fetchone()
        allowed_connections = [c.strip() for c in connections_row[0].split(",")] if connections_row else []

        if target_loc_id not in allowed_connections:
            return await callback.answer("❌ Туда нельзя перейти напрямую отсюда!", show_alert=True)

        cursor.execute("UPDATE characters SET current_location_id = ? WHERE id = ?", (target_loc_id, char_id))
        conn.commit()

    # Лог логики перемещения
    loc_from = get_location_info(current_loc_id)
    loc_to = get_location_info(target_loc_id)
    from_name = loc_from[1] if loc_from else current_loc_id
    to_name = loc_to[1] if loc_to else target_loc_id
    
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM characters WHERE id = ?", (char_id,))
        c_row = cursor.fetchone()
        char_n = c_row[0] if c_row else f"#{char_id}"

    await send_to_log("rp", f"🐾 **[Перемещение]** Персонаж **{char_n}** перешел из **{from_name}** в **{to_name}**.")

    await render_location_message(callback_or_message=callback, char_id=char_id, location_id=target_loc_id, is_new_message=False)

@dp.callback_query(F.data.startswith("refresh:"))
async def cb_refresh(callback: types.CallbackQuery):
    _, char_id, loc_id = callback.data.split(":")
    update_activity(callback.from_user.id, username=callback.from_user.username, active_char_id=int(char_id))
    
    try:
        await render_location_message(callback_or_message=callback, char_id=int(char_id), location_id=loc_id, is_new_message=False)
        await callback.answer("🔄 Локация обновлена")
    except Exception as e:
        if "message is not modified" in str(e):
            await callback.answer("🔄 Всё и так актуально!", show_alert=False)
        else:
            raise e

# --- ОБЩЕНИЕ НА ЛОКАЦИЯХ И ЛОГИРОВАНИЕ В ТЕМЫ ---

@dp.message(StateFilter(None))
async def handle_location_chat(message: types.Message):
    user_id = message.from_user.id

    if not user_has_access(user_id):
        return await message.answer("⛔ У вас нет доступа к проекту.")

    raw_text = (message.text or message.caption or "").strip()
    attached_photo_id = message.photo[-1].file_id if message.photo else None

    is_rp = None
    chat_text = raw_text

    if raw_text.startswith("!!"):
        is_rp = True
        chat_text = raw_text[2:].strip()
    elif raw_text.startswith("!"):
        is_rp = False
        chat_text = raw_text[1:].strip()
    elif message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if "🎭" in replied_text:
            is_rp = True
        elif "💬" in replied_text:
            is_rp = False
        else:
            return
    else:
        return

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.active_char_id, c.name, c.role, c.base_moons, c.assigned_at, c.current_location_id, c.photo_url 
            FROM user_activity a
            JOIN characters c ON a.active_char_id = c.id
            WHERE a.user_id = ? AND a.active_char_id IS NOT NULL
        """, (user_id,))
        sender = cursor.fetchone()

    if not sender:
        return await message.answer("⚠️ Для отправки сообщений войдите в игру за персонажа (/repers)!")

    char_id, char_name, char_role, base_m, assigned_at, loc_id, char_avatar_url = sender
    moons = calculate_moons(base_m, assigned_at)

    update_activity(user_id, username=message.from_user.username, active_char_id=char_id, is_rp=is_rp)

    reply_header = ""
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        if replied_text:
            target_lines = replied_text.split("\n")
            clean_lines = [line for line in target_lines if not line.startswith("↩️")]
            if clean_lines:
                target_author = clean_lines[0].replace(":", "").replace("🎭", "").replace("💬", "").strip()
                reply_header = f"↩️ *Ответ для {target_author}*\n"

    user_display_name = message.from_user.first_name

    loc_info = get_location_info(loc_id)
    loc_title = loc_info[1] if loc_info else loc_id

    if is_rp:
        formatted_msg = (
            f"{reply_header}"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎭 *{char_name}* [{char_role} • {moons} лун]\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"{chat_text}"
        )
        # Логирование RP сообщения
        log_msg = f"📍 **[{loc_title}]**\n{formatted_msg}"
        await send_to_log("rp", log_msg, photo=attached_photo_id)
    else:
        formatted_msg = (
            f"{reply_header}"
            f"💬 *[Флуд]* {user_display_name} ({char_name}):\n\n"
            f"{chat_text}"
        )
        # Логирование Флуд сообщения
        log_msg = f"📍 **[{loc_title}]**\n{formatted_msg}"
        await send_to_log("flood", log_msg, photo=attached_photo_id)

    photo_to_send = None

    if attached_photo_id:
        photo_to_send = attached_photo_id
    else:
        last_char_on_loc = last_sender_in_location.get(loc_id)
        if last_char_on_loc != char_id:
            photo_to_send = char_avatar_url

    last_sender_in_location[loc_id] = char_id

    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        cursor = conn.cursor()
        now = int(time.time())
        cursor.execute("""
            SELECT DISTINCT c.user_id 
            FROM characters c
            JOIN user_activity a ON c.user_id = a.user_id
            WHERE c.current_location_id = ? 
              AND a.active_char_id = c.id 
              AND (a.last_active >= ? - 600)
        """, (loc_id, now))
        
        receivers = cursor.fetchall()

    for (receiver_uid,) in receivers:
        try:
            if photo_to_send:
                await bot.send_photo(chat_id=receiver_uid, photo=photo_to_send, caption=formatted_msg, parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=receiver_uid, text=formatted_msg, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения игроку {receiver_uid}: {e}")

async def main():
    init_db()
    asyncio.create_task(random_item_spawner())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
