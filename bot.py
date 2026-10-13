import asyncio
import logging
import sqlite3
import random
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatMemberStatus

# Токен твоего бота
TOKEN = "8805094896:AAEcWq2pPZNZNmHf261lYeSYIIEbiQvIQHg"

# Каналы для обязательной подписки и Главный Владелец
CHANNELS = ["@ANFshop", "@trollshopstick"]
OWNER_ID = 364059659
REFRRAL_BONUS = 5.0  # Награда за приглашенного друга в рублях
DAILY_BONUS_AMOUNT = 5.0  # Ежедневный бонус

dp = Dispatcher()

# Состояния FSM
class TopUpState(StatesGroup):
    waiting_for_amount = State()

class PromoState(StatesGroup):
    waiting_for_code = State()

# ===== БАЗА ДАННЫХ SQLite =====
def init_db():
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            item_type TEXT,
            price REAL,
            status TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_info TEXT,
            date_given TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            referrer_id INTEGER DEFAULT 0,
            last_daily_claim TEXT,
            daily_streak INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            last_bonus_date TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward REAL,
            uses_left INTEGER
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS used_promos (
            user_id INTEGER,
            username TEXT,
            code TEXT,
            activated_at TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    
    cursor.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,))
    conn.commit()
    conn.close()

def generate_unique_order_id():
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    while True:
        order_id = str(random.randint(100000, 999999))
        cursor.execute("SELECT order_id FROM orders WHERE order_id = ?", (order_id,))
        if not cursor.fetchone():
            conn.close()
            return order_id

def save_order(order_id, user_id, username, item_type, price):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (order_id, user_id, username, item_type, price, status) VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, user_id, username, item_type, price, "ожидает обработки")
    )
    conn.commit()
    conn.close()

def add_user_item(user_id, item_info):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("INSERT INTO user_items (user_id, item_info, date_given) VALUES (?, ?, ?)", (user_id, item_info, date_now))
    conn.commit()
    conn.close()

def get_user_items(user_id):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, item_info, date_given FROM user_items WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_user_orders(user_id):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT order_id, item_type, price, status FROM orders WHERE user_id = ? ORDER BY order_id DESC LIMIT 10", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_user_balance(user_id):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, 0.0)", (user_id,))
        conn.commit()
        conn.close()
        return 0.0
    conn.close()
    return row[0]

def update_user_balance(user_id, new_balance):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()

def add_user_balance(user_id, amount):
    balance = get_user_balance(user_id)
    update_user_balance(user_id, balance + amount)

def get_referrals_count(user_id):
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def is_admin(user_id):
    if user_id == OWNER_ID:
        return True
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

init_db()


# ===== КЛАВИАТУРЫ =====
def start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на @ANFshop", url="https://t.me/ANFshop")],
        [InlineKeyboardButton(text="📢 Подписаться на @trollshopstick", url="https://t.me/trollshopstick")],
        [InlineKeyboardButton(text="Я ПОДПИСАЛСЯ НА ВСЕ ✅", callback_data="check_sub")]
    ])

def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎃 Заброшенный автомат 🎰", callback_data="spooky_slot_machine")],
        [InlineKeyboardButton(text="🛒 Каталог товаров", callback_data="menu_catalog_categories")],
        [
            InlineKeyboardButton(text="👤 Личный кабинет", callback_data="menu_profile"),
            InlineKeyboardButton(text="💳 Пополнить", callback_data="top_up_balance")
        ],
        [
            InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus"),
            InlineKeyboardButton(text="👥 Рефералы", callback_data="menu_referral")
        ],
        [InlineKeyboardButton(text="💬 Отзывы и Поддержка", callback_data="menu_support")]
    ])

def catalog_categories_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Обычные аккаунты (по странам)", callback_data="catalog_countries:0")],
        [InlineKeyboardButton(text="⭐ Премиум аккаунты", callback_data="menu_premium")],
        [InlineKeyboardButton(text="🔄 Аккаунты с отлегой (США)", callback_data="menu_otlega")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])

def premium_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇨🇴 Колумбия (880 ₽)", callback_data="buy_prem:columbia:880")],
        [InlineKeyboardButton(text="🇨🇦 Канада (1090 ₽)", callback_data="buy_prem:canada:1090")],
        [InlineKeyboardButton(text="🇺🇸 США (810 ₽)", callback_data="buy_prem:usa:810")],
        [InlineKeyboardButton(text="⤶ В каталог", callback_data="menu_catalog_categories")]
    ])

def otlega_years_keyboard():
    years = ["2014", "2015", "2016", "2017", "2018", "2019", "2020"]
    rows = []
    row = []
    for year in years:
        row.append(InlineKeyboardButton(text=f"🇺🇸 {year} год", callback_data=f"buy_otlega:{year}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⤶ В каталог", callback_data="menu_catalog_categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ===== ПРОВЕРКА ПОДПИСКИ =====
async def check_all_subscriptions(bot: Bot, user_id: int) -> bool:
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
                return False
        except Exception as e:
            print(f"Ошибка проверки подписки на {channel}: {e}")
            return False
    return True


@dp.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    greeting = f"Привет, @{username}! 👋" if username else f"Привет, {message.from_user.first_name}!"

    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    is_existing_user = cursor.fetchone()

    if not is_existing_user:
        args = message.text.split()
        referrer_id = 0
        if len(args) > 1 and args[1].isdigit():
            potential_ref = int(args[1])
            if potential_ref != user_id:
                referrer_id = potential_ref

        cursor.execute("INSERT INTO users (user_id, balance, referrer_id, daily_streak) VALUES (?, 0.0, ?, 0)", (user_id, referrer_id))
        conn.commit()

        if referrer_id != 0:
            add_user_balance(referrer_id, REFRRAL_BONUS)
            try:
                await message.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 <b>По вашей реферальной ссылке зарегистрировался новый пользователь!</b>\n💰 Вам зачислено +{REFRRAL_BONUS} руб.!",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    conn.close()

    balance = get_user_balance(user_id)
    photo_path = "image_4bda3a.jpg"

    if await check_all_subscriptions(message.bot, user_id):
        text = (
            f"{greeting}\n\n"
            f"💰 Ваш баланс: <b>{balance} руб.</b>\n\n"
            "Добро пожаловать в главное меню <b>ANFshop</b>! 🛍️🎃"
        )
        try:
            photo = BufferedInputFile.from_file(photo_path)
            await message.answer_photo(
                photo=photo,
                caption=text,
                parse_mode="HTML",
                reply_markup=main_menu_keyboard()
            )
        except Exception:
            await message.answer(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    else:
        text = (
            f"{greeting}\n\n"
            "Добро пожаловать в ANFshop! 🛍️🎃\n\n"
            "Чтобы продолжить, подпишитесь на оба наших канала:\n"
            "1. @ANFshop\n"
            "2. @trollshopstick"
        )
        try:
            photo = BufferedInputFile.from_file(photo_path)
            await message.answer_photo(
                photo=photo,
                caption=text,
                reply_markup=start_keyboard()
            )
        except Exception:
            await message.answer(text, reply_markup=start_keyboard())

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if await check_all_subscriptions(callback.bot, user_id):
        balance = get_user_balance(user_id)
        text = (
            "Подписки подтверждены! ✅\n\n"
            f"💰 Ваш баланс: <b>{balance} руб.</b>\n\n"
            "Добро пожаловать в главное меню ANFshop:"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        await callback.answer()
    else:
        await callback.answer("❌ Вы подписались не на все каналы!", show_alert=True)


# ===== ХЭЛЛОУИНСКИЙ ЗАБРОШЕННЫЙ АВТОМАТ 🎃 =====
user_spins_counter = {}

@dp.callback_query(F.data == "spooky_slot_machine")
async def spooky_slot_machine_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    balance = get_user_balance(user_id)
    
    text = (
        "🕸️👻 <b>ЗАБРОШЕННЫЙ АВТОМАТ ANFSHOP</b> 🎃🕷️\n\n"
        "<i>Привет, вижу ты смельчак, раз решился сыграть в этот заброшенный автомат...</i> 🕯️🔮\n\n"
        "📜 <b>Правила игры:</b>\n"
        "• Стоимость одной прокрутки: <b>30 рублей</b> 🪙\n\n"
        "🎁 <b>Возможные призы при прокрутке:</b>\n"
        "  — 🇺🇸 Аккаунт США\n"
        "  — 🇬🇧 Аккаунт Великобритания\n"
        "  — 🇺🇦 Аккаунт Украина\n"
        "  — 💰 <b>100 рублей</b> на баланс!\n\n"
        "🤫 <i>Скажу по секрету: если прокрутить автомат 3 раза подряд, тебе гарантированно выпадет аккаунт США со спам-блоком!</i> 👁️\n\n"
        f"💰 Ваш баланс: <b>{balance} руб.</b>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Испытать удачу (30₽)", callback_data="spin_spooky_slot")],
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="top_up_balance")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "spin_spooky_slot")
async def spin_spooky_slot_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = callback.from_user
    price = 30.0
    
    balance = get_user_balance(user_id)
    
    if balance < price:
        await callback.answer("❌ Недостаточно средств! Стоимость игры: 30₽", show_alert=True)
        return

    # Списываем 30 рублей
    new_balance = balance - price
    update_user_balance(user_id, new_balance)

    # Увеличиваем счётчик последовательных прокруток
    user_spins_counter[user_id] = user_spins_counter.get(user_id, 0) + 1
    current_spin = user_spins_counter[user_id]

    # 🎰 АНИМАЦИЯ СЛОТ-МАШИНЫ
    slots_frames = [
        "🎰 | 🎃 | 👻 | 🔮 |",
        "🎰 | 💀 | 🕷️ | 🕸️ |",
        "🎰 | 🎃 | 💀 | 👻 |",
    ]
    
    for frame in slots_frames:
        try:
            await callback.message.edit_text(
                f"🎰 <b>Призрачные барабаны крутятся...</b>\n\n"
                f"<code>[ {frame} ]</code>\n\n"
                f"🕯️ <i>Судьба решается...</i>",
                parse_mode="HTML"
            )
            await asyncio.sleep(0.5)
        except Exception:
            pass

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Сыграть ещё раз (30₽)", callback_data="spin_spooky_slot")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])

    # РЕЖИМ 1: 3-Я ПРОКРУТКА ПОДРЯД (Срабатывает гарантированный приз!)
    if current_spin >= 3:
        user_spins_counter[user_id] = 0  # Сбрасываем счётчик
        order_id = generate_unique_order_id()
        item_name = "🇺🇸 США (со спам-блоком) [СЕКРЕТНЫЙ БОНУС ЗА 3 ПРОКРУТКИ]"
        save_order(order_id, user_id, user.username, item_name, 0.0)
        
        win_text = (
            "🎉🎃 <b>СЕКРЕТНЫЙ ДЖЕКПОТ СРАБОТАЛ!</b> 🎃🎉\n\n"
            "<code>[ 🇺🇸 | 🇺🇸 | 🇺🇸 ]</code>\n\n"
            "Вы прокрутили автомат 3 раза подряд и получаете гарантированный приз:\n"
            "<b>🇺🇸 Аккаунт США (со спам-блоком)</b>!\n\n"
            f"🔢 Номер заказа: <b>#{order_id}</b>\n"
            "👨‍💻 Напишите администратору @anfix для получения товара!"
        )
        
        admin_msg = f"🎁 <b>СЕКРЕТНЫЙ ВЫИГРЫШ (3 прокрутки подряд)!</b>\n👤 Игрок: ID {user_id} (@{user.username})\n📦 Товар: {item_name}\n🔢 Заказ: #{order_id}"
        try:
            await callback.bot.send_message(chat_id=OWNER_ID, text=admin_msg, parse_mode="HTML")
        except Exception:
            pass

        await callback.message.edit_text(win_text, parse_mode="HTML", reply_markup=keyboard)
        return

    # РЕЖИМ 2: ОБЫЧНАЯ ПРОКРУТКА (1-я и 2-я) — Шанс выигрыша 2%
    roll = random.randint(1, 100)
    
    if roll <= 2:
        user_spins_counter[user_id] = 0  # При случайном выигрыше сбрасываем
        prizes = [
            ("🇺🇸 Аккаунт США", "item"),
            ("🇬🇧 Аккаунт Великобритания", "item"),
            ("🇺🇦 Аккаунт Украина", "item"),
            ("💰 100 рублей на баланс", "balance")
        ]
        prize_name, prize_type = random.choice(prizes)

        if prize_type == "balance":
            add_user_balance(user_id, 100.0)
            win_text = (
                "🎉🎃 <b>НЕВЕРОЯТНО! ВЫ ПОБЕДИЛИ!</b> 🎃🎉\n\n"
                "<code>[ 💎 | 💎 | 💎 ]</code>\n\n"
                f"Приз: <b>{prize_name}</b>!\n"
                "💰 +100₽ зачислены на ваш баланс!"
            )
        else:
            order_id = generate_unique_order_id()
            save_order(order_id, user_id, user.username, f"Выигрыш в автомате: {prize_name}", 0.0)
            win_text = (
                "🎉🎃 <b>НЕВЕРОЯТНО! ВЫ ПОБЕДИЛИ!</b> 🎃🎉\n\n"
                "<code>[ 🎁 | 🎁 | 🎁 ]</code>\n\n"
                f"Приз: <b>{prize_name}</b>!\n"
                f"🔢 Номер: <b>#{order_id}</b>\n"
                "👨‍💻 Напишите @anfix для получения!"
            )
            admin_msg = f"🎃 <b>СЛУЧАЙНЫЙ ВЫИГРЫШ В АВТОМАТЕ!</b>\n👤 ID {user_id} (@{user.username})\n📦 Приз: {prize_name}\n🔢 Заказ: #{order_id}"
            try:
                await callback.bot.send_message(chat_id=OWNER_ID, text=admin_msg, parse_mode="HTML")
            except Exception:
                pass

        await callback.message.edit_text(win_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        fail_responses = [
            "<code>[ 🕷️ | 🕸️ | 💀 ]</code>\n\n🕸️ В автомате выпали пауки и тыквы...",
            "<code>[ 👻 | 🕯️ | 💀 ]</code>\n\n💀 Призраки забрали 30 рублей и растворились...",
            "<code>[ 🎃 | 🕸️ | 👻 ]</code>\n\n👻 Скрежет автомата... Неудача!"
        ]
        fail_text = random.choice(fail_responses)
        
        text = (
            f"{fail_text}\n\n"
            f"🔥 Прокруток подряд: <b>{current_spin}/3</b>\n"
            f"💰 Ваш текущий баланс: <b>{new_balance:.2f} руб.</b>"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


# ===== ЕЖЕДНЕВНЫЙ БОНУС C ПРОВЕРКОЙ НА 3-Й ДЕНЬ =====
@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT last_daily_claim, daily_streak FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    last_claim_str, streak = (row[0], row[1]) if row else (None, 0)
    now = datetime.now()

    if last_claim_str:
        last_claim = datetime.strptime(last_claim_str, "%Y-%m-%d %H:%M:%S")
        if now - last_claim < timedelta(hours=24):
            time_left = timedelta(hours=24) - (now - last_claim)
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            await callback.answer(f"⏳ Вы уже забирали бонус! Приходите через {hours} ч. {minutes} мин.", show_alert=True)
            conn.close()
            return
        elif now - last_claim > timedelta(hours=48):
            streak = 0

    new_streak = streak + 1

    # Проверка на 3-й день (защита от ботов)
    if new_streak == 3:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Пополнить на 35+ руб.", callback_data="top_up_balance")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
        ])
        text = (
            "🤖 <b>Проверка на бота!</b>\n\n"
            "Вы получаете ежедневный бонус уже <b>3-й день подряд</b>!\n"
            "А вы точно не бот? 🤔\n\n"
            "Для подтверждения аккаунта и получения бонуса пополните баланс на <b>35+ рублей</b>."
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        conn.close()
        await callback.answer()
        return

    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET last_daily_claim = ?, daily_streak = ? WHERE user_id = ?", (now_str, new_streak, user_id))
    conn.commit()
    conn.close()

    add_user_balance(user_id, DAILY_BONUS_AMOUNT)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    text = (
        "🎁 <b>Ежедневный бонус получен!</b>\n\n"
        f"💰 Вам зачислено: <b>+{DAILY_BONUS_AMOUNT} руб.</b>\n"
        f"🔥 Ваша серия: <b>{new_streak} день подряд</b>\n\n"
        "Возвращайтесь завтра за новым бонусом!"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# ===== КАТАЛОГ =====
@dp.callback_query(F.data == "menu_catalog_categories")
async def menu_catalog_categories(callback: CallbackQuery):
    text = "🛒 <b>Выберите нужный раздел каталога:</b>"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=catalog_categories_keyboard())
    await callback.answer()


# ===== РАССЫЛКА =====
@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Рассылка доступна только владельцу бота.")
        return

    full_text = message.text or message.caption or ""
    args = full_text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer(
            "⚠️ <b>Использование рассылки:</b>\n\n"
            "• <code>/broadcast Текст</code>\n"
            "• Прикрепите фото и напишите <code>/broadcast Текст</code>\n"
            "• Кнопка-ссылка: <code>[Текст кнопки|https://ссылка.com]</code>",
            parse_mode="HTML"
        )
        return

    raw_text = args[1]
    reply_markup = None
    button_match = re.search(r"\[(.*?)\]", raw_text)
    if button_match:
        btn_content = button_match.group(1)
        if "|" in btn_content:
            btn_title, btn_url = btn_content.split("|", 1)
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=btn_title.strip(), url=btn_url.strip())]
            ])
            raw_text = raw_text.replace(button_match.group(0), "").strip()

    photo_id = message.photo[-1].file_id if message.photo else None

    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    if not users:
        await message.answer("⚠️ В базе данных нет пользователей.")
        return

    status_msg = await message.answer(f"⏳ Рассылка запускается для {len(users)} пользователей...")

    success_count = 0
    blocked_count = 0

    for user_row in users:
        u_id = user_row[0]
        try:
            if photo_id:
                await message.bot.send_photo(chat_id=u_id, photo=photo_id, caption=raw_text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                await message.bot.send_message(chat_id=u_id, text=raw_text, parse_mode="HTML", reply_markup=reply_markup)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked_count += 1

    await status_msg.edit_text(
        "✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Доставлено: <b>{success_count}</b>\n"
        f"🚫 Ошибки / Блок: <b>{blocked_count}</b>",
        parse_mode="HTML"
    )


# ===== СТАТИСТИКА БОТА (/stats) =====
@dp.message(Command("stats"))
async def stats_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только для владельца.")
        return

    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
    users_data = cursor.fetchone()
    total_users = users_data[0] or 0
    total_balance = users_data[1] or 0.0

    cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'выполнен'")
    completed_orders = cursor.fetchone()[0] or 0
    conn.close()

    text = (
        "📊 <b>Статистика магазина ANFshop:</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users} чел.</b>\n"
        f"💰 Общий баланс юзеров: <b>{total_balance:.2f} руб.</b>\n"
        f"📦 Успешных заказов: <b>{completed_orders} шт.</b>"
    )
    await message.answer(text, parse_mode="HTML")


# ===== КОМАНДЫ АДМИНА И ВЛАДЕЛЬЦА =====
@dp.message(Command("give"))
async def give_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступно только владельцу.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("⚠️ Использование: `/give [id] [описание товара]`", parse_mode="Markdown")
        return

    target_id = int(args[1])
    item_info = args[2]

    add_user_item(target_id, item_info)

    try:
        await message.bot.send_message(
            chat_id=target_id,
            text=f"🎁 <b>Вам выдан новый аккаунт!</b>\n\n📦 <b>Товар:</b> {item_info}\n\n<i>Перейдите в Личный кабинет в раздел «Мои аккаунты», чтобы забрать его.</i>",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Товар успешно выдан пользователю {target_id}!")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки уведомления: {e}")

@dp.message(Command("addbalance"))
async def add_balance_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец.")
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ Использование: `/addbalance [id] [сумма]`", parse_mode="Markdown")
        return
    add_user_balance(int(args[1]), float(args[2]))
    await message.answer(f"✅ Баланс пополнен на {args[2]} руб. для ID `{args[1]}`", parse_mode="Markdown")

@dp.message(Command("createcode"))
async def create_code_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец может создавать промокоды.")
        return

    args = message.text.split()
    if len(args) < 4:
        await message.answer("⚠️ Использование: `/createcode [код] [сумма] [кол-во_использований]`", parse_mode="Markdown")
        return

    code = args[1].upper()
    reward = float(args[2])
    uses = int(args[3])

    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO promocodes (code, reward, uses_left) VALUES (?, ?, ?)", (code, reward, uses))
    conn.commit()
    conn.close()

    await message.answer(f"🎉 Промокод `<b>{code}</b>` на <b>{reward} руб.</b> (использований: {uses}) успешно создан!", parse_mode="HTML")

@dp.message(Command("promostats"))
async def promo_stats_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Использование: `/promostats [код]`", parse_mode="Markdown")
        return

    code = args[1].upper()
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()

    cursor.execute("SELECT reward, uses_left FROM promocodes WHERE code = ?", (code,))
    promo = cursor.fetchone()

    cursor.execute("SELECT user_id, username, activated_at FROM used_promos WHERE code = ?", (code,))
    activations = cursor.fetchall()
    conn.close()

    text = f"📊 <b>Статистика промокода: <code>{code}</code></b>\n\n"
    if promo:
        text += f"💰 Награда: {promo[0]}₽\n"
        text += f"🎟 Осталось активаций: {promo[1]}\n\n"
    else:
        text += "⚠️ Промокод полностью использован или удален.\n\n"

    if not activations:
        text += "👥 Этот промокод еще никто не активировал."
    else:
        text += "👥 <b>Активации:</b>\n"
        for user_id, uname, date_time in activations:
            user_link = f"@{uname}" if uname else f"ID: {user_id}"
            text += f"• {user_link} (`{user_id}`) — <i>{date_time}</i>\n"

    await message.answer(text, parse_mode="HTML")

@dp.message(Command("owner"))
async def owner_help_command(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Доступно только владельцу.")
        return
    text = (
        "👑 <b>Панель владельца ANFshop:</b>\n\n"
        "• `/broadcast [текст]` — медиа-рассылка всем юзерам\n"
        "• `/stats` — общая статистика магазина\n"
        "• `/give [id] [товар]` — выдать товар\n"
        "• `/addbalance [id] [сумма]` — выдать баланс\n"
        "• `/createcode [код] [сумма] [кол-во]` — новый промокод\n"
        "• `/promostats [код]` — статистика промокода"
    )
    await message.answer(text, parse_mode="HTML")


# ===== КАТАЛОГ СТРАН =====
COUNTRIES = [
    # 1/7
    ("🇺🇸", "США", 76), ("🇨🇴", "Колумбия", 76),
    ("🇵🇭", "Филиппины", 76), ("🇧🇩", "Бангладеш", 76),
    ("🇲🇲", "Мьянма", 76), ("🇮🇳", "Индия", 76),
    ("🇦🇷", "Аргентина", 76), ("🇲🇽", "Мексика", 76),
    ("🇱🇰", "Шри-Ланка", 76), ("🇰🇭", "Камбоджа", 76),

    # 2/7
    ("🇦🇫", "Афганистан", 76), ("🇵🇾", "Парагвай", 76),
    ("🇪🇨", "Эквадор", 76), ("🇭🇰", "Гонконг", 76),
    ("🇨🇦", "Канада", 76), ("🇧🇷", "Бразилия", 80),
    ("🇮🇩", "Индонезия", 84), ("🇨🇱", "Чили", 88),
    ("🇰🇪", "Кения", 90), ("🇲🇾", "Малайзия", 100),

    # 3/7
    ("🇪🇬", "Египет", 100), ("🇳🇬", "Нигерия", 100),
    ("🇨🇲", "Камерун", 106), ("🇵🇱", "Польша", 108),
    ("🇨🇳", "Китай", 110), ("🇿🇦", "ЮАР", 132),
    ("🇧🇬", "Болгария", 134), ("🇬🇧", "Великобритания", 134),
    ("🇮🇱", "Израиль", 134), ("🇬🇺", "Гуам", 134),

    # 4/7
    ("🇻🇺", "Вануату", 134), ("🇧🇼", "Ботсвана", 136),
    ("🇹🇭", "Таиланд", 148), ("🇪🇸", "Испания", 150),
    ("🇵🇹", "Португалия", 174), ("🇺🇿", "Узбекистан", 194),
    ("🇲🇷", "Мавритания", 208), ("🇯🇵", "Япония", 212),
    ("🇹🇩", "Чад", 218), ("🇦🇮", "Ангилья", 218),

    # 5/7
    ("🇩🇴", "Доминиканская Респ.", 220), ("🇮🇷", "Иран", 226),
    ("🇹🇯", "Таджикистан", 228), ("🇦🇴", "Ангола", 230),
    ("🇳🇿", "Новая Зеландия", 248), ("🇦🇪", "ОАЭ", 248),
    ("🇬🇷", "Греция", 254), ("🇹🇷", "Турция", 260),
    ("🇦🇱", "Албания", 290), ("🇻🇳", "Вьетнам", 294),

    # 6/7
    ("🇩🇿", "Алжир", 296), ("🇮🇹", "Италия", 298),
    ("🇪🇪", "Эстония", 308), ("🇫🇷", "Франция", 348),
    ("🇾🇪", "Йемен", 350), ("🇰🇿", "Казахстан", 388),
    ("🇫🇮", "Финляндия", 436), ("🇺🇦", "Украина", 490),
    ("🇲🇩", "Молдова", 550), ("🇨🇿", "Чехия", 634),

    # 7/7
    ("🇧🇾", "Беларусь", 662), ("🇬🇪", "Грузия", 814),
]

COUNTRIES_PER_PAGE = 10

def catalog_keyboard(page: int = 0):
    start = page * COUNTRIES_PER_PAGE
    end = start + COUNTRIES_PER_PAGE
    page_countries = COUNTRIES[start:end]
    rows = []
    row = []
    for index_in_page, (flag, name, price) in enumerate(page_countries):
        country_index = start + index_in_page
        row.append(InlineKeyboardButton(text=f"{flag} {name} · {price}₽", callback_data=f"country_info:{country_index}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
        
    total_pages = (len(COUNTRIES) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⤶ Назад", callback_data=f"catalog_info_page:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="catalog:noop"))
    if end < len(COUNTRIES):
        nav_row.append(InlineKeyboardButton(text="➫ Вперёд", callback_data=f"catalog_info_page:{page + 1}"))
    rows.append(nav_row)
    rows.append([InlineKeyboardButton(text="⤶ В каталог", callback_data="menu_catalog_categories")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.regexp(r"^catalog_countries:\d+$"))
async def catalog_countries_handler(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.message.edit_text("🌐 <b>Укажите страну:</b>", parse_mode="HTML", reply_markup=catalog_keyboard(page=page))
    await callback.answer()

@dp.callback_query(F.data.regexp(r"^catalog_info_page:\d+$"))
async def catalog_info_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.message.edit_text("🌐 <b>Укажите страну:</b>", parse_mode="HTML", reply_markup=catalog_keyboard(page=page))
    await callback.answer()

@dp.callback_query(F.data.regexp(r"^country_info:\d+$"))
async def country_info_handler(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    flag, name, price = COUNTRIES[index]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Купить за {price}₽", callback_data=f"confirm_buy_country:{index}")],
        [InlineKeyboardButton(text="⤶ Назад к списку", callback_data="catalog_countries:0")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(f"<b>{flag} {name}</b>\n\n💵 Цена: <b>{price}₽</b>", parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "menu_premium")
async def menu_premium(callback: CallbackQuery):
    await callback.message.edit_text("⭐ <b>Премиум аккаунты:</b>", parse_mode="HTML", reply_markup=premium_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data.regexp(r"^buy_prem:(.+):(\d+)$"))
async def buy_prem_country(callback: CallbackQuery):
    parts = callback.data.split(":")
    country_key = parts[1]
    price = float(parts[2])
    country_names = {"columbia": "🇨🇴 Колумбия (Премиум)", "canada": "🇨🇦 Канада (Премиум)", "usa": "🇺🇸 США (Премиум)"}
    item_type = country_names.get(country_key, "Премиум аккаунт")
    
    user = callback.from_user
    balance = get_user_balance(user.id)
    if balance < price:
        await callback.answer(f"❌ Недостаточно средств! Нужно: {price} ₽, а у вас: {balance} ₽.", show_alert=True)
        return
    
    new_balance = balance - price
    update_user_balance(user.id, new_balance)
    order_id = generate_unique_order_id()
    save_order(order_id, user.id, user.username, item_type, price)
    
    await callback.message.edit_text(
        f"✅ <b>Заказ оплачен!</b>\n📦 Товар: {item_type}\n💵 Списано: {price} ₽\n🔢 Номер: <b>{order_id}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]])
    )
    
    admin_text = f"🔔 <b>Оплаченный Премиум заказ!</b>\n🔢 #{order_id}\n👤 ID: {user.id}\n📦 {item_type}"
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Заказ выполнен✅", callback_data=f"admin_done:{order_id}"),
        InlineKeyboardButton(text="Отменить заказ❌", callback_data=f"admin_cancel:{order_id}")
    ]])
    try:
        await callback.bot.send_message(chat_id=OWNER_ID, text=admin_text, parse_mode="HTML", reply_markup=admin_keyboard)
    except Exception:
        pass
    await callback.answer("Заказ успешно оформлен!")

@dp.callback_query(F.data.regexp(r"^confirm_buy_country:\d+$"))
async def confirm_buy_country(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    flag, name, price = COUNTRIES[index]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтверждаю, создать заказ", callback_data=f"create_order_country:{index}")],
        [InlineKeyboardButton(text="⤶ Отмена", callback_data=f"country_info:{index}")]
    ])
    await callback.message.edit_text(f"⚠️ <b>Внимание!</b> Купить {flag} {name} за {price}₽?", parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.regexp(r"^create_order_country:\d+$"))
async def create_order_country(callback: CallbackQuery):
    index = int(callback.data.split(":")[1])
    flag, name, price = COUNTRIES[index]
    user = callback.from_user
    
    balance = get_user_balance(user.id)
    if balance < price:
        await callback.answer(f"❌ Недостаточно средств! Нужно: {price}₽, а у вас: {balance}₽.", show_alert=True)
        return

    new_balance = balance - price
    update_user_balance(user.id, new_balance)

    order_id = generate_unique_order_id()
    item_type = f"Обычный аккаунт: {flag} {name}"
    save_order(order_id, user.id, user.username, item_type, price)
    
    await callback.message.edit_text(
        f"✅ <b>Заказ #{order_id} создан!</b>\n📦 Товар: {item_type}\n💵 Списано: {price}₽\n\nНапишите администратору @anfix для получения.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]])
    )
    admin_text = f"🔔 <b>Новый оплаченный заказ!</b>\n🔢 #{order_id}\n👤 ID: {user.id}\n📦 {item_type}\n💵 {price}₽"
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Заказ выполнен✅", callback_data=f"admin_done:{order_id}"),
        InlineKeyboardButton(text="Отменить заказ❌", callback_data=f"admin_cancel:{order_id}")
    ]])
    try:
        await callback.bot.send_message(chat_id=OWNER_ID, text=admin_text, parse_mode="HTML", reply_markup=admin_keyboard)
    except Exception:
        pass
    await callback.answer("Заказ успешно оформлен!")

@dp.callback_query(F.data == "menu_otlega")
async def menu_otlega(callback: CallbackQuery):
    await callback.message.edit_text("🔄 Отлега США, выберите год:", reply_markup=otlega_years_keyboard())
    await callback.answer()

@dp.callback_query(F.data.regexp(r"^buy_otlega:.+$"))
async def buy_otlega_year(callback: CallbackQuery):
    year = callback.data.split(":")[1]
    user = callback.from_user
    order_id = generate_unique_order_id()
    item_type = f"отлега США {year} год"
    save_order(order_id, user.id, user.username, item_type, 0.0)
    
    await callback.message.edit_text(
        f"✅ Заказ создан! Номер: <b>{order_id}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]])
    )
    await callback.answer("Заказ создан!")


# ===== ПОПОЛНЕНИЕ БАЛАНСА =====
@dp.callback_query(F.data == "top_up_balance")
async def top_up_balance(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="50₽", callback_data="pay_sum:50"),
            InlineKeyboardButton(text="100₽", callback_data="pay_sum:100")
        ],
        [
            InlineKeyboardButton(text="250₽", callback_data="pay_sum:250"),
            InlineKeyboardButton(text="500₽", callback_data="pay_sum:500")
        ],
        [
            InlineKeyboardButton(text="1000₽", callback_data="pay_sum:1000"),
            InlineKeyboardButton(text="2500₽", callback_data="pay_sum:2500")
        ],
        [InlineKeyboardButton(text="✍️ Своя сумма", callback_data="pay_custom")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text("💳 <b>На какую сумму пополнить?</b>", parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "pay_custom")
async def pay_custom_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TopUpState.waiting_for_amount)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⤶ Назад", callback_data="top_up_balance")]
    ])
    await callback.message.edit_text(
        "✍️ <b>Введите сумму для пополнения:</b>\n\n<i>Минимальная сумма пополнения — 50₽</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.message(TopUpState.waiting_for_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Пожалуйста, введите число.")
        return
    
    amount = int(message.text)
    if amount < 50:
        await message.answer("❌ Минимальная сумма пополнения — 50₽.")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_method:stars:{amount}"),
            InlineKeyboardButton(text="🚀 xRocket", callback_data=f"pay_method:xrocket:{amount}")
        ],
        [
            InlineKeyboardButton(text="🔹 CryptoBot", callback_data=f"pay_method:cryptobot:{amount}"),
            InlineKeyboardButton(text="🔮 СБП", callback_data=f"pay_method:sbp:{amount}")
        ],
        [InlineKeyboardButton(text="⤶ Назад", callback_data="top_up_balance")]
    ])
    await message.answer(
        f"👛 <b>Сумма: {amount}₽</b>\n\n<i>Выберите способ оплаты:</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await state.clear()

@dp.callback_query(F.data.regexp(r"^pay_sum:\d+$"))
async def pay_sum_handler(callback: CallbackQuery):
    amount = int(callback.data.split(":")[1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Telegram Stars", callback_data=f"pay_method:stars:{amount}"),
            InlineKeyboardButton(text="🚀 xRocket", callback_data=f"pay_method:xrocket:{amount}")
        ],
        [
            InlineKeyboardButton(text="🔹 CryptoBot", callback_data=f"pay_method:cryptobot:{amount}"),
            InlineKeyboardButton(text="🔮 СБП", callback_data=f"pay_method:sbp:{amount}")
        ],
        [InlineKeyboardButton(text="⤶ Назад", callback_data="top_up_balance")]
    ])
    await callback.message.edit_text(
        f"👛 <b>Сумма: {amount}₽</b>\n\n<i>Выберите способ оплаты:</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.regexp(r"^pay_method:(.+):(\d+)$"))
async def pay_method_handler(callback: CallbackQuery):
    parts = callback.data.split(":")
    method = parts[1]
    amount = parts[2]
    
    method_names = {"stars": "⭐ Telegram Stars", "xrocket": "🚀 xRocket", "cryptobot": "🔹 CryptoBot", "sbp": "🔮 СБП"}
    m_name = method_names.get(method, "Оплата")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👛 Оплатить", url="https://t.me/anfix")],
        [InlineKeyboardButton(text="⤶ Назад", callback_data="top_up_balance")]
    ])
    await callback.message.edit_text(
        f"💳 <b>{m_name}. Счёт создан</b>\n"
        f"Сумма к оплате: <b>{amount}₽</b>\n\n"
        f"<i>Для завершения оплаты нажмите кнопку ниже и перейдите к владельцу (@anfix).</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await callback.answer()


# ===== РЕФЕРАЛЬНАЯ СИСТЕМА =====
@dp.callback_query(F.data == "menu_referral")
async def menu_referral_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    ref_count = get_referrals_count(user_id)

    text = (
        "🤝 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и зарабатывайте <b>+{REFRRAL_BONUS} руб.</b> на баланс за каждого нового пользователя!\n\n"
        f"📊 Ваш результат: <b>{ref_count} чел.</b>\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# ===== ОТЗЫВЫ И ПОДДЕРЖКА =====
@dp.callback_query(F.data == "menu_support")
async def menu_support_handler(callback: CallbackQuery):
    text = (
        "💬 <b>Поддержка и Отзывы</b>\n\n"
        "Если у вас возникли вопросы по оплате, выдаче аккаунтов или есть предложения по работе магазина — напишите нашему администратору.\n\n"
        "👨‍💻 Администратор: @anfix\n"
        "📢 Наш канал и отзывы: @ANFshop"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Написать админу", url="https://t.me/anfix")],
        [InlineKeyboardButton(text="📢 Отзывы @ANFshop", url="https://t.me/ANFshop")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


# ===== АКТИВАЦИЯ ПРОМОКОДОВ =====
@dp.callback_query(F.data == "activate_promo")
async def activate_promo_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PromoState.waiting_for_code)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⤶ В Личный кабинет", callback_data="menu_profile")]
    ])
    await callback.message.edit_text("🎟 <b>Введите промокод:</b>", parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.message(PromoState.waiting_for_code)
async def process_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user = message.from_user
    user_id = user.id
    username = user.username

    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()

    cursor.execute("SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        await message.answer("❌ Вы уже активировали этот промокод!")
        conn.close()
        await state.clear()
        return

    cursor.execute("SELECT reward, uses_left FROM promocodes WHERE code = ?", (code,))
    row = cursor.fetchone()

    if not row:
        await message.answer("❌ Промокод не найден или истёк.")
        conn.close()
        await state.clear()
        return

    reward, uses_left = row

    if uses_left <= 0:
        await message.answer("❌ Этот промокод больше недоступен.")
        conn.close()
        await state.clear()
        return

    new_uses = uses_left - 1
    if new_uses > 0:
        cursor.execute("UPDATE promocodes SET uses_left = ? WHERE code = ?", (new_uses, code))
    else:
        cursor.execute("DELETE FROM promocodes WHERE code = ?", (code,))

    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute(
        "INSERT INTO used_promos (user_id, username, code, activated_at) VALUES (?, ?, ?, ?)",
        (user_id, username, code, date_now)
    )
    conn.commit()
    conn.close()

    add_user_balance(user_id, reward)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 В Личный кабинет", callback_data="menu_profile")]
    ])
    await message.answer(f"🎉 <b>Промокод активирован!</b>\n💰 Вам зачислено <b>+{reward} руб.</b> на баланс!", parse_mode="HTML", reply_markup=keyboard)
    await state.clear()


# ===== АДМИНСКИЕ КНОПКИ ЗАКАЗОВ =====
@dp.callback_query(F.data.regexp(r"^admin_done:.+$"))
async def admin_order_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    order_id = callback.data.split(":")[1]
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = 'выполнен' WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text(callback.message.text + "\n\n✅ <b>СТАТУС: Заказ выполнен</b>", parse_mode="HTML")
    await callback.answer("Выполнено.")

@dp.callback_query(F.data.regexp(r"^admin_cancel:.+$"))
async def admin_order_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!", show_alert=True)
        return
    order_id = callback.data.split(":")[1]
    conn = sqlite3.connect("anfshop.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = 'отменён' WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text(callback.message.text + "\n\n❌ <b>СТАТУС: Заказ отменён</b>", parse_mode="HTML")
    await callback.answer("Отменено.")


# ===== ЛИЧНЫЙ КАБИНЕТ =====
@dp.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    balance = get_user_balance(user_id)
    items_count = len(get_user_items(user_id))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Мои аккаунты / Товары", callback_data="my_items")],
        [InlineKeyboardButton(text="📜 История заказов", callback_data="my_orders")],
        [InlineKeyboardButton(text="🎟 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    
    text = (
        "👤 <b>Личный кабинет ANFshop</b>\n\n"
        f"🆔 Ваш ID: <code>{user_id}</code>\n"
        f"💰 Баланс: <b>{balance} руб.</b>\n"
        f"📦 Выдано товаров: <b>{items_count} шт.</b>"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "my_items")
async def my_items_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    items = get_user_items(user_id)
    
    if not items:
        text = "🎁 <b>Мои аккаунты:</b>\n\nУ вас пока нет выданных товаров."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⤶ В Личный кабинет", callback_data="menu_profile")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
        ])
    else:
        text = "🎁 <b>Ваши аккаунты (выданные магазином):</b>\n\nНажмите кнопку под товаром, чтобы забрать его у владельца:"
        rows = []
        for item_id, item_info, date_given in items:
            rows.append([InlineKeyboardButton(text=f"🎁 Забрать: {item_info}", url="https://t.me/anfix")])
            
        rows.append([InlineKeyboardButton(text="⤶ В Личный кабинет", callback_data="menu_profile")])
        rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
        
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "my_orders")
async def my_orders_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    orders = get_user_orders(user_id)
    if not orders:
        text = "📜 У вас пока нет заказов."
    else:
        text = "📜 <b>Ваши заказы:</b>\n\n"
        for order_id, item_type, price, status in orders:
            text += f"• Заказ #{order_id} | {item_type} | {status}\n"
            
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⤶ В Личный кабинет", callback_data="menu_profile")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    balance = get_user_balance(user_id)
    text = (
        "Добро пожаловать в главное меню <b>ANFshop</b>:\n"
        f"💰 Ваш баланс: <b>{balance} руб.</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "catalog:noop")
async def catalog_noop(callback: CallbackQuery):
    await callback.answer()


async def main():
    bot = Bot(token=TOKEN)
    logging.basicConfig(level=logging.INFO)
    print("=== Бот ANFshop успешно запущен с Хэллоуинским обновлением! ===")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())