# main.py
import asyncio
import logging
import aiosqlite
import time
import random
import string
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен бота (ЗАМЕНИ НА СВОЙ!)
BOT_TOKEN = "8272534352:AAE2g5pYc-hAy1b9HntCurNDdE1GnMr_SpQ"
# ID администратора (ЗАМЕНИ НА СВОЙ!)
ADMIN_ID = 7471568341

# Инициализация бота и диспетчера с FSM-хранилищем
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Путь к базе данных
DB_PATH = "users.db"

# Генераторы кодов
def generate_ref_code(length=7):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_check_code():
    chars = string.ascii_letters + string.digits
    return "SI" + ''.join(random.choice(chars) for _ in range(6))

def generate_game_id():
    chars = string.ascii_letters + string.digits
    return "#" + ''.join(random.choice(chars) for _ in range(16))

# --- FSM STATES ---
class DiceGameState(StatesGroup):
    waiting_for_bet = State()      # Ожидание ввода ставки
    waiting_for_players = State()  # Ожидание выбора количества игроков
    waiting_for_check_amount = State()  # Ожидание суммы для чека

class BlackjackGameState(StatesGroup):
    waiting_for_bet = State()      # Ожидание ввода ставки
    waiting_for_players = State()  # Ожидание выбора количества игроков

class WithdrawState(StatesGroup):
    waiting_for_amount = State()  # Ожидание ввода суммы
    waiting_for_method = State()  # Ожидание выбора метода
    waiting_for_details = State() # Ожидание ввода деталей (номер карты/телефона)
    waiting_for_confirmation = State()  # Ожидание подтверждения

class AdminState(StatesGroup):
    waiting_for_crypto_check = State()

DICE_STICKERS = {
    1: "CAACAgEAAxkBAAEPVvdowN7mr81AXLFhy9T-eeegBzoY3QACfw4AAoI0egGMUY9GQldDATYE", 
    2: "CAACAgEAAxkBAAEPVvhowN7mScBz_UpnH4bY0HaGVVfrqAACgA4AAoI0egEMlvotM7vbaDYE",
    3: "CAACAgEAAxkBAAEPVvlowN7nO_uNvOoXNtJ1u18o6usXiwACgQ4AAoI0egHmMZTw4jEsUjYE",
    4: "CAACAgEAAxkBAAEPVvtowN7ns9Ffk5UGYqoYiqeV6gjQuQACgg4AAoI0egFxeg_q3jlyvTYE",
    5: "CAACAgEAAxkBAAEPVvxowN7n4ORijJtz5HMOPDhbhSKtqAACgw4AAoI0egHMmDGMXUyPXzYE",
    6: "CAACAgEAAxkBAAEPVv1owN7oZynbnfooipcUkk7z3fgk-wAChA4AAoI0egEyx_5CLNK94DYE",
}

# --- ИГРА 21 (Blackjack) ---
# Колода карт: значение -> очки
DECK = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
    'J': 10, 'Q': 10, 'K': 10, 'A': 11  # Туз может быть 1 или 11, обрабатываем в calculate_score
}

SUITS = ['♠️', '♥️', '♦️', '♣️']

def calculate_score(hand: list) -> int:
    """Рассчитывает сумму очков в руке. Туз считается как 11, если не приводит к перебору, иначе как 1."""
    score = 0
    aces = 0
    for card in hand:
        value = card[:-1]  # Убираем масть
        if value == 'A':
            aces += 1
            score += 11
        else:
            score += DECK[value]
    # Если есть тузы и перебор, считаем тузы как 1
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score

def deal_card() -> str:
    """Выдает случайную карту в формате 'ЗначениеМасть', например 'A♠️'."""
    value = random.choice(list(DECK.keys()))
    suit = random.choice(SUITS)
    return f"{value}{suit}"

def hand_to_str(hand: list) -> str:
    """Преобразует список карт в строку для отображения."""
    return ' '.join(hand)

# Инициализация БД
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                deposit REAL DEFAULT 0.0,
                games INTEGER DEFAULT 0,
                withdraw REAL DEFAULT 0.0,
                status TEXT DEFAULT 'нет',
                reg_time INTEGER,
                referral_id INTEGER REFERENCES users(user_id),
                ref_code TEXT UNIQUE,
                agreed_policy INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                joined_at INTEGER NOT NULL,
                total_deposit REAL DEFAULT 0.0,
                bonus_paid REAL DEFAULT 0.0,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                creator_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                activated_by INTEGER,
                created_at INTEGER NOT NULL,
                activated_at INTEGER,
                FOREIGN KEY (creator_id) REFERENCES users(user_id),
                FOREIGN KEY (activated_by) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dice_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT UNIQUE NOT NULL,
                creator_id INTEGER NOT NULL,
                bet REAL NOT NULL,
                max_players INTEGER NOT NULL,
                status TEXT DEFAULT 'waiting',
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                winner_id INTEGER,
                FOREIGN KEY (creator_id) REFERENCES users(user_id),
                FOREIGN KEY (winner_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dice_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                dice_value INTEGER,
                turn_order INTEGER,
                last_turn_time INTEGER,
                FOREIGN KEY (game_id) REFERENCES dice_games(game_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(game_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                amount REAL NOT NULL,
                creator_id INTEGER NOT NULL,
                total_uses INTEGER NOT NULL,
                uses_left INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (creator_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                method TEXT NOT NULL,
                details TEXT,
                crypto_check_url TEXT,
                fee REAL NOT NULL,
                final_amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                processed_at INTEGER,
                processed_by INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (processed_by) REFERENCES users(user_id)
            )
        """)
        # Таблица для игр "21"
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blackjack_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT UNIQUE NOT NULL,
                creator_id INTEGER NOT NULL,
                bet REAL NOT NULL,
                max_players INTEGER NOT NULL,
                status TEXT DEFAULT 'waiting',
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                winner_id INTEGER,
                FOREIGN KEY (creator_id) REFERENCES users(user_id),
                FOREIGN KEY (winner_id) REFERENCES users(user_id)
            )
        """)
        # Таблица для игроков в "21"
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blackjack_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                hand TEXT NOT NULL DEFAULT '[]',
                score INTEGER DEFAULT 0,
                is_standing BOOLEAN DEFAULT 0,
                turn_order INTEGER,
                last_turn_time INTEGER,
                FOREIGN KEY (game_id) REFERENCES blackjack_games(game_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(game_id, user_id)
            )
        """)
        await db.commit()

# Вспомогательные функции
def get_reg_days(reg_time: int) -> int:
    days = (int(time.time()) - reg_time) // (24 * 60 * 60)
    return days

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, username, balance, deposit, games, withdraw, status, reg_time, ref_code, agreed_policy FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "username": row[1],
                    "balance": row[2],
                    "deposit": row[3],
                    "games": row[4],
                    "withdraw": row[5],
                    "status": row[6],
                    "reg_time": row[7],
                    "ref_code": row[8],
                    "agreed_policy": row[9],
                }
            else:
                return None

async def add_user(user_id: int, username: str = None, ref_code: str = None, agreed_policy: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            exists = await cursor.fetchone()
            if exists:
                return
        my_ref_code = generate_ref_code()
        while True:
            async with db.execute("SELECT 1 FROM users WHERE ref_code = ?", (my_ref_code,)) as cursor:
                if not await cursor.fetchone():
                    break
            my_ref_code = generate_ref_code()
        referral_id = None
        if ref_code:
            async with db.execute("SELECT user_id FROM users WHERE ref_code = ?", (ref_code,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    referral_id = row[0]
        reg_time = int(time.time())
        await db.execute(
            "INSERT INTO users (user_id, username, reg_time, referral_id, ref_code, agreed_policy) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, reg_time, referral_id, my_ref_code, agreed_policy)
        )
        if referral_id:
            await db.execute(
                "INSERT INTO referrals (referrer_id, referred_id, joined_at) VALUES (?, ?, ?)",
                (referral_id, user_id, reg_time)
            )
        await db.commit()

# Клавиатуры
def get_reply_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎮 Игры"))
    builder.add(KeyboardButton(text="👤 Профиль"))
    builder.add(
        KeyboardButton(text="📚 Информация"),
        KeyboardButton(text="🖥 Статистика")
    )
    builder.adjust(1, 1, 2)
    return builder.as_markup(resize_keyboard=True)

def get_games_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎲 Кости"))
    builder.add(KeyboardButton(text="🃏 21"))
    builder.add(KeyboardButton(text="🔙 В главное меню"))
    builder.adjust(1, 1, 1)
    return builder.as_markup(resize_keyboard=True)

def get_back_to_profile_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Вернуться в профиль", callback_data="back_to_profile")
    return builder.as_markup()

# Функции отображения
async def show_profile(message: Message | CallbackQuery, user_id: int):
    db_list = await get_user(user_id)
    if not db_list:
        if isinstance(message, CallbackQuery):
            await message.answer("Ошибка: пользователь не найден", show_alert=True)
        else:
            await message.answer("Ты не зарегистрирован. Напиши /start")
        return
    user = (await bot.get_chat(user_id)) if isinstance(message, CallbackQuery) else message.from_user
    profile_msg = f"""<b>📊 Ваш профиль</b>
➖➖➖➖➖➖➖
👤 <b>Имя:</b> {user.first_name}
🆔 <b>ID:</b> {user.id}
💰 <b>Баланс:</b> {db_list['balance']:.2f} RUB
➖➖➖➖➖➖➖
📥 <b>Депозитов:</b> {db_list['deposit']:.2f} RUB (за неделю 0.00 RUB)
➖➖➖➖➖➖➖
💳 <b>Выводов:</b> {db_list['withdraw']:.2f} RUB
🎮 <b>Кол-во игр:</b> {db_list['games']}
❤️ <b>Вы с нами:</b> {get_reg_days(db_list['reg_time'])} дней"""
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="🔥 Пополнить", callback_data="deposit"),
        InlineKeyboardButton(text="📤 Вывести", callback_data="withdraw"),
        InlineKeyboardButton(text="📋 Активировать промокод", callback_data="active_promo"),
        InlineKeyboardButton(text="⭐️ Чеки", callback_data="show_checks"),
        InlineKeyboardButton(text="👥 Реферальная система", callback_data="refferals_sys")
    )
    builder.adjust(2, 2, 2)
    if isinstance(message, CallbackQuery):
        await message.message.answer(profile_msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(profile_msg, reply_markup=builder.as_markup(), parse_mode="HTML")

async def show_policy(message: Message):
    policy_text = f"""📜 <b>Пользовательское соглашение</b>
Приветствуем вас в нашем Telegram-казино!
🔹 Играя у нас, вы соглашаетесь с тем, что:
• Вам исполнилось 18 лет
• Вы несете полную ответственность за свои действия
• Бот не несет ответственности за возможные потери
• Все транзакции финальны и не подлежат возврату
• Администрация оставляет за собой право изменять правила
Нажимая «✅ Принимаю», вы подтверждаете, что прочитали и согласны с условиями."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принимаю", callback_data="accept_policy")
    await message.answer(policy_text, reply_markup=builder.as_markup(), parse_mode="HTML")

# --- ИГРА КОСТИ (встроенная) ---
@dp.callback_query(F.data == "dice_lobby")
async def dice_lobby_handler(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT dg.game_id, dg.bet, dg.max_players, COUNT(dp.user_id) as current_players
            FROM dice_games dg
            LEFT JOIN dice_players dp ON dg.game_id = dp.game_id
            WHERE dg.status = 'waiting'
            GROUP BY dg.game_id
            HAVING current_players < dg.max_players
            ORDER BY dg.created_at DESC
        """) as cursor:
            games = await cursor.fetchall()
    msg = "<b>🎲 Лобби игры \"Кости\"</b>\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать игру", callback_data="create_dice_game")
    if games:
        msg += "Доступные лобби:\n"
        for game_id, bet, max_players, current_players in games:
            builder.button(text=f"{game_id} ({current_players}/{max_players}) {bet:.0f} RUB", callback_data=f"dice_game_info:{game_id}")
    else:
        msg += "Нет доступных лобби. Создайте своё!\n"
    builder.button(text="📋 Мои лобби", callback_data="my_dice_games")
    builder.button(text="🔙 Назад", callback_data="back_to_games")
    builder.adjust(1, *[1] * len(games), 1, 1)
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "create_dice_game")
async def create_dice_game_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DiceGameState.waiting_for_bet)
    await callback.message.delete()
    msg = "Введите ставку на игрока (минимум 20 RUB):"
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="cancel_dice_creation")
    await callback.message.answer(msg, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "cancel_dice_creation")
async def cancel_dice_creation(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Создание игры отменено.", reply_markup=InlineKeyboardBuilder()
        .button(text="🎲 Вернуться к лобби", callback_data="dice_lobby")
        .as_markup()
    )

@dp.message(DiceGameState.waiting_for_bet)
async def handle_bet_amount(message: Message, state: FSMContext):
    print(f"[DEBUG GAME] Получена ставка от {message.from_user.id}: {message.text}")
    if not message.text.isdigit() or int(message.text) < 20:
        await message.answer("❌ Введите корректную сумму (минимум 20 RUB):")
        return
    bet = int(message.text)
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < bet:
                await message.answer("❌ Недостаточно средств.")
                return
    await state.update_data(bet=bet)
    await state.set_state(DiceGameState.waiting_for_players)
    builder = InlineKeyboardBuilder()
    for i in range(2, 6):
        builder.button(text=f"{i} игроков", callback_data=f"set_players:{i}")
    builder.button(text="❌ Отменить", callback_data="cancel_dice_creation")
    builder.adjust(4, 1)
    await message.answer(f"Выберите количество игроков (минимум 2):", reply_markup=builder.as_markup())

@dp.callback_query(DiceGameState.waiting_for_players, F.data.startswith("set_players:"))
async def set_players_handler(callback: CallbackQuery, state: FSMContext):
    players = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    data = await state.get_data()
    bet = data.get("bet")
    if not bet:
        await callback.answer("Ошибка: данные устарели", show_alert=True)
        await state.clear()
        return

    # 🔴 ПРОВЕРКА: Максимум 3 активных лобби у одного создателя
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) 
            FROM dice_games 
            WHERE creator_id = ? AND status = 'waiting'
        """, (user_id,)) as cursor:
            active_games_count = (await cursor.fetchone())[0]
            if active_games_count >= 3:
                await callback.answer("❌ Вы не можете создать больше 3 активных лобби одновременно. Завершите или дождитесь начала одной из ваших игр.", show_alert=True)
                await state.clear()
                return

    game_id = generate_game_id()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO dice_games (game_id, creator_id, bet, max_players, created_at) VALUES (?, ?, ?, ?, ?)",
            (game_id, user_id, bet, players, int(time.time()))
        )
        await db.execute(
            "INSERT INTO dice_players (game_id, user_id, turn_order) VALUES (?, ?, ?)",
            (game_id, user_id, 1)
        )
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, user_id))
        await db.commit()
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        f"""✅ Лобби создано!
ID: {game_id}
Ставка: {bet} RUB
Игроков: 1/{players}
Ожидаем других игроков...""",
        reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад к лобби", callback_data="dice_lobby")
            .as_markup()
    )

@dp.callback_query(F.data == "my_dice_games")
async def my_dice_games_handler(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT game_id, bet, max_players, status
            FROM dice_games
            WHERE creator_id = ?
            ORDER BY created_at DESC
        """, (user_id,)) as cursor:
            games = await cursor.fetchall()
    msg = "<b>📋 Ваши лобби</b>\n"
    builder = InlineKeyboardBuilder()
    if not games:
        msg += "У вас нет созданных лобби."
    else:
        for game_id, bet, max_players, status in games:
            status_emoji = "⏳" if status == "waiting" else "🎲" if status == "playing" else "✅"
            builder.button(text=f"{status_emoji} {game_id} ({bet} RUB)", callback_data=f"dice_game_info:{game_id}")
    builder.button(text="🔙 Назад к лобби", callback_data="dice_lobby")
    builder.adjust(*[1] * len(games), 1)
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("dice_game_info:"))
async def dice_game_info_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT dg.bet, dg.max_players, dg.status, dg.creator_id, COUNT(dp.user_id) as current_players
            FROM dice_games dg
            LEFT JOIN dice_players dp ON dg.game_id = dp.game_id
            WHERE dg.game_id = ?
            GROUP BY dg.game_id
        """, (game_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Игра не найдена", show_alert=True)
                return
        bet, max_players, status, creator_id, current_players = row
        async with db.execute("SELECT 1 FROM dice_players WHERE game_id = ? AND user_id = ?", (game_id, user_id)) as cursor:
            is_participant = await cursor.fetchone()
    msg = f"""<b>🎲 Игра {game_id}</b>
💰 Ставка: {bet} RUB
👥 Игроков: {current_players}/{max_players}
🔄 Статус: {'Ожидание' if status == 'waiting' else 'Игра' if status == 'playing' else 'Завершена'}"""
    builder = InlineKeyboardBuilder()
    if not is_participant and status == "waiting" and current_players < max_players:
        builder.button(text="✅ Вступить", callback_data=f"join_dice_game:{game_id}")
    builder.button(text="🔙 Назад", callback_data="dice_lobby")
    await callback.message.delete()
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("join_dice_game:"))
async def join_dice_game_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        # 🔴 ПРОВЕРКА: Участвует ли игрок уже в другой активной игре?
        async with db.execute("""
            SELECT 1
            FROM dice_players dp
            JOIN dice_games dg ON dp.game_id = dg.game_id
            WHERE dp.user_id = ? AND dg.status IN ('waiting', 'playing')
        """, (user_id,)) as cursor:
            already_in_game = await cursor.fetchone()
            if already_in_game:
                await callback.answer("❌ Вы уже участвуете в другой игре. Дождитесь её окончания.", show_alert=True)
                return

        async with db.execute("SELECT bet, max_players, status FROM dice_games WHERE game_id = ?", (game_id,)) as cursor:
            game = await cursor.fetchone()
            if not game or game[2] != "waiting":
                await callback.answer("Игра не найдена или уже началась", show_alert=True)
                return
        bet, max_players, status = game
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < bet:
                await callback.answer("❌ Недостаточно средств", show_alert=True)
                return
        async with db.execute("SELECT 1 FROM dice_players WHERE game_id = ? AND user_id = ?", (game_id, user_id)) as cursor:
            if await cursor.fetchone():
                await callback.answer("Вы уже в игре", show_alert=True)
                return
        async with db.execute("SELECT COUNT(*) FROM dice_players WHERE game_id = ?", (game_id,)) as cursor:
            current_players = (await cursor.fetchone())[0]
        if current_players >= max_players:
            await callback.answer("Лобби заполнено", show_alert=True)
            return

        turn_order = current_players + 1
        await db.execute("INSERT INTO dice_players (game_id, user_id, turn_order) VALUES (?, ?, ?)", (game_id, user_id, turn_order))
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, user_id))
        await db.commit()

        # Уведомляем всех игроков, КРОМЕ САМОГО СЕБЯ
        async with db.execute("SELECT user_id FROM dice_players WHERE game_id = ?", (game_id,)) as cursor:
            all_players = await cursor.fetchall()
        try:
            new_player_name = f"@{(await bot.get_chat(user_id)).username}" if (await bot.get_chat(user_id)).username else f"ID{user_id}"
        except:
            new_player_name = f"ID{user_id}"
        for (pid,) in all_players:
            if pid == user_id:  # ← НЕ отправляем уведомление себе
                continue
            try:
                await bot.send_message(pid, f"👤 Игрок {new_player_name} присоединился к игре {game_id}!")
            except:
                pass

        if current_players + 1 == max_players:
            await db.execute("UPDATE dice_games SET status = 'playing', started_at = ? WHERE game_id = ?", (int(time.time()), game_id))
            await db.commit()
            # Отправляем сообщение с таймером первому игроку
            async with db.execute("""
                SELECT user_id
                FROM dice_players
                WHERE game_id = ?
                ORDER BY turn_order ASC
                LIMIT 1
            """, (game_id,)) as cursor:
                first_player = await cursor.fetchone()
            if first_player:
                first_pid = first_player[0]
                try:
                    sent = await bot.send_message(
                        first_pid,
                        "🎲 Ваш ход! Бросьте кости.\n⏳ Осталось: 5:00",
                        reply_markup=InlineKeyboardBuilder()
                            .button(text="🎲 Бросить кости", callback_data=f"roll_dice:{game_id}")
                            .as_markup()
                    )
                    asyncio.create_task(update_timer_message(bot, first_pid, sent.message_id, game_id, first_pid))
                except Exception as e:
                    print(f"[ERROR] Не удалось отправить сообщение игроку {first_pid}: {e}")
            # Уведомляем всех, что игра началась
            for (pid,) in all_players:
                try:
                    await bot.send_message(pid, f"▶️ Игра {game_id} началась! Игроки бросают кости по очереди.")
                except:
                    pass

        await callback.answer("✅ Вы вступили в игру!", show_alert=True)
        await callback.message.delete()
        await callback.message.answer(
            f"""Вы вступили в игру {game_id}!
Ожидайте начала...""",
            reply_markup=InlineKeyboardBuilder()
                .button(text="🔙 Назад к лобби", callback_data="dice_lobby")
                .as_markup()
        )

# --- ФУНКЦИЯ ОБНОВЛЕНИЯ ТАЙМЕРА ---
async def update_timer_message(bot: Bot, chat_id: int, message_id: int, game_id: str, user_id: int):
    """Обновляет сообщение с таймером каждые 3 секунды."""
    start_time = int(time.time())
    timeout = 300  # 5 минут = 300 секунд
    while True:
        elapsed = int(time.time()) - start_time
        remaining = timeout - elapsed
        if remaining <= 0:
            # Таймер истёк — пропускаем ход
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE dice_players SET dice_value = 0 WHERE game_id = ? AND user_id = ?",
                    (game_id, user_id)
                )
                await db.commit()
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="⏳ Время вышло! Ход пропущен (0 очков)."
                )
            except:
                pass
            # Уведомляем всех игроков
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM dice_players WHERE game_id = ?", (game_id,)) as cursor:
                    players = await cursor.fetchall()
            try:
                username = (await bot.get_chat(user_id)).username
                display_name = f"@{username}" if username else f"ID{user_id}"
            except:
                display_name = f"ID{user_id}"
            for (pid,) in players:
                try:
                    await bot.send_message(
                        pid,
                        f"⏳ Игрок {display_name} не успел сделать ход — ход пропущен (0 очков)."
                    )
                except:
                    pass
            # Проверяем, все ли бросили
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("""
                    SELECT COUNT(*) FROM dice_players WHERE game_id = ? AND dice_value IS NOT NULL
                """, (game_id,)) as cursor:
                    finished_count = (await cursor.fetchone())[0]
                async with db.execute("SELECT max_players FROM dice_games WHERE game_id = ?", (game_id,)) as cursor:
                    max_players = (await cursor.fetchone())[0]
                if finished_count == max_players:
                    # Определяем победителя
                    async with db.execute("""
                        SELECT user_id, dice_value
                        FROM dice_players
                        WHERE game_id = ?
                        ORDER BY dice_value DESC
                        LIMIT 1
                    """, (game_id,)) as cursor:
                        winner = await cursor.fetchone()
                    if winner:
                        winner_id, max_value = winner
                        async with db.execute("SELECT bet FROM dice_games WHERE game_id = ?", (game_id,)) as cursor:
                            row = await cursor.fetchone()
                            if not row:
                                break
                            bet = row[0]
                        total_pot = max_players * bet
                        commission = total_pot * 0.05
                        prize = total_pot - commission
                        await db.execute("UPDATE dice_games SET status = 'finished', winner_id = ? WHERE game_id = ?", (winner_id, game_id))
                        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                        await db.commit()
                        # Формируем список игроков и результатов
                        async with db.execute("""
                            SELECT u.user_id, u.username, dp.dice_value
                            FROM dice_players dp
                            JOIN users u ON dp.user_id = u.user_id
                            WHERE dp.game_id = ?
                            ORDER BY dp.turn_order ASC
                        """, (game_id,)) as cursor:
                            players = await cursor.fetchall()
                        results_text = ""
                        for pid, username, value in players:
                            name = f"@{username}" if username else f"ID{pid}"
                            results_text += f"{name} ({pid}) — {value}\n"
                        # Отправляем итог всем игрокам
                        for pid, _, _ in players:
                            try:
                                if pid == winner_id:
                                    msg = f"""🎉 Игра Dice {game_id} завершена!
Сумма выигрыша: {total_pot:.2f} RUB
{results_text}
🏆 Вы выиграли! На ваш баланс начислено {prize:.2f} RUB (комиссия 5%)."""
                                else:
                                    msg = f"""🎲 Игра Dice {game_id} завершена!
{results_text}
🏆 Победитель: ID{winner_id}"""
                                await bot.send_message(pid, msg)
                            except:
                                pass
            break
        # Форматируем оставшееся время: M:SS (минуты без ведущего нуля, секунды с ведущим нулем)
        mins, secs = divmod(remaining, 60)
        timer_text = f"{mins}:{secs:02d}"
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"🎲 Ваш ход! Бросьте кости.\n⏳ Осталось: {timer_text}",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="🎲 Бросить кости", callback_data=f"roll_dice:{game_id}")
                    .as_markup()
            )
        except Exception as e:
            # Сообщение удалено или редактирование невозможно — выходим
            break
        await asyncio.sleep(3)  # <-- ИЗМЕНЕНО С 5 НА 3 СЕКУНДЫ

# --- БРОСОК КОСТИ ---
@dp.callback_query(F.data.startswith("roll_dice:"))
async def roll_dice_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT dg.status, dp.dice_value, dp.turn_order
            FROM dice_games dg
            JOIN dice_players dp ON dg.game_id = dp.game_id
            WHERE dg.game_id = ? AND dp.user_id = ?
        """, (game_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] != "playing" or row[1] is not None:
                await callback.answer("Нельзя бросить кости", show_alert=True)
                return
        status, dice_value, current_turn_order = row
        # Проверяем, что сейчас ход именно этого игрока
        async with db.execute("""
            SELECT user_id
            FROM dice_players
            WHERE game_id = ? AND dice_value IS NULL
            ORDER BY turn_order ASC
            LIMIT 1
        """, (game_id,)) as cursor:
            next_player = await cursor.fetchone()
            if not next_player or next_player[0] != user_id:
                await callback.answer("Сейчас не ваш ход. Ожидайте своей очереди.", show_alert=True)
                return
        # Генерируем значение 1-6
        dice_value = random.randint(1, 6)
        # Отправляем стикер
        sticker_file_id = DICE_STICKERS.get(dice_value)
        if sticker_file_id:
            await bot.send_sticker(user_id, sticker_file_id)
        # Обновляем БД
        await db.execute(
            "UPDATE dice_players SET dice_value = ?, last_turn_time = ? WHERE game_id = ? AND user_id = ?",
            (dice_value, int(time.time()), game_id, user_id)
        )
        await db.commit()
        # await callback.answer(f"🎲 Вам выпало: {dice_value}", show_alert=True)  # Уведомление отключено
        await callback.message.delete()
        # Проверяем, бросили ли все
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("""
                SELECT COUNT(*) FROM dice_players WHERE game_id = ? AND dice_value IS NOT NULL
            """, (game_id,)) as cursor:
                finished_count = (await cursor.fetchone())[0]
            async with db.execute("SELECT max_players FROM dice_games WHERE game_id = ?", (game_id,)) as cursor:
                max_players = (await cursor.fetchone())[0]
            if finished_count == max_players:
                # Определяем победителя
                async with db.execute("""
                    SELECT user_id, dice_value
                    FROM dice_players
                    WHERE game_id = ?
                    ORDER BY dice_value DESC
                    LIMIT 1
                """, (game_id,)) as cursor:
                    winner = await cursor.fetchone()
                if winner:
                    winner_id, max_value = winner
                    async with db.execute("SELECT bet FROM dice_games WHERE game_id = ?", (game_id,)) as cursor:
                        row = await cursor.fetchone()
                        if not row:
                            return
                        bet = row[0]
                    total_pot = max_players * bet
                    commission = total_pot * 0.05
                    prize = total_pot - commission
                    await db.execute("UPDATE dice_games SET status = 'finished', winner_id = ? WHERE game_id = ?", (winner_id, game_id))
                    await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize, winner_id))
                    await db.commit()
                    # Формируем список игроков и результатов
                    async with db.execute("""
                        SELECT u.user_id, u.username, dp.dice_value
                        FROM dice_players dp
                        JOIN users u ON dp.user_id = u.user_id
                        WHERE dp.game_id = ?
                        ORDER BY dp.turn_order ASC
                    """, (game_id,)) as cursor:
                        players = await cursor.fetchall()
                    results_text = ""
                    for pid, username, value in players:
                        name = f"@{username}" if username else f"ID{pid}"
                        results_text += f"{name} ({pid}) — {value}\n"
                    # Отправляем итог всем игрокам
                    for pid, _, _ in players:
                        try:
                            if pid == winner_id:
                                msg = f"""🎉 Игра Dice {game_id} завершена!
Сумма выигрыша: {total_pot:.2f} RUB
{results_text}
🏆 Вы выиграли! На ваш баланс начислено {prize:.2f} RUB (комиссия 5%)."""
                            else:
                                msg = f"""🎲 Игра Dice {game_id} завершена!
{results_text}
🏆 Победитель: ID{winner_id}"""
                            await bot.send_message(pid, msg)
                        except:
                            pass
            else:
                # Переходим к следующему игроку
                async with db.execute("""
                    SELECT user_id
                    FROM dice_players
                    WHERE game_id = ? AND dice_value IS NULL
                    ORDER BY turn_order ASC
                    LIMIT 1
                """, (game_id,)) as cursor:
                    next_player = await cursor.fetchone()
                    if next_player:
                        next_pid = next_player[0]
                        try:
                            sent = await bot.send_message(
                                next_pid,
                                "🎲 Ваш ход! Бросьте кости.\n⏳ Осталось: 5:00",
                                reply_markup=InlineKeyboardBuilder()
                                    .button(text="🎲 Бросить кости", callback_data=f"roll_dice:{game_id}")
                                    .as_markup()
                            )
                            asyncio.create_task(update_timer_message(bot, next_pid, sent.message_id, game_id, next_pid))
                        except Exception as e:
                            print(f"[ERROR] Не удалось отправить сообщение игроку {next_pid}: {e}")

@dp.callback_query(F.data == "back_to_games")
async def back_to_games_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "🕹️ Доступные игры:",
        reply_markup=get_games_keyboard()
    )

# --- ИГРА 21 (Blackjack) ---
@dp.message(lambda msg: msg.text == "🃏 21")
async def start_blackjack_game(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT bg.game_id, bg.bet, bg.max_players, COUNT(bp.user_id) as current_players
            FROM blackjack_games bg
            LEFT JOIN blackjack_players bp ON bg.game_id = bp.game_id
            WHERE bg.status = 'waiting'
            GROUP BY bg.game_id
            HAVING current_players < bg.max_players
            ORDER BY bg.created_at DESC
        """) as cursor:
            games = await cursor.fetchall()
    msg = "<b>🃏 Лобби игры \"21\"</b>\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать игру", callback_data="create_blackjack_game")
    if games:
        msg += "Доступные лобби:\n"
        for game_id, bet, max_players, current_players in games:
            builder.button(text=f"{game_id} ({current_players}/{max_players}) {bet:.0f} RUB", callback_data=f"bj_game_info:{game_id}")
    else:
        msg += "Нет доступных лобби. Создайте своё!\n"
    builder.button(text="📋 Мои лобби", callback_data="my_blackjack_games")
    builder.button(text="🔙 Назад", callback_data="back_to_games")
    builder.adjust(1, *[1] * len(games), 1, 1)
    await message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "create_blackjack_game")
async def create_blackjack_game_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BlackjackGameState.waiting_for_bet)
    await callback.message.delete()
    msg = "Введите ставку на игрока (минимум 20 RUB):"
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="cancel_bj_creation")
    await callback.message.answer(msg, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "cancel_bj_creation")
async def cancel_bj_creation(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Создание игры отменено.", reply_markup=InlineKeyboardBuilder()
        .button(text="🃏 Вернуться к лобби", callback_data="back_to_bj_lobby")
        .as_markup()
    )

@dp.message(BlackjackGameState.waiting_for_bet)
async def handle_bj_bet_amount(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) < 20:
        await message.answer("❌ Введите корректную сумму (минимум 20 RUB):")
        return
    bet = int(message.text)
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < bet:
                await message.answer("❌ Недостаточно средств.")
                return
    await state.update_data(bet=bet)
    await state.set_state(BlackjackGameState.waiting_for_players)
    builder = InlineKeyboardBuilder()
    for i in range(2, 6):
        builder.button(text=f"{i} игроков", callback_data=f"bj_set_players:{i}")
    builder.button(text="❌ Отменить", callback_data="cancel_bj_creation")
    builder.adjust(4, 1)
    await message.answer(f"Выберите количество игроков (минимум 2):", reply_markup=builder.as_markup())

@dp.callback_query(BlackjackGameState.waiting_for_players, F.data.startswith("bj_set_players:"))
async def bj_set_players_handler(callback: CallbackQuery, state: FSMContext):
    players = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    data = await state.get_data()
    bet = data.get("bet")
    if not bet:
        await callback.answer("Ошибка: данные устарели", show_alert=True)
        await state.clear()
        return

    game_id = generate_game_id()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO blackjack_games (game_id, creator_id, bet, max_players, created_at) VALUES (?, ?, ?, ?, ?)",
            (game_id, user_id, bet, players, int(time.time()))
        )
        # Создаем руку для создателя (2 карты)
        hand = [deal_card(), deal_card()]
        score = calculate_score(hand)
        await db.execute(
            "INSERT INTO blackjack_players (game_id, user_id, hand, score, turn_order) VALUES (?, ?, ?, ?, ?)",
            (game_id, user_id, json.dumps(hand), score, 1)
        )
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, user_id))
        await db.commit()
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        f"""✅ Лобби создано!
ID: {game_id}
Ставка: {bet} RUB
Игроков: 1/{players}
Ожидаем других игроков...""",
        reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад к лобби", callback_data="back_to_bj_lobby")
            .as_markup()
    )

@dp.callback_query(F.data == "my_blackjack_games")
async def my_blackjack_games_handler(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT game_id, bet, max_players, status
            FROM blackjack_games
            WHERE creator_id = ?
            ORDER BY created_at DESC
        """, (user_id,)) as cursor:
            games = await cursor.fetchall()
    msg = "<b>📋 Ваши лобби (21)</b>\n"
    builder = InlineKeyboardBuilder()
    if not games:
        msg += "У вас нет созданных лобби."
    else:
        for game_id, bet, max_players, status in games:
            status_emoji = "⏳" if status == "waiting" else "🃏" if status == "playing" else "✅"
            builder.button(text=f"{status_emoji} {game_id} ({bet} RUB)", callback_data=f"bj_game_info:{game_id}")
    builder.button(text="🔙 Назад к лобби", callback_data="back_to_bj_lobby")
    builder.adjust(*[1] * len(games), 1)
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_bj_lobby")
async def back_to_bj_lobby_handler(callback: CallbackQuery):
    await start_blackjack_game(callback.message)

@dp.callback_query(F.data.startswith("bj_game_info:"))
async def bj_game_info_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT bg.bet, bg.max_players, bg.status, bg.creator_id, COUNT(bp.user_id) as current_players
            FROM blackjack_games bg
            LEFT JOIN blackjack_players bp ON bg.game_id = bp.game_id
            WHERE bg.game_id = ?
            GROUP BY bg.game_id
        """, (game_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Игра не найдена", show_alert=True)
                return
        bet, max_players, status, creator_id, current_players = row
        async with db.execute("SELECT 1 FROM blackjack_players WHERE game_id = ? AND user_id = ?", (game_id, user_id)) as cursor:
            is_participant = await cursor.fetchone()
    msg = f"""<b>🃏 Игра 21 {game_id}</b>
💰 Ставка: {bet} RUB
👥 Игроков: {current_players}/{max_players}
🔄 Статус: {'Ожидание' if status == 'waiting' else 'Игра' if status == 'playing' else 'Завершена'}"""
    builder = InlineKeyboardBuilder()
    if not is_participant and status == "waiting" and current_players < max_players:
        builder.button(text="✅ Вступить", callback_data=f"join_blackjack_game:{game_id}")
    builder.button(text="🔙 Назад", callback_data="back_to_bj_lobby")
    await callback.message.delete()
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("join_blackjack_game:"))
async def join_blackjack_game_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT bet, max_players, status FROM blackjack_games WHERE game_id = ?", (game_id,)) as cursor:
            game = await cursor.fetchone()
            if not game or game[2] != "waiting":
                await callback.answer("Игра не найдена или уже началась", show_alert=True)
                return
        bet, max_players, status = game
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] < bet:
                await callback.answer("❌ Недостаточно средств", show_alert=True)
                return
        async with db.execute("SELECT 1 FROM blackjack_players WHERE game_id = ? AND user_id = ?", (game_id, user_id)) as cursor:
            if await cursor.fetchone():
                await callback.answer("Вы уже в игре", show_alert=True)
                return
        async with db.execute("SELECT COUNT(*) FROM blackjack_players WHERE game_id = ?", (game_id,)) as cursor:
            current_players = (await cursor.fetchone())[0]
        if current_players >= max_players:
            await callback.answer("Лобби заполнено", show_alert=True)
            return

        # Создаем руку для нового игрока
        hand = [deal_card(), deal_card()]
        score = calculate_score(hand)
        turn_order = current_players + 1

        await db.execute(
            "INSERT INTO blackjack_players (game_id, user_id, hand, score, turn_order) VALUES (?, ?, ?, ?, ?)",
            (game_id, user_id, json.dumps(hand), score, turn_order)
        )
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (bet, user_id))
        await db.commit()

        # Уведомляем всех игроков, КРОМЕ САМОГО СЕБЯ
        async with db.execute("SELECT user_id FROM blackjack_players WHERE game_id = ?", (game_id,)) as cursor:
            all_players = await cursor.fetchall()
        try:
            new_player_name = f"@{(await bot.get_chat(user_id)).username}" if (await bot.get_chat(user_id)).username else f"ID{user_id}"
        except:
            new_player_name = f"ID{user_id}"
        for (pid,) in all_players:
            if pid == user_id:
                continue
            try:
                await bot.send_message(pid, f"👤 Игрок {new_player_name} присоединился к игре 21 {game_id}!")
            except:
                pass

        if current_players + 1 == max_players:
            await db.execute("UPDATE blackjack_games SET status = 'playing', started_at = ? WHERE game_id = ?", (int(time.time()), game_id))
            await db.commit()
            # Отправляем сообщение с таймером первому игроку
            async with db.execute("""
                SELECT user_id
                FROM blackjack_players
                WHERE game_id = ?
                ORDER BY turn_order ASC
                LIMIT 1
            """, (game_id,)) as cursor:
                first_player = await cursor.fetchone()
            if first_player:
                first_pid = first_player[0]
                try:
                    # Получаем руку первого игрока
                    async with db.execute(
                        "SELECT hand FROM blackjack_players WHERE game_id = ? AND user_id = ?",
                        (game_id, first_pid)
                    ) as cursor:
                        row = await cursor.fetchone()
                        hand = json.loads(row[0]) if row else []

                    sent = await bot.send_message(
                        first_pid,
                        f"""🃏 Ваш ход в игре 21!
Ваши карты: {hand_to_str(hand)}
Сумма: {calculate_score(hand)}
⏳ Осталось: 5:00""",
                        reply_markup=InlineKeyboardBuilder()
                            .button(text="🃏 Взять карту", callback_data=f"bj_hit:{game_id}")
                            .button(text="✋ Пас", callback_data=f"bj_stand:{game_id}")
                            .as_markup()
                    )
                    asyncio.create_task(update_blackjack_timer_message(bot, first_pid, sent.message_id, game_id, first_pid))
                except Exception as e:
                    print(f"[ERROR] Не удалось отправить сообщение игроку {first_pid} в игре 21: {e}")
            # Уведомляем всех, что игра началась
            for (pid,) in all_players:
                try:
                    await bot.send_message(pid, f"▶️ Игра 21 {game_id} началась! Игроки ходят по очереди.")
                except:
                    pass

        await callback.answer("✅ Вы вступили в игру!", show_alert=True)
        await callback.message.delete()
        await callback.message.answer(
            f"""Вы вступили в игру 21 {game_id}!
Ожидайте начала...""",
            reply_markup=InlineKeyboardBuilder()
                .button(text="🔙 Назад к лобби", callback_data="back_to_bj_lobby")
                .as_markup()
        )

# --- ФУНКЦИЯ ОБНОВЛЕНИЯ ТАЙМЕРА ДЛЯ ИГРЫ 21 ---
async def update_blackjack_timer_message(bot: Bot, chat_id: int, message_id: int, game_id: str, user_id: int):
    """Обновляет сообщение с таймером каждые 3 секунды для игры 21."""
    start_time = int(time.time())
    timeout = 300  # 5 минут = 300 секунд
    while True:
        elapsed = int(time.time()) - start_time
        remaining = timeout - elapsed
        if remaining <= 0:
            # Таймер истёк — игрок автоматически пасует
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE blackjack_players SET is_standing = 1 WHERE game_id = ? AND user_id = ?",
                    (game_id, user_id)
                )
                await db.commit()
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="⏳ Время вышло! Вы автоматически пасуете."
                )
            except:
                pass
            # Уведомляем всех игроков
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id FROM blackjack_players WHERE game_id = ?", (game_id,)) as cursor:
                    players = await cursor.fetchall()
            try:
                username = (await bot.get_chat(user_id)).username
                display_name = f"@{username}" if username else f"ID{user_id}"
            except:
                display_name = f"ID{user_id}"
            for (pid,) in players:
                try:
                    await bot.send_message(
                        pid,
                        f"⏳ Игрок {display_name} не успел сделать ход — пасует автоматически."
                    )
                except:
                    pass
            # Проверяем, все ли пасанули
            await check_blackjack_game_end(game_id, bot)
            break

        # Форматируем оставшееся время: M:SS
        mins, secs = divmod(remaining, 60)
        timer_text = f"{mins}:{secs:02d}"
        try:
            # Получаем текущую руку игрока для отображения
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT hand, score FROM blackjack_players WHERE game_id = ? AND user_id = ?",
                    (game_id, user_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        break
                    hand_json, score = row
                    hand = json.loads(hand_json)

            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"""🃏 Ваш ход в игре 21!
Ваши карты: {hand_to_str(hand)}
Сумма: {score}
⏳ Осталось: {timer_text}""",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="🃏 Взять карту", callback_data=f"bj_hit:{game_id}")
                    .button(text="✋ Пас", callback_data=f"bj_stand:{game_id}")
                    .as_markup()
            )
        except Exception as e:
            break
        await asyncio.sleep(3)

async def check_blackjack_game_end(game_id: str, bot: Bot):
    """Проверяет, закончилась ли игра 21 (все пасанули), и определяет победителя."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем всех игроков и их очки
        async with db.execute("""
            SELECT user_id, hand, score
            FROM blackjack_players
            WHERE game_id = ?
            ORDER BY turn_order ASC
        """, (game_id,)) as cursor:
            players = await cursor.fetchall()

        if not players:
            return

        # Проверяем, пасанули ли все
        all_standing = True
        for user_id, hand_json, score in players:
            async with db.execute(
                "SELECT is_standing FROM blackjack_players WHERE game_id = ? AND user_id = ?",
                (game_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                if not row or not row[0]:
                    all_standing = False
                    break

        if not all_standing:
            # Не все пасанули, игра продолжается
            # Находим следующего игрока, который еще не пасанул
            next_player_id = None
            for user_id, _, _ in players:
                async with db.execute(
                    "SELECT is_standing FROM blackjack_players WHERE game_id = ? AND user_id = ?",
                    (game_id, user_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row and not row[0]:  # Игрок еще не пасанул
                        next_player_id = user_id
                        break

            if next_player_id:
                try:
                    # Получаем руку следующего игрока
                    async with db.execute(
                        "SELECT hand FROM blackjack_players WHERE game_id = ? AND user_id = ?",
                        (game_id, next_player_id)
                    ) as cursor:
                        row = await cursor.fetchone()
                        hand = json.loads(row[0]) if row else []

                    sent = await bot.send_message(
                        next_player_id,
                        f"""🃏 Ваш ход в игре 21!
Ваши карты: {hand_to_str(hand)}
Сумма: {calculate_score(hand)}
⏳ Осталось: 5:00""",
                        reply_markup=InlineKeyboardBuilder()
                            .button(text="🃏 Взять карту", callback_data=f"bj_hit:{game_id}")
                            .button(text="✋ Пас", callback_data=f"bj_stand:{game_id}")
                            .as_markup()
                    )
                    asyncio.create_task(update_blackjack_timer_message(bot, next_player_id, sent.message_id, game_id, next_player_id))
                except Exception as e:
                    print(f"[ERROR] Не удалось отправить сообщение игроку {next_player_id} в игре 21: {e}")
            return

        # Все пасанули, определяем победителя
        # Банк (дилер) набирает карты до 17
        bank_hand = []
        bank_score = 0
        while bank_score < 17:
            card = deal_card()
            bank_hand.append(card)
            bank_score = calculate_score(bank_hand)

        # Сравниваем результаты игроков с банком
        winners = []
        for user_id, hand_json, player_score in players:
            hand = json.loads(hand_json)
            # Игрок проигрывает, если перебор
            if player_score > 21:
                continue
            # Банк проигрывает, если у него перебор
            if bank_score > 21:
                winners.append((user_id, hand, player_score))
            # Если никто не перебрал, побеждает тот, у кого больше очков
            elif player_score > bank_score:
                winners.append((user_id, hand, player_score))

        # Обновляем статус игры
        await db.execute(
            "UPDATE blackjack_games SET status = 'finished', started_at = ? WHERE game_id = ?",
            (int(time.time()), game_id)
        )

        # Начисляем выигрыш, если есть победители
        if winners:
            # Получаем ставку и количество игроков
            async with db.execute("SELECT bet, max_players FROM blackjack_games WHERE game_id = ?", (game_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return
                bet, max_players = row

            total_pot = max_players * bet
            commission = total_pot * 0.05
            prize_per_winner = (total_pot - commission) / len(winners)

            for winner_id, _, _ in winners:
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (prize_per_winner, winner_id))

        await db.commit()

        # Формируем сообщение с результатами
        results_text = f"🏦 Банк: {hand_to_str(bank_hand)} (Сумма: {bank_score})\n\n"
        for user_id, hand_json, player_score in players:
            hand = json.loads(hand_json)
            name = f"ID{user_id}"
            try:
                user = await bot.get_chat(user_id)
                name = f"@{user.username}" if user.username else f"ID{user_id}"
            except:
                pass
            results_text += f"{name}: {hand_to_str(hand)} (Сумма: {player_score})\n"

        # Отправляем итог всем игрокам
        for user_id, _, _ in players:
            is_winner = any(winner_id == user_id for winner_id, _, _ in winners)
            try:
                if is_winner:
                    msg = f"""🎉 Игра 21 {game_id} завершена!
{results_text}
🏆 Вы выиграли! На ваш баланс начислено {prize_per_winner:.2f} RUB (комиссия 5%)."""
                else:
                    msg = f"""🎲 Игра 21 {game_id} завершена!
{results_text}
😞 Вы проиграли. Победил банк."""
                await bot.send_message(user_id, msg)
            except:
                pass

# --- ХОДЫ ИГРОКА В 21 ---
@dp.callback_query(F.data.startswith("bj_hit:"))
async def bj_hit_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем статус игры и игрока
        async with db.execute("""
            SELECT bg.status, bp.is_standing, bp.hand
            FROM blackjack_games bg
            JOIN blackjack_players bp ON bg.game_id = bp.game_id
            WHERE bg.game_id = ? AND bp.user_id = ?
        """, (game_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] != "playing" or row[1]:
                await callback.answer("Нельзя взять карту", show_alert=True)
                return
        status, is_standing, hand_json = row
        hand = json.loads(hand_json)

        # Проверяем, что сейчас ход именно этого игрока
        async with db.execute("""
            SELECT bp.user_id
            FROM blackjack_players bp
            WHERE bp.game_id = ? AND bp.is_standing = 0
            ORDER BY bp.turn_order ASC
            LIMIT 1
        """, (game_id,)) as cursor:
            next_player = await cursor.fetchone()
            if not next_player or next_player[0] != user_id:
                await callback.answer("Сейчас не ваш ход. Ожидайте своей очереди.", show_alert=True)
                return

        # Выдаем новую карту
        new_card = deal_card()
        hand.append(new_card)
        new_score = calculate_score(hand)

        # Обновляем руку и счет в БД
        await db.execute(
            "UPDATE blackjack_players SET hand = ?, score = ? WHERE game_id = ? AND user_id = ?",
            (json.dumps(hand), new_score, game_id, user_id)
        )
        await db.commit()

        await callback.message.delete()

        # Если перебор, игрок автоматически пасует
        if new_score > 21:
            await db.execute(
                "UPDATE blackjack_players SET is_standing = 1 WHERE game_id = ? AND user_id = ?",
                (game_id, user_id)
            )
            await db.commit()
            await callback.message.answer(f"😞 Перебор! Ваши карты: {hand_to_str(hand)} (Сумма: {new_score}). Вы пасуете.")
            # Проверяем, закончилась ли игра
            await check_blackjack_game_end(game_id, bot)
            return

        # Отправляем новое сообщение с обновленной рукой и таймером
        sent = await callback.message.answer(
            f"""🃏 Ваш ход в игре 21!
Ваши карты: {hand_to_str(hand)}
Сумма: {new_score}
⏳ Осталось: 5:00""",
            reply_markup=InlineKeyboardBuilder()
                .button(text="🃏 Взять карту", callback_data=f"bj_hit:{game_id}")
                .button(text="✋ Пас", callback_data=f"bj_stand:{game_id}")
                .as_markup()
        )
        asyncio.create_task(update_blackjack_timer_message(bot, user_id, sent.message_id, game_id, user_id))

@dp.callback_query(F.data.startswith("bj_stand:"))
async def bj_stand_handler(callback: CallbackQuery):
    game_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем статус игры
        async with db.execute("""
            SELECT bg.status
            FROM blackjack_games bg
            JOIN blackjack_players bp ON bg.game_id = bp.game_id
            WHERE bg.game_id = ? AND bp.user_id = ?
        """, (game_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] != "playing":
                await callback.answer("Нельзя пасовать", show_alert=True)
                return

        # Устанавливаем флаг is_standing
        await db.execute(
            "UPDATE blackjack_players SET is_standing = 1 WHERE game_id = ? AND user_id = ?",
            (game_id, user_id)
        )
        await db.commit()

    await callback.message.delete()
    await callback.message.answer("✋ Вы пасуете.")

    # Проверяем, закончилась ли игра
    await check_blackjack_game_end(game_id, bot)

# --- СИСТЕМА ВЫВОДА СРЕДСТВ ---
@dp.callback_query(F.data == "withdraw")
async def withdraw_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_data = await get_user(user_id)
    if not user_data:
        await callback.answer("Ошибка: пользователь не найден", show_alert=True)
        return

    # ✅ Минимальная сумма вывода 300 RUB
    if user_data['balance'] < 300:
        await callback.message.delete()
        await callback.message.answer(
            "❌ Минимальная сумма для вывода — 300 RUB.",
            reply_markup=get_back_to_profile_kb()
        )
        return

    await state.set_state(WithdrawState.waiting_for_amount)
    await callback.message.delete()
    msg = f"📤 Введите сумму для вывода (доступно: {user_data['balance']:.2f} RUB):"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отменить", callback_data="back_to_profile")
    await callback.message.answer(msg, reply_markup=builder.as_markup())

@dp.message(WithdrawState.waiting_for_amount)
async def handle_withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        user_data = await get_user(message.from_user.id)

        if amount < 300:
            raise ValueError("Слишком маленькая сумма")
        if amount > user_data['balance']:
            raise ValueError("Недостаточно средств")

        await state.update_data(withdraw_amount=amount)
        await state.set_state(WithdrawState.waiting_for_method)

        builder = InlineKeyboardBuilder()
        builder.button(text="🤖 CryptoBot", callback_data="method:crypto")
        builder.button(text="💳 Карта", callback_data="method:card")
        builder.button(text="🏦 СПБ", callback_data="method:spb")
        builder.button(text="🔙 Отменить", callback_data="back_to_profile")
        builder.adjust(1, 1, 1, 1)

        await message.answer(
            f"""✅ Сумма: {amount:.2f} RUB
Выберите способ вывода:""",
            reply_markup=builder.as_markup()
        )

    except (ValueError, TypeError):
        await message.answer(
            "❌ Пожалуйста, введите корректную сумму (минимум 300 RUB, например, 500.00)."
        )

@dp.callback_query(WithdrawState.waiting_for_method, F.data.startswith("method:"))
async def handle_withdraw_method(callback: CallbackQuery, state: FSMContext):
    method_map = {
        "method:crypto": ("CryptoBot", "🤖"),
        "method:card": ("Карта", "💳"),
        "method:spb": ("СПБ", "🏦")
    }

    method_key = callback.data
    if method_key not in method_map:
        await callback.answer("Неверный метод", show_alert=True)
        return

    method_name, emoji = method_map[method_key]

    data = await state.get_data()
    amount = data.get("withdraw_amount")
    if not amount:
        await callback.answer("Ошибка: данные устарели", show_alert=True)
        await state.clear()
        return

    # Рассчитываем комиссию и итоговую сумму
    fee = amount * 0.05
    final_amount = amount - fee

    await state.update_data(withdraw_method=method_name, withdraw_fee=fee, withdraw_final=final_amount)

    # Если метод требует деталей, переходим к их вводу
    if method_name in ["Карта", "СПБ"]:
        await state.set_state(WithdrawState.waiting_for_details)
        detail_prompt = "Введите номер карты (16 цифр):" if method_name == "Карта" else "Введите номер телефона в формате +7XXXXXXXXXX:"
        await callback.message.delete()
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Отменить", callback_data="back_to_profile")
        await callback.message.answer(detail_prompt, reply_markup=builder.as_markup())
    else:
        # Для CryptoBot сразу переходим к подтверждению
        await state.set_state(WithdrawState.waiting_for_confirmation)
        await show_withdraw_confirmation(callback.message, state)

async def show_withdraw_confirmation(message_or_callback, state: FSMContext):
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    method = data.get("withdraw_method")
    fee = data.get("withdraw_fee")
    final_amount = data.get("withdraw_final")
    details = data.get("withdraw_details", "")

    if not all([amount, method, fee, final_amount]):
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("Ошибка: данные устарели", show_alert=True)
        else:
            await message_or_callback.answer("Ошибка: данные устарели.")
        await state.clear()
        return

    msg = f"""📋 <b>Заказ выплаты</b>
💰 Сумма для вывода: {amount:.2f} RUB
💳 Метод выплаты: {method}"""
    if details:
        msg += f"\n🔢 Реквизиты: {details}"
    msg += f"""\n⚠️ Комиссия 5%: {fee:.2f} RUB
✅ Сумма к выплате: {final_amount:.2f} RUB
Подтвердите создание заявки:"""

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отправить заявку", callback_data="confirm_withdraw:yes")
    builder.button(text="❌ Нет, отменить", callback_data="confirm_withdraw:no")
    builder.adjust(1, 1)

    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.delete()
        await message_or_callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message_or_callback.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.message(WithdrawState.waiting_for_details)
async def handle_withdraw_details(message: Message, state: FSMContext):
    data = await state.get_data()
    method = data.get("withdraw_method")
    if not method:
        await message.answer("Ошибка: данные устарели.", reply_markup=get_back_to_profile_kb())
        await state.clear()
        return

    details = message.text.strip()

    # Валидация (упрощенная)
    if method == "Карта" and (not details.isdigit() or len(details) != 16):
        await message.answer("❌ Неверный формат номера карты. Введите 16 цифр.")
        return
    elif method == "СПБ" and not (details.startswith('+7') and details[1:].isdigit() and len(details) == 12):
        await message.answer("❌ Неверный формат номера телефона. Введите в формате +7XXXXXXXXXX.")
        return

    await state.update_data(withdraw_details=details)
    await state.set_state(WithdrawState.waiting_for_confirmation)
    await show_withdraw_confirmation(message, state)

@dp.callback_query(WithdrawState.waiting_for_confirmation, F.data.startswith("confirm_withdraw:"))
async def handle_withdraw_confirmation(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    user_id = callback.from_user.id

    if choice == "no":
        await state.clear()
        await callback.message.delete()
        await callback.message.answer("❌ Заявка на вывод отменена.", reply_markup=get_back_to_profile_kb())
        return

    # Получаем данные из FSM
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    method = data.get("withdraw_method")
    fee = data.get("withdraw_fee")
    final_amount = data.get("withdraw_final")
    details = data.get("withdraw_details", "")

    if not all([amount, method, fee, final_amount]):
        await callback.answer("Ошибка: данные устарели", show_alert=True)
        await state.clear()
        return

    # Создаем заявку в БД
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO withdraw_requests (user_id, amount, method, details, fee, final_amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, amount, method, details, fee, final_amount, int(time.time()))
        )
        request_id = cursor.lastrowid  # ✅ Исправлено: lastrowid у курсора
        # Снимаем сумму с баланса пользователя
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

    await state.clear()

    # Формируем сообщение для админа
    try:
        user = await bot.get_chat(user_id)
        username = f"@{user.username}" if user.username else f"ID{user_id}"
        full_name = user.full_name
    except:
        username = f"ID{user_id}"
        full_name = "Неизвестно"

    admin_msg = f"""🆕 <b>Новая заявка на вывод #{request_id}</b>
👤 Пользователь: {full_name} ({username})
🆔 ID: {user_id}
💰 Сумма: {amount:.2f} RUB
💳 Метод: {method}"""
    if details:
        admin_msg += f"\n🔢 Реквизиты: {details}"
    admin_msg += f"""\n⚠️ Комиссия: {fee:.2f} RUB
✅ К выплате: {final_amount:.2f} RUB
⏰ Создана: {datetime.fromtimestamp(int(time.time())).strftime('%d.%m.%Y %H:%M:%S')}"""

    admin_builder = InlineKeyboardBuilder()
    admin_builder.button(text="✅ Выплачено", callback_data=f"admin_approve:{request_id}")
    admin_builder.button(text="❌ Отказ", callback_data=f"admin_reject:{request_id}")
    admin_builder.adjust(1, 1)

    # Отправляем заявку администратору
    try:
        await bot.send_message(
            ADMIN_ID,
            admin_msg,
            reply_markup=admin_builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[ERROR] Не удалось отправить заявку админу: {e}")
        # Возвращаем деньги на баланс, если админу не удалось отправить
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            await db.execute("DELETE FROM withdraw_requests WHERE id = ?", (request_id,))
            await db.commit()
        await callback.message.delete()
        await callback.message.answer(
            "❌ Произошла ошибка при создании заявки. Средства возвращены на баланс.",
            reply_markup=get_back_to_profile_kb()
        )
        return

    # Сообщаем пользователю, что заявка отправлена
    await callback.message.delete()
    user_msg = f"""✅ Заявка на вывод #{request_id} успешно отправлена!
💰 Сумма к выплате: {final_amount:.2f} RUB
⏳ Ожидайте подтверждения от администратора. Вы получите уведомление."""
    await callback.message.answer(user_msg, reply_markup=get_back_to_profile_kb())

# --- ХЕНДЛЕРЫ ДЛЯ АДМИНИСТРАТОРА ---
@dp.callback_query(F.data.startswith("admin_approve:"))
async def admin_approve_withdraw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Это только для администратора!", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем данные заявки
        async with db.execute(
            "SELECT user_id, amount, method, final_amount, details FROM withdraw_requests WHERE id = ? AND status = 'pending'",
            (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Заявка не найдена или уже обработана.", show_alert=True)
                return

        user_id, amount, method, final_amount, details = row

        if method == "CryptoBot":
            # Для CryptoBot переводим в особый статус и запрашиваем ссылку на чек
            await db.execute(
                "UPDATE withdraw_requests SET status = 'crypto_link_required', processed_at = ?, processed_by = ? WHERE id = ?",
                (int(time.time()), ADMIN_ID, request_id)
            )
            await db.commit()
            await callback.message.edit_text(
                callback.message.text + "\n\n⚠️ <b>Требуется ссылка на чек CryptoBot.</b>",
                parse_mode="HTML"
            )
            await callback.message.answer(
                f"🔗 Введите ссылку на чек CryptoBot для заявки #{request_id}:",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="❌ Отменить", callback_data=f"admin_reject:{request_id}")
                    .as_markup()
            )
            # Сохраняем ID заявки в состоянии администратора
            state = dp.fsm.get_context(bot=bot, user_id=ADMIN_ID, chat_id=ADMIN_ID)
            await state.set_state(AdminState.waiting_for_crypto_check)
            await state.update_data(crypto_request_id=request_id)
        else:
            # Для других методов сразу одобряем
            await db.execute(
                "UPDATE withdraw_requests SET status = 'approved', processed_at = ?, processed_by = ? WHERE id = ?",
                (int(time.time()), ADMIN_ID, request_id)
            )
            await db.commit()

            # Уведомляем пользователя
            try:
                await bot.send_message(
                    user_id,
                    f"""✅ Ваша заявка на вывод #{request_id} ОДОБРЕНА!
💰 Сумма: {final_amount:.2f} RUB
💳 Метод: {method}"""
                    + (f"\n🔢 Реквизиты: {details}" if details else "") +
                    "\nСпасибо за использование нашего сервиса!",
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[ERROR] Не удалось уведомить пользователя {user_id}: {e}")

            # Уведомляем админа
            await callback.message.edit_text(
                callback.message.text + "\n\n<b>✅ Заявка одобрена.</b>",
                parse_mode="HTML"
            )
            await callback.answer("Заявка одобрена", show_alert=True)

@dp.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject_withdraw(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Это только для администратора!", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем данные заявки и возвращаем средства
        async with db.execute(
            "SELECT user_id, amount FROM withdraw_requests WHERE id = ? AND status = 'pending'",
            (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Заявка не найдена или уже обработана.", show_alert=True)
                return

        user_id, amount = row

        # Обновляем статус заявки
        await db.execute(
            "UPDATE withdraw_requests SET status = 'rejected', processed_at = ?, processed_by = ? WHERE id = ?",
            (int(time.time()), ADMIN_ID, request_id)
        )
        # Возвращаем средства на баланс пользователя
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"""❌ Ваша заявка на вывод #{request_id} ОТКЛОНЕНА.
💰 Сумма {amount:.2f} RUB возвращена на ваш баланс.
Пожалуйста, свяжитесь с поддержкой для уточнения причины.""",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[ERROR] Не удалось уведомить пользователя {user_id}: {e}")

    # Уведомляем админа
    await callback.message.edit_text(
        callback.message.text + "\n\n<b>❌ Заявка отклонена.</b>",
        parse_mode="HTML"
    )
    await callback.answer("Заявка отклонена", show_alert=True)

@dp.message(lambda msg: msg.from_user.id == ADMIN_ID)
async def handle_admin_crypto_check(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "AdminState:waiting_for_crypto_check":
        return  # Игнорируем, если не в нужном состоянии

    data = await state.get_data()
    request_id = data.get("crypto_request_id")
    if not request_id:
        await message.answer("Ошибка: не найдена заявка для обработки.")
        await state.clear()
        return

    crypto_check_url = message.text.strip()
    if not crypto_check_url.startswith("http"):
        await message.answer("❌ Пожалуйста, введите корректную ссылку, начинающуюся с http:// или https://")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # Обновляем заявку
        await db.execute(
            "UPDATE withdraw_requests SET status = 'approved', crypto_check_url = ?, processed_at = ? WHERE id = ?",
            (crypto_check_url, int(time.time()), request_id)
        )
        # Получаем ID пользователя для уведомления
        async with db.execute("SELECT user_id FROM withdraw_requests WHERE id = ?", (request_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await message.answer("Ошибка: заявка не найдена.")
                return
            user_id = row[0]

        await db.commit()

    await state.clear()

    # Уведомляем пользователя с кнопкой
    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="💸 Получить CryptoBot чек", url=crypto_check_url)
        await bot.send_message(
            user_id,
            f"""✅ Ваша заявка на вывод #{request_id} ОДОБРЕНА!
💰 Сумма: {final_amount:.2f} RUB
💳 Метод: CryptoBot

Нажмите кнопку ниже, чтобы получить ваш чек:""",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[ERROR] Не удалось уведомить пользователя {user_id}: {e}")

    # Уведомляем админа
    await message.answer(f"✅ Ссылка на чек для заявки #{request_id} сохранена. Пользователь уведомлен.")

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    args = message.text.split()
    ref_code = None
    check_code = None
    if len(args) > 1:
        code = args[1].strip()
        if code.startswith("SI"):
            check_code = code
        else:
            ref_code = code
    user_data = await get_user(user.id)
    if user_data and user_data.get("agreed_policy") == 1:
        pass
    else:
        await add_user(user.id, user.username, ref_code, 0)
        await show_policy(message)
        return
    if check_code:
        async with aiosqlite.connect(DB_PATH) as db:
            # Сначала проверяем, существует ли чек и активен ли он
            async with db.execute(
                "SELECT id, creator_id, amount FROM checks WHERE code = ? AND is_active = 1",
                (check_code,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    sent = await message.answer("❌ Чек не найден или уже активирован.")
                    await asyncio.sleep(3)
                    await sent.delete()
                    return

            check_id, creator_id, amount = row

            # Проверяем, не является ли пользователь создателем чека
            if creator_id == user.id:
                sent = await message.answer("❌ Нельзя активировать свой собственный чек.")
                await asyncio.sleep(3)
                await sent.delete()
                return

            await db.execute(
                "UPDATE checks SET is_active = 0, activated_by = ?, activated_at = ? WHERE id = ?",
                (user.id, int(time.time()), check_id)
            )
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user.id))
            async with db.execute("SELECT referral_id FROM users WHERE user_id = ?", (user.id,)) as ref_cursor:
                current_ref = await ref_cursor.fetchone()
                if current_ref and current_ref[0] is None:
                    await db.execute("UPDATE users SET referral_id = ? WHERE user_id = ?", (creator_id, user.id))
                    await db.execute(
                        "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, joined_at) VALUES (?, ?, ?)",
                        (creator_id, user.id, int(time.time()))
                    )
            await db.commit()
            try:
                await bot.send_message(
                    creator_id,
                    f"✅ Ваш чек {check_code} на {amount:.2f} RUB был активирован пользователем "
                    f"<a href='tg://user?id={user.id}'>{user.full_name}</a>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await message.answer(f"🎉 Вы активировали чек на {amount:.2f} RUB!")
            return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT reg_time FROM users WHERE user_id = ?", (user.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                reg_days = get_reg_days(row[0])
                await message.answer(
                    f"""Привет, {user.full_name}! 🎰
Добро пожаловать в наше казино!
Используй меню ниже 👇""",
                    reply_markup=get_reply_keyboard()
                )
            else:
                await message.answer(
                    f"""Привет, {user.full_name}! 🎰
Добро пожаловать!""",
                    reply_markup=get_reply_keyboard()
                )

@dp.message(lambda msg: msg.text == "👤 Профиль")
async def profile_handler(message: Message):
    await show_profile(message, message.from_user.id)

@dp.message(lambda msg: msg.text == "🎮 Игры")
async def games_menu(message: Message):
    await message.answer(
        "🕹️ Доступные игры:",
        reply_markup=get_games_keyboard()
    )

@dp.message(lambda msg: msg.text == "🎲 Кости")
async def start_dice_game(message: Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT dg.game_id, dg.bet, dg.max_players, COUNT(dp.user_id) as current_players
            FROM dice_games dg
            LEFT JOIN dice_players dp ON dg.game_id = dp.game_id
            WHERE dg.status = 'waiting'
            GROUP BY dg.game_id
            HAVING current_players < dg.max_players
            ORDER BY dg.created_at DESC
        """) as cursor:
            games = await cursor.fetchall()
    msg = "<b>🎲 Лобби игры \"Кости\"</b>\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать игру", callback_data="create_dice_game")
    if games:
        msg += "Доступные лобби:\n"
        for game_id, bet, max_players, current_players in games:
            builder.button(text=f"{game_id} ({current_players}/{max_players}) {bet:.0f} RUB", callback_data=f"dice_game_info:{game_id}")
    else:
        msg += "Нет доступных лобби. Создайте своё!\n"
    builder.button(text="📋 Мои лобби", callback_data="my_dice_games")
    builder.button(text="🔙 Назад", callback_data="back_to_games")
    builder.adjust(1, *[1] * len(games), 1, 1)
    await message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.message(lambda msg: msg.text == "🔙 В главное меню")
async def back_to_main_menu(message: Message):
    await message.answer(
        "Вы вернулись в главное меню.",
        reply_markup=get_reply_keyboard()
    )

@dp.message(lambda msg: msg.text == "📚 Информация")
async def info_handler(message: Message):
    await message.answer("Здесь будет инфо ℹ️")

@dp.message(lambda msg: msg.text == "🖥 Статистика")
async def casino_stats_handler(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        # Общий депозит
        async with db.execute("SELECT COALESCE(SUM(deposit), 0) FROM users") as cursor:
            total_deposit = (await cursor.fetchone())[0]
        # Общий вывод
        async with db.execute("SELECT COALESCE(SUM(withdraw), 0) FROM users") as cursor:
            total_withdraw = (await cursor.fetchone())[0]
        # Количество игроков
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_players = (await cursor.fetchone())[0]
        # Количество сыгранных игр
        async with db.execute("SELECT COUNT(*) FROM dice_games WHERE status = 'finished'") as cursor:
            total_games = (await cursor.fetchone())[0]
    msg = f"""<b>📊 Статистика казино</b>
💰 Общий депозит: {total_deposit:.2f} RUB
💳 Общий вывод: {total_withdraw:.2f} RUB
👥 Игроков: {total_players}
🎲 Сыграно игр: {total_games}"""
    await message.answer(msg, parse_mode="HTML")

# Inline хендлеры
@dp.callback_query(F.data == "accept_policy")
async def accept_policy_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET agreed_policy = 1 WHERE user_id = ?", (user_id,))
        await db.commit()
    await callback.message.delete()
    await callback.message.answer(
        "✅ Спасибо! Теперь вы можете пользоваться всеми функциями бота.",
        reply_markup=get_reply_keyboard()
    )

@dp.callback_query(F.data == "deposit")
async def deposit_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("📥 Для пополнения баланса здесь будет инфо", reply_markup=get_back_to_profile_kb())

# @dp.callback_query(F.data == "withdraw")  # Этот хендлер заменен на полноценную систему выше
# async def withdraw_handler(callback: CallbackQuery):
#     await callback.message.delete()
#     await callback.message.answer("📤 Для вывода средств тоже будет инфо", reply_markup=get_back_to_profile_kb())

@dp.callback_query(F.data == "active_promo")
async def promo_handler(callback: CallbackQuery):
    await callback.message.delete()
    msg = "🎁 Введите промокод:"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Отменить", callback_data="back_to_profile")
    await callback.message.answer(msg, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "db_check")
async def db_check_handler(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Тут хуй знает что должно быть", reply_markup=get_back_to_profile_kb())

@dp.callback_query(F.data == "refferals_sys")
async def referrals_handler(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ref_code FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Ошибка", show_alert=True)
                return
            ref_code = row[0]
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(deposit), 0) FROM users WHERE referral_id = ?",
            (user_id,)
        ) as cursor:
            ref_count, total_deposit = await cursor.fetchone()
        best_ref_msg = ""
        async with db.execute("""
            SELECT u.username, u.user_id, r.total_deposit
            FROM referrals r
            JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.total_deposit DESC
            LIMIT 1
        """, (user_id,)) as cursor:
            best_ref = await cursor.fetchone()
            if best_ref and best_ref[2] > 0:
                username, user_id, deposit = best_ref
                name = f"@{username}" if username else f"ID{user_id}"
                best_ref_msg = f"\n Больше всего доход: {name} — {deposit:.2f} RUB"
        bot_username = (await bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={ref_code}"
        msg = f"""<b>👥 Реферальная система</b>
🔗 Твоя реф.ссылка:
<code>{ref_link}</code>
👥 Приглашено: {ref_count}
💰 Общий депозит рефералов: {total_deposit:.2f} RUB{best_ref_msg}
🎁 Твой бонус: 5% от каждого депозита реферала"""
        builder = InlineKeyboardBuilder()
        builder.button(
            text="📨 Пригласить друга",
            switch_inline_query=f"Приглашаю тебя залететь в новый казик! {ref_link}"
        )
        builder.button(text="📈 История приглашённых", callback_data="ref_history")
        builder.button(text="🔙 Вернуться в профиль", callback_data="back_to_profile")
        builder.adjust(1, 1, 1)
        await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "ref_history")
async def ref_history_handler(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT u.username, u.user_id, r.joined_at, r.total_deposit
            FROM referrals r
            JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.joined_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Вернуться в профиль", callback_data="back_to_profile")
    if not rows:
        msg = "У тебя пока нет приглашённых 😔"
        await callback.message.answer(msg, reply_markup=builder.as_markup())
        return
    msg = "<b>📈 Твои приглашённые:</b>\n"
    for username, user_id, joined_at, total_deposit in rows:
        display_name = username if username else f"ID {user_id}"
        name_link = f"<a href='tg://user?id={user_id}'>{display_name}</a>"
        date = datetime.fromtimestamp(joined_at).strftime('%d.%m.%Y')
        msg += f"👤 {name_link} | 📅 {date} | 💰 {total_deposit:.2f} RUB\n"
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "show_checks")
async def show_checks_handler(callback: CallbackQuery):
    await callback.message.delete()
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT code, amount FROM checks WHERE creator_id = ? AND is_active = 1",
            (user_id,)
        ) as cursor:
            active_checks = await cursor.fetchall()
    msg = "<b>⭐️ Ваши чеки</b>\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать чек", callback_data="create_check")
    if active_checks:
        msg += "Ваши активные чеки:\n"
        for code, amount in active_checks:
            builder.button(text=f"Чек {code} ({amount:.2f} RUB)", callback_data=f"check_detail:{code}")
    else:
        msg += "У вас нет активных чеков.\n"
    builder.button(text="🔙 Вернуться в профиль", callback_data="back_to_profile")
    builder.adjust(1, *[1] * len(active_checks), 1)
    await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "create_check")
async def create_check_handler(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DiceGameState.waiting_for_check_amount)
    await callback.message.delete()
    msg = "Введите сумму чека (в RUB):"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к чекам", callback_data="show_checks")
    await callback.message.answer(msg, reply_markup=builder.as_markup())
    await callback.answer("Введите сумму числом, например: 100.50", show_alert=False)

# ✅ Главный хендлер чеков — с проверкой состояния
@dp.message(lambda msg: msg.text.replace('.', '', 1).isdigit() and float(msg.text) > 0)
async def handle_check_amount(message: Message, state: FSMContext):
    # Получаем текущее состояние
    current_state = await state.get_state()
    if current_state is not None:
        print(f"[DEBUG CHECK] Игнорируем {message.text} — пользователь в состоянии {current_state}")
        # Если пользователь в состоянии создания чека, обрабатываем как сумму чека
        if current_state == "DiceGameState:waiting_for_check_amount":
            try:
                amount = float(message.text)
                if amount < 1:
                    raise ValueError
                user_id = message.from_user.id
                user_data = await get_user(user_id)
                if not user_data or user_data['balance'] < amount:
                    sent = await message.answer(
                        "❌ Недостаточно средств для создания чека.",
                        reply_markup=InlineKeyboardBuilder()
                            .button(text="🔙 Назад к чекам", callback_data="show_checks")
                            .as_markup()
                    )
                    await asyncio.sleep(5)
                    await sent.delete()
                    return
                code = generate_check_code()
                async with aiosqlite.connect(DB_PATH) as db:
                    while True:
                        async with db.execute("SELECT 1 FROM checks WHERE code = ?", (code,)) as cursor:
                            if not await cursor.fetchone():
                                break
                        code = generate_check_code()
                    await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                    await db.execute(
                        "INSERT INTO checks (code, creator_id, amount, created_at) VALUES (?, ?, ?, ?)",
                        (code, user_id, amount, int(time.time()))
                    )
                    await db.commit()
                bot_username = (await bot.get_me()).username
                check_link = f"https://t.me/{bot_username}?start={code}"
                msg = f"""✅ Чек создан!
Сумма: {amount:.2f} RUB
Код: <code>{code}</code>
Ссылка: {check_link}
Отправьте её кому-то — и они получат деньги на баланс!"""
                builder = InlineKeyboardBuilder()
                builder.button(text="🔙 Назад к чекам", callback_data="show_checks")
                await message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
                await state.clear()
            except Exception as e:
                sent = await message.answer(
                    "❌ Ошибка. Введите корректную сумму (например, 100.50).",
                    reply_markup=InlineKeyboardBuilder()
                        .button(text="🔙 Назад к чекам", callback_data="show_checks")
                        .as_markup()
                )
                await asyncio.sleep(5)
                await sent.delete()
        return  # Игнорируем, если в другом состоянии (например, создание игры)
    print(f"[DEBUG CHECK] Обрабатываем как промокод: {message.text}")
    # Если не в состоянии, обрабатываем как промокод (старая логика)
    user_id = message.from_user.id
    code = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, amount, creator_id, uses_left FROM promocodes WHERE code = ? AND uses_left > 0",
            (code,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await message.answer("❌ Промокод не найден или лимит активаций исчерпан.")
                return
        promo_id, amount, creator_id, uses_left = row
        # Начисляем баланс
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        # Уменьшаем лимит активаций
        new_uses_left = uses_left - 1
        await db.execute(
            "UPDATE promocodes SET uses_left = ? WHERE id = ?",
            (new_uses_left, promo_id)
        )
        await db.commit()
        # Уведомляем создателя
        try:
            await bot.send_message(
                creator_id,
                f"🎁 Ваш промокод {code} на {amount:.2f} RUB был активирован пользователем "
                f"<a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
                f"Осталось активаций: {new_uses_left}",
                parse_mode="HTML"
            )
        except:
            pass
        await message.answer(f"🎉 Промокод активирован! На ваш баланс зачислено {amount:.2f} RUB.\nОсталось активаций: {new_uses_left}")

@dp.callback_query(F.data.startswith("check_detail:"))
async def check_detail_handler(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount, creator_id FROM checks WHERE code = ? AND is_active = 1 AND creator_id = ?",
            (code, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Чек не найден или не принадлежит вам", show_alert=True)
                return
        amount, creator_id = row
        msg = f"""<b>Чек {code}</b>
Сумма: {amount:.2f} RUB
Выберите действие:"""
        builder = InlineKeyboardBuilder()
        builder.button(text="📤 Отправить", switch_inline_query=f"Активируй чек в этом казино: https://t.me/{(await bot.get_me()).username}?start={code}")
        builder.button(text="❌ Удалить чек", callback_data=f"delete_check:{code}")
        builder.button(text="🔙 Назад к чекам", callback_data="show_checks")
        builder.adjust(1, 1, 1)
        await callback.message.delete()
        await callback.message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("delete_check:"))
async def delete_check_handler(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT amount FROM checks WHERE code = ? AND is_active = 1 AND creator_id = ?",
            (code, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await callback.answer("Чек не найден", show_alert=True)
                return
        amount = row[0]
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.execute("UPDATE checks SET is_active = 0 WHERE code = ?", (code,))
        await db.commit()
    await callback.answer("Чек удалён, средства возвращены", show_alert=True)
    await callback.message.delete()
    await show_checks_handler(callback)

@dp.callback_query(F.data == "back_to_profile")
async def back_to_profile_handler(callback: CallbackQuery):
    await callback.message.delete()
    await show_profile(callback, callback.from_user.id)

# --- ПРОМОКОДЫ ---
@dp.message(Command("createpromo"))
async def create_promo(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет прав для создания промокодов.")
        return
    args = message.text.split()
    if len(args) != 4:
        await message.answer("❌ Использование: /createpromo <КОД> <СУММА> <ЛИМИТ>")
        return
    code = args[1].strip()
    try:
        amount = float(args[2])
        total_uses = int(args[3])
        if amount <= 0 or total_uses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Сумма и лимит должны быть положительными числами.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO promocodes (code, amount, creator_id, total_uses, uses_left, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (code, amount, message.from_user.id, total_uses, total_uses, int(time.time()))
            )
            await db.commit()
            await message.answer(f"✅ Промокод {code} на {amount:.2f} RUB создан! Лимит активаций: {total_uses}")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Промокод с таким кодом уже существует.")

# --- ЗАПУСК ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())