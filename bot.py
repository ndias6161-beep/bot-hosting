import uuid
import datetime
import asyncio
import random
import sqlite3
import pytz
from datetime import datetime # это тоже понадобится для команды "время"
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# --- КОНФИГУРАЦИЯ ---
TOKEN = "7913689244:AAGFfGKzRSCu7Jbfh7sY4w2KCJqROUNROYs"
ADMIN_ID = (8049948727, 8593794663)
X50_CHAT_ID = -1003592894012 

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ ---
conn = sqlite3.connect("lira_ultimate_v2.db", check_same_thread=False)
cur = conn.cursor()

# 1. Создаем основную таблицу пользователей
cur.execute('''CREATE TABLE IF NOT EXISTS users (
    uid INTEGER PRIMARY KEY, 
    name TEXT, 
    bal INTEGER DEFAULT 10000, 
    played INTEGER DEFAULT 0, 
    won INTEGER DEFAULT 0, 
    daily INTEGER DEFAULT 0,
    reg TEXT, 
    bonus TEXT, 
    last_x50_bet TEXT,
    level INTEGER DEFAULT 1,      -- Добавлено для уровней
    used_limit INTEGER DEFAULT 0   -- Добавлено для суточных лимитов
)''')

# 2. ПРОВЕРКА И ДОБАВЛЕНИЕ КОЛОНОК (если таблица уже была создана ранее без них)
# Этот блок исправит ошибки "no such column"
try:
    cur.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
except: pass

try:
    cur.execute("ALTER TABLE users ADD COLUMN used_limit INTEGER DEFAULT 0")
except: pass

# 3. Таблица админов
cur.execute('''CREATE TABLE IF NOT EXISTS admins (uid INTEGER PRIMARY KEY)''')

# 4. Остальные таблицы
cur.execute('''CREATE TABLE IF NOT EXISTS promo (code TEXT PRIMARY KEY, amount INTEGER, uses INTEGER)''')
cur.execute('''CREATE TABLE IF NOT EXISTS promo_history (uid INTEGER, code TEXT)''')
cur.execute('''CREATE TABLE IF NOT EXISTS x50_history (id INTEGER PRIMARY KEY AUTOINCREMENT, res TEXT)''')

# 5. Казна
cur.execute('''CREATE TABLE IF NOT EXISTS treasury (
    id INTEGER PRIMARY KEY, 
    balance INTEGER DEFAULT 0, 
    reward_per_user INTEGER DEFAULT 100)''')
cur.execute("INSERT OR IGNORE INTO treasury (id, balance, reward_per_user) VALUES (1, 0, 100)")

# 6. История игр
cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER,
    game_name TEXT,
    bet INTEGER,
    win_amount INTEGER,
    coef REAL,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()


try:
    cur.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
    conn.commit()
except: pass
# --- ЭТОТ БЛОК ИСПРАВИТ ОШИБКУ ---
try:
    cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
    conn.commit()
    print("Колонка username успешно добавлена!")
except Exception as e:
    print(f"Заметка: {e}") # Если она уже есть, просто пойдет дальше
# ---------------------------------

# Добавляем новые колонки
for col in [
    ("bank", "INTEGER DEFAULT 0"), 
    ("reputation", "INTEGER DEFAULT 0"), 
    ("bio", "TEXT DEFAULT 'Пока пусто'"),
    ("hide_bal", "INTEGER DEFAULT 0"),  # 0 - открыт, 1 - скрыт
    ("hide_bank", "INTEGER DEFAULT 0")  # 0 - открыт, 1 - скрыт
]:
    try:
        cur.execute(f"ALTER TABLE users ADD COLUMN {col[0]} {col[1]}")
    except: pass
conn.commit()

cur.execute('''CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER,
    game TEXT,
    amount INTEGER,
    result TEXT,
    date DATETIME DEFAULT CURRENT_TIMESTAMP
)''')
conn.commit()


# Удаляем старую таблицу (ВНИМАНИЕ: старые логи удалятся)
cur.execute("DROP TABLE IF EXISTS logs")

# Создаем таблицу заново с нужными колонками
cur.execute('''CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER,
    type TEXT,       -- 'game' или 'transfer'
    action TEXT,     -- название игры или ник игрока
    amount INTEGER,
    result TEXT,     -- 'выигрыш', 'проигрыш', 'sent' или 'received'
    date DATETIME DEFAULT CURRENT_TIMESTAMP
)''')
conn.commit()

cur.execute('''CREATE TABLE IF NOT EXISTS tournament (
    uid INTEGER PRIMARY KEY,
    username TEXT,
    max_coef REAL,
    date DATETIME
)''')
conn.commit()

cur.execute('''CREATE TABLE IF NOT EXISTS checks (
    check_id TEXT PRIMARY KEY,
    owner_id INTEGER,
    amount INTEGER,
    activations INTEGER,
    remaining INTEGER,
    password TEXT,
    date TEXT
)''')
conn.commit()

# --- СОСТОЯНИЯ ---
class AdminStates(StatesGroup):
    # Для выдачи
    give_id = State()
    give_amount = State()
    # Для промо
    promo_name = State()
    promo_sum = State()
    promo_uses = State()
    # Для рассылки
    mailing_text = State()
    # Для ФК и Викторины
    fast_amount = State()
    vik_amount = State()
    vik_question = State()
    vik_answer = State()
# ... твои старые состояния ...
    user_control = State() # Для ввода ID пользователя

class SupportStates(StatesGroup):
    waiting_for_report = State()  # Ожидание обращения от юзера
    waiting_for_admin_answer = State()  # Ожидание текста ответа от админа


# Убедись, что этот класс добавлен в твои состояния
class VilinStates(StatesGroup):
    confirm = State()

class GameStates(StatesGroup):
    toad = State()   # Состояние для Жабы
    mines = State()  # Состояние для Мин
    tower = State()  # <--- ДОБАВЬ ЭТУ СТРОКУ
    # ... другие твои состояния

class CreateCheck(StatesGroup):
    amount = State()
    activations = State()
    password = State()    
#m
from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable

class BanMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        # Проверяем, есть ли пользователь в базе и забанен ли он
        cur.execute("SELECT banned FROM users WHERE uid = ?", (event.from_user.id,))
        res = cur.fetchone()
        
        if res and res[0] == 1:
            # Если забанен, прерываем цепочку и отвечаем
            return await event.answer(
                "❌ <b>Доступ заблокирован!</b>\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\nВы были забанены за нарушение правил.",
                parse_mode="HTML"
            )
        
        # Если не забанен, пропускаем к хендлерам
        return await handler(event, data)


dp.message.outer_middleware(BanMiddleware())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_u(uid, name, username=None):
    cur.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    res = cur.fetchone()
    if not res:
        from datetime import datetime
        reg_date = datetime.now().strftime("%d.%m.%Y")
        
        # Если юзернейма нет (бывает в ЛС), ставим "None"
        uname = username.replace("@", "") if username else "None"
        
        # ВНИМАНИЕ: Убедись, что количество колонок (uid, name...) 
        # совпадает с количеством знаков ? (их тут 6)
        try:
            cur.execute("""INSERT INTO users (uid, name, reg, level, used_limit, username) 
                           VALUES (?, ?, ?, ?, ?, ?)""", 
                        (uid, name, reg_date, 1, 0, uname))
            conn.commit()
        except Exception as e:
            print(f"Ошибка при регистрации: {e}")
            
        cur.execute("SELECT * FROM users WHERE uid = ?", (uid,))
        return cur.fetchone()
    return res

def b_num(number):
    """Превращает число в жирный текст с разделителями"""
    return f"<b>{number:,}</b>"

def upd_bal(uid, am):
    cur.execute("UPDATE users SET bal = bal + ?, daily = daily + ? WHERE uid = ?", (am, am if am > 0 else 0, uid))
    conn.commit()

def is_admin(uid):
    cur.execute("SELECT uid FROM admins WHERE uid = ?", (uid,))
    return cur.fetchone() is not None

def get_all_admins():
    cur.execute("SELECT uid FROM admins")
    return [row[0] for row in cur.fetchall()]

def log_game(uid, game_name, bet, win_amount, coef):
    conn = sqlite3.connect("lira_ultimate_v2.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO history (uid, game_name, bet, win_amount, coef) VALUES (?, ?, ?, ?, ?)",
                (uid, game_name, bet, win_amount, coef))
    conn.commit()
    conn.close()

def parse_bet(val, user_bal):
    val = str(val).lower().strip().replace("кк", "000000").replace("к", "000")
    if val == "все": return user_bal
    try:
        res = int(val)
        return res if 100 <= res <= user_bal else -1
    except: return -2

def get_link(u):
    return f"[{u[1]}](tg://user?id={u[0]})"

def add_log(uid, l_type, action, amount, result):
    import datetime
    now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    # Записываем только ОДНО значение amount
    cur.execute("INSERT INTO logs (uid, type, action, amount, result, date) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, l_type, action, int(amount), result, now))
    conn.commit()

# --- КЛАВИАТУРЫ ---
def main_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(types.KeyboardButton(text="👤 Профиль"), types.KeyboardButton(text="🎁 Бонус"))
    kb.row(types.KeyboardButton(text="🏆 Топ игроки"))
    kb.row(types.KeyboardButton(text="📍 Помощь"), types.KeyboardButton(text="➕ Добавить"))
    return kb.as_markup(resize_keyboard=True)

# --- НИКИ И БАЛАНС ---
@dp.message(F.text.lower().startswith("+ник "))
async def set_new_nick(m: types.Message):
    new_nick = m.text[5:].strip().replace("[", "").replace("]", "")
    if len(new_nick) > 20 or len(new_nick) < 2:
        return await m.reply("❌ Ник от 2 до 20 символов!")
    cur.execute("UPDATE users SET name = ? WHERE uid = ?", (new_nick, m.from_user.id))
    conn.commit()
    await m.reply(f"✅ Ваш ник изменен на: {get_link([m.from_user.id, new_nick])}", parse_mode="Markdown")

@dp.message(F.text.lower() == "ник")
async def show_nick(m: types.Message):
    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    u = get_u(target.id, target.full_name)
    await m.reply(f"👤 Ник: {get_link(u)}", parse_mode="Markdown")

@dp.message(F.text.lower() == "б")
async def show_my_balance(m: types.Message):
    # Пытаемся получить баланс
    cur.execute("SELECT bal FROM users WHERE uid = ?", (m.from_user.id,))
    res = cur.fetchone()
    
    if res is None:
        # Если пользователя нет, регистрируем его «на лету»
        # Передаем id, имя и юзернейм
        u = get_u(m.from_user.id, m.from_user.full_name, m.from_user.username)
        balance = u[2] # 10000 по умолчанию
    else:
        balance = res[0]

    # Отправляем баланс жирным через HTML
    await m.reply(f"💸 Баланс: <b>{balance:,}</b> лир", parse_mode="HTML")
    
# --- ПЕРЕДАЧА И ВЫДАЧА ---
@dp.message(F.text.lower().startswith("дать "))
async def transfer(m: types.Message):
    if not m.reply_to_message: 
        return await m.reply("❌ Ответьте на сообщение игрока!")
    
    u = get_u(m.from_user.id, m.from_user.full_name)
    t_raw = m.reply_to_message.from_user
    t = get_u(t_raw.id, t_raw.full_name)
    
    if t_raw.is_bot or t[0] == u[0]: 
        return await m.reply("❌ Ошибка!")
    
    # Сумма перевода
    try:
        bet = parse_bet(m.text.split()[1] if len(m.text.split())>1 else "0", u[2])
    except:
        return await m.reply("❌ Введите сумму!")

    if bet < 100: 
        return await m.reply("❌ Минимум 100 лир!")

    # Проверка данных из БД
    cur.execute("SELECT level, used_limit, bal FROM users WHERE uid = ?", (u[0],))
    row = cur.fetchone()
    u_lv, u_used, u_bal = row[0], row[1], row[2]

    if bet > u_bal: 
        return await m.reply("❌ Недостаточно лир на балансе!")

    # Проверка лимита
    u_limit = LEVELS[u_lv]["limit"]
    if (u_used + bet) > u_limit:
        remains = u_limit - u_used
        return await m.reply(
            f"⚠️ **ЛИМИТ ИСЧЕРПАН!**\n"
            f"━━━━━━━━━━━━━━\n"
            f"Ваш уровень (**{u_lv}**) позволяет передать еще **{max(0, remains):,}** лир сегодня.\n\n"
            f"Лимиты обновляются в **22:00 МСК**.",
            parse_mode="Markdown"
        )

    # Проведение транзакции
    upd_bal(u[0], -bet)
    upd_bal(t[0], bet)
    
    # Записываем расход лимита
    cur.execute("UPDATE users SET used_limit = used_limit + ? WHERE uid = ?", (bet, u[0]))
    conn.commit()

    await m.answer(f"✅ {get_link(u)} передал **{bet:,}** лир игроку {get_link(t)}!", parse_mode="Markdown")
    
# --- 1. КОМАНДА ВЫДАТЬ (через реплай) ---
@dp.message(F.text.lower().startswith("выдать "))
async def adm_give_fast(m: types.Message):
    # Проверка доступа для списка админов
    if m.from_user.id not in ADMIN_ID: return 
    
    if not m.reply_to_message: 
        return await m.reply("❌ **Ответьте на сообщение игрока (реплай)!**", parse_mode="Markdown")
    
    try:
        # Поддержка 'к', чтобы можно было писать 'выдать 50к'
        summ_raw = m.text.split()[1].lower().replace("к", "000").replace("k", "000")
        summ = int(summ_raw)
        
        target_id = m.reply_to_message.from_user.id
        target_name = m.reply_to_message.from_user.first_name
        
        upd_bal(target_id, summ)
        
        await m.answer(
            f"👑 **АДМИНИСТРАЦИЯ**\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 Выдано: **{summ:,}** лир\n"
            f"👤 Игрок: **{target_name}**\n"
            f"━━━━━━━━━━━━━━", 
            parse_mode="Markdown"
        )
    except: 
        await m.reply("❌ **Ошибка!** Введите сумму числом (например: `выдать 10000` или `выдать 10к`)", parse_mode="Markdown")

import random
from aiogram import F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

# --- 1. Твоя формула коэффициентов ---
def get_mines_coef(mines_count: int, opened: int) -> float:
    total = 25
    if mines_count >= total or opened <= 0:
        return 1.0
    safe = total - mines_count
    prob = 1.0
    for i in range(opened):
        prob *= (safe - i) / (total - i)
    coef = (1.0 / prob) * 0.96
    return round(coef, 2)

# --- 2. Команда запуска ---
@dp.message(F.text.lower().startswith("мины"))
async def mines_start(m: types.Message, state: FSMContext):
    u = get_u(m.from_user.id, m.from_user.full_name, m.from_user.username)
    args = m.text.split()
    
    try:
        bet = parse_bet(args[1], u[2])
        mines_cnt = int(args[2]) if len(args) > 2 else 5
    except:
        return await m.reply("❌ Формат: `мины [ставка] [кол-во мин]`")

    if bet < 100: return await m.reply("❌ Ставка от 100 лир!")
    if not (1 <= mines_cnt <= 24): return await m.reply("❌ Мин может быть от 1 до 24!")
    if u[2] < bet: return await m.reply("❌ Недостаточно средств!")

    # Генерируем поле (1 - мина, 0 - пусто)
    field = [1] * mines_cnt + [0] * (25 - mines_cnt)
    random.shuffle(field)

    upd_bal(m.from_user.id, -bet)

    data = {
        "bet": bet,
        "mines_cnt": mines_cnt,
        "field": field,
        "opened": 0,
        "opened_indices": [],
        "coef": 1.0,
        "game_id": random.randint(100000, 999999),
        "last_index": -1 # Для отслеживания взрыва
    }
    
    await state.update_data(data)
    await mines_render(m, data)

# --- 3. Отрисовка сетки 5х5 ---
async def mines_render(m, d, finished=False, is_win=False):
    kb = InlineKeyboardBuilder()
    
    for i in range(25):
        if finished:
            # Логика раскрытия как на скрине
            if d['field'][i] == 1:
                if i == d['last_index'] and not is_win:
                    txt = "💥" # Тот самый взрыв
                else:
                    txt = "💣" # Просто бомба
            else:
                if i in d['opened_indices']:
                    txt = "💎" # Открытая безопасная
                else:
                    txt = "🧊" # Не открытая безопасная
            kb.button(text=txt, callback_data="none")
        else:
            # Игровой процесс
            if i in d['opened_indices']:
                txt = "💎"
            else:
                txt = "❓"
            kb.button(text=txt, callback_data=f"mine_step_{i}")
    
    kb.adjust(5)

    if not finished:
        kb.row(types.InlineKeyboardButton(text="🔄 Автовыбор", callback_data="mine_auto"))
        if d['opened'] > 0:
            kb.row(types.InlineKeyboardButton(
                text=f"✅ Забрать выигрыш {d['coef']}X", 
                callback_data="mine_stop"
            ))

    # Текст сообщения
    if finished:
        if is_win:
            win_total = int(d['bet'] * d['coef'])
            text = (f"💎 **МИНЫ #{d['game_id']} — ИГРА ЗАВЕРШЕНА**\n\n"
                    f"💰 **Ставка:** {d['bet']:,} лир\n"
                    f"📈 **Коэффициент:** x{d['coef']}\n"
                    f"💵 **Выигрыш:** {win_total - d['bet']:,} лир\n"
                    f"💣 {d['mines_cnt']} | 💎 {25 - d['mines_cnt']}\n\n"
                    f"_Ты прошёл по полю смерти и остался жив._")
        else:
            text = (f"💣 **МИНОЕ ПОЛЕ — ПРОИГРЫШ**\n\n"
                    f"Вы подорвались! Ставка **{d['bet']:,}** лир потеряна.\n"
                    f"💣 {d['mines_cnt']} | 💎 {25 - d['mines_cnt']}")
    else:
        text = (f"✨ **Игра «Мины» #{d['game_id']} продолжается!**\n\n"
                f"💠 **Ставка:** {d['bet']:,} лир\n"
                f"💣 {d['mines_cnt']} | 💎 {d['opened']}\n"
                f"📈 **Текущий множитель:** x{d['coef']}\n\n"
                f"_Следующий клик может быть победным... или последним._")

    if isinstance(m, types.Message):
        await m.answer(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    else:
        try:
            await m.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        except: pass

# --- 4. Логика хода и Автовыбора ---
@dp.callback_query(F.data.startswith("mine_step_"))
@dp.callback_query(F.data == "mine_auto")
async def mine_logic(call: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d: return await call.answer()

    if call.data == "mine_auto":
        available = [i for i in range(25) if i not in d['opened_indices']]
        idx = random.choice(available)
    else:
        idx = int(call.data.split("_")[2])

    if idx in d['opened_indices']: return await call.answer()
    
    d['last_index'] = idx # Запоминаем последний ход

    if d['field'][idx] == 1: # Поражение
        await mines_render(call, d, finished=True, is_win=False)
        await state.clear()
        await call.answer("💥 БА-БАХ!", show_alert=True)
    else: # Успех
        d['opened'] += 1
        d['opened_indices'].append(idx)
        d['coef'] = get_mines_coef(d['mines_cnt'], d['opened'])
        
        # Если открыли все безопасные клетки - автопобеда
        if d['opened'] == (25 - d['mines_cnt']):
            win_total = int(d['bet'] * d['coef'])
            upd_bal(call.from_user.id, win_total)
            await mines_render(call, d, finished=True, is_win=True)
            await state.clear()
            await call.answer("🏆 Очистили всё поле!")
        else:
            await state.update_data(d)
            await mines_render(call, d)
    await call.answer()

# --- 5. Завершение игры (Забрать) ---
@dp.callback_query(F.data == "mine_stop")
async def mine_stop(call: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d: return

    win_total = int(d['bet'] * d['coef'])
    upd_bal(call.from_user.id, win_total)

    await mines_render(call, d, finished=True, is_win=True)
    await state.clear()
    await call.answer("Выигрыш зачислен!")

import random
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

# --- Функция отрисовки (красивое раскрытие) ---
async def toad_render(m, bet, lvl, levels, bombs, history, finished=False, result="lose"):
    kb = InlineKeyboardBuilder()
    
    for i in range(6, -1, -1):
        row_btns = []
        for j in range(8):
            if finished:
                # В конце игры показываем всё
                if j in bombs[i]:
                    text = "💣"
                elif history.get(f"step_{i}") == j:
                    text = "💎"
                else:
                    text = "🧊"
                row_btns.append(types.InlineKeyboardButton(text=text, callback_data="none"))
            else:
                # Процесс игры
                if i == lvl:
                    row_btns.append(types.InlineKeyboardButton(text="❓", callback_data=f"toad_{i}_{j}"))
                elif i < lvl:
                    # Прошлые уровни с учетом истории выбора
                    if j in bombs[i]:
                        text = "💣"
                    elif history.get(f"step_{i}") == j:
                        text = "💎"
                    else:
                        text = "🧊"
                    row_btns.append(types.InlineKeyboardButton(text=text, callback_data="none"))
                else:
                    row_btns.append(types.InlineKeyboardButton(text="⬛️", callback_data="none"))
        kb.row(*row_btns)

    if not finished:
        kb.row(types.InlineKeyboardButton(text="🎲 Автовыбор", callback_data="toad_auto"))
        if lvl > 0:
            kb.row(types.InlineKeyboardButton(
                text=f"💰 ЗАБРАТЬ {int(bet * levels[lvl-1]):,}", 
                callback_data="toad_c"
            ))

    status = "🎮 Игра идет..."
    if finished:
        status = "✅ <b>ВЫИГРЫШ!</b>" if result == "win" else "💥 <b>ПРОИГРЫШ!</b>"

    txt = (
        f"🐸 <b>ЖАБА</b> | Уровень {min(lvl+1, 7)}/7\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Ставка: <b>{bet:,}</b>\n"
        f"📈 Коэф: <b>x{levels[lvl-1] if lvl > 0 else 1.0}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{status}"
    )

    if isinstance(m, types.Message):
        await m.reply(txt, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        try:
            await m.message.edit_text(txt, reply_markup=kb.as_markup(), parse_mode="HTML")
        except:
            pass

    # ДОБАВЬ ЭТО:
    cur.execute("UPDATE users SET daily = daily + ? WHERE uid = ?", (win, uid))
    conn.commit()
    
# --- Команда старта ---
@dp.message(F.text.lower().startswith("жаба"))
async def toad_start(m: types.Message, state: FSMContext):
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    bet = parse_bet(args[1] if len(args) > 1 else "0", u[2])
    
    if bet < 100: return await m.reply("❌ Ставка от 100!")
    if u[2] < bet: return await m.reply("❌ Недостаточно лир!")
    
    upd_bal(u[0], -bet)
    levels = [1.2, 1.5, 2.0, 3.0, 5.0, 10.0, 25.0]
    bombs = [random.sample(range(8), i+1) for i in range(7)]
    
    # Инициализируем историю и состояние
    await state.set_state(GameStates.toad)
    data = {
        'bet': bet, 
        'bombs': bombs, 
        'lvl': 0, 
        'levels': levels, 
        'history': {}, 
        'user_name': m.from_user.first_name
    }
    await state.update_data(**data)
    await toad_render(m, bet, 0, levels, bombs, {})

# --- Логика игры (ИСПРАВЛЕННАЯ) ---
@dp.callback_query(F.data.startswith("toad_"), GameStates.toad)
async def toad_logic(call: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    # Теперь все переменные вытаскиваются правильно
    bet = d.get('bet')
    lvl = d.get('lvl')
    bombs = d.get('bombs')
    levels = d.get('levels')
    history = d.get('history', {})

    if call.data == "toad_c":
        win_total = int(bet * levels[lvl-1])
        upd_bal(call.from_user.id, win_total)
        await toad_render(call, bet, lvl, levels, bombs, history, finished=True, result="win")
        await state.clear()
        return

    # Определяем колонку выбора
    if call.data == "toad_auto":
        c = random.randint(0, 7)
    else:
        c = int(call.data.split("_")[2])

    # Записываем выбор в историю ДО проверки на бомбу
    history[f"step_{lvl}"] = c
    await state.update_data(history=history)

    if c in bombs[lvl]:
        # Проигрыш
        await toad_render(call, bet, lvl, levels, bombs, history, finished=True, result="lose")
        await state.clear()
    else:
        # Успех
        if lvl == 6:
            win_total = int(bet * 25.0)
            upd_bal(call.from_user.id, win_total)
            await toad_render(call, bet, 7, levels, bombs, history, finished=True, result="win")
            await state.clear()
        else:
            new_lvl = lvl + 1
            await state.update_data(lvl=new_lvl)
            await toad_render(call, bet, new_lvl, levels, bombs, history)
    
    await call.answer()



    
import random
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder


# --- Константы ---
CARDS_VALUES = {
    'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, 
    '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13
}
CARDS_NAMES = list(CARDS_VALUES.keys())
active_hilo_games = {}

# --- Функция отрисовки интерфейса ---
async def hl_render_game(m, game, finished=False, is_reminder=False):
    card = game['last']
    coef = game['coef']
    bet = game['bet']
    val = CARDS_VALUES[card]
    user_name = game.get('user_name', 'Игрок')

    prob_up = (13 - val + 1) / 13
    prob_down = val / 13
    next_up = max(round((1 / prob_up) * 0.92, 2), 1.1)
    next_down = max(round((1 / prob_down) * 0.92, 2), 1.1)
    k_same = 11.50

    kb = InlineKeyboardBuilder()
    if not finished:
        if card == 'K':
            kb.row(
                types.InlineKeyboardButton(text=f"⏺️ Та же [x{round(coef * k_same, 2)}]", callback_data=f"hl_same_{k_same}"),
                types.InlineKeyboardButton(text=f"⬇️ Ниже [x{round(coef * next_down, 2)}]", callback_data=f"hl_down_{next_down}")
            )
        elif card == 'A':
            kb.row(
                types.InlineKeyboardButton(text=f"⬆️ Выше [x{round(coef * next_up, 2)}]", callback_data=f"hl_up_{next_up}"),
                types.InlineKeyboardButton(text=f"⏺️ Та же [x{round(coef * k_same, 2)}]", callback_data=f"hl_same_{k_same}")
            )
        else:
            kb.row(
                types.InlineKeyboardButton(text=f"⬆️ Выше [x{round(coef * next_up, 2)}]", callback_data=f"hl_up_{next_up}"),
                types.InlineKeyboardButton(text=f"⬇️ Ниже [x{round(coef * next_down, 2)}]", callback_data=f"hl_down_{next_down}")
            )
        
        if coef > 1.0:
            kb.row(types.InlineKeyboardButton(text=f"💰 ЗАБРАТЬ {int(bet * coef):,}", callback_data="hl_collect"))

    header = "<b>#Активная Игра</b>\n" if is_reminder else ""
    
    text = (
        f"{header}🃏 <b>HI-LO</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Ставка: <b>{bet:,}</b>\n"
        f"📈 Множитель: <b>x{coef}</b>\n"
        f"💰 Выигрыш: <b>{int(bet * coef):,}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎴 Карта: <b>{card}</b>"
    )

    if finished:
        if game.get('result') == "win":
            text += f"\n\n✅ <b>{user_name}</b>, выигрыш зачислен: <b>{int(bet * coef):,}</b>"
        else:
            text += f"\n\n❌ <b>{user_name}</b>, проигрыш! Карта: <b>{card}</b>"

    markup = kb.as_markup() if not finished else None

    # ГЛАВНОЕ ИЗМЕНЕНИЕ ТУТ:
    if isinstance(m, types.Message):
        # Используем .reply() чтобы бот ответил на сообщение игрока (с цитированием)
        await m.reply(text, reply_markup=markup, parse_mode="HTML")
    else:
        # Если это нажатие кнопки (callback), просто редактируем текст
        try:
            await m.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except:
            pass

# --- Старт игры ---
@dp.message(F.text.lower().startswith("хл"))
async def hl_start(m: types.Message):
    user_id = m.from_user.id
    u = get_u(m.from_user.id, m.from_user.full_name, m.from_user.username)
    args = m.text.split()
    
    # Если игра уже есть — реплаим на текущее сообщение
    if user_id in active_hilo_games:
        return await hl_render_game(m, active_hilo_games[user_id], is_reminder=True)

    try:
        bet = parse_bet(args[1] if len(args) > 1 else "0", u[2])
    except: return

    if bet < 100: return await m.reply("❌ Минимум 100 лир")
    if u[2] < bet: return await m.reply("❌ Недостаточно средств")

    upd_bal(user_id, -bet)
    
    start_card = random.choice(['3', '4', '5', '6', '7', '8', '9', '10', 'J'])
    game = {
        "bet": bet, 
        "last": start_card, 
        "coef": 1.0, 
        "finished": False,
        "user_name": m.from_user.first_name
    }
    
    active_hilo_games[user_id] = game
    # Запускаем отрисовку, которая сделает .reply()
    await hl_render_game(m, game)

# --- Callback кнопок ---
@dp.callback_query(F.data.startswith("hl_"))
async def hl_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    # Сразу отвечаем, чтобы кнопка не крутилась
    await call.answer()

    if user_id not in active_hilo_games:
        return await call.answer("⏳ Ваша игра не найдена", show_alert=True)

    game = active_hilo_games[user_id]
    if game.get('finished'): return 

    if call.data == "hl_collect":
        payout = int(game['bet'] * game['coef'])
        upd_bal(user_id, payout)
        game.update({"finished": True, "result": "win"})

        # --- ЗАПИСЬ КОЭФФИЦИЕНТА ---
        try:
            import datetime
            now = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
            current_coef = game['coef']
            user_name = call.from_user.first_name or "Игрок"

            cur.execute("SELECT max_coef FROM tournament WHERE uid = ?", (user_id,))
            res = cur.fetchone()

            if res is None:
                cur.execute("INSERT INTO tournament (uid, username, max_coef, date) VALUES (?, ?, ?, ?)",
                            (user_id, user_name, current_coef, now))
            elif current_coef > res[0]:
                cur.execute("UPDATE tournament SET max_coef = ?, username = ?, date = ? WHERE uid = ?",
                            (current_coef, user_name, now, user_id))
            conn.commit()
        except Exception as e:
            print(f"Ошибка турнира: {e}")
        # ---------------------------

        await hl_render_game(call, game, finished=True)
        active_hilo_games.pop(user_id, None)
        return

    _, action, step_k = call.data.split("_")
    new_card = random.choice(CARDS_NAMES)
    old_val = CARDS_VALUES[game['last']]
    new_val = CARDS_VALUES[new_card]

    if new_val == old_val:
        if action == "same":
            game['coef'] = round(game['coef'] * float(step_k), 2)
        game['last'] = new_card
        return await hl_render_game(call, game)

    win = False
    if action == "up" and new_val > old_val: win = True
    elif action == "down" and new_val < old_val: win = True

    if win:
        game['coef'] = round(game['coef'] * float(step_k), 2)
        game['last'] = new_card
        await hl_render_game(call, game)
    else:
        game.update({"finished": True, "result": "lose", "last": new_card})
        await hl_render_game(call, game, finished=True)
        active_hilo_games.pop(user_id, None)


# --- ЭМОДЗИ ИГРЫ ---
@dp.message(F.text.lower().startswith(("дартс", "футбол", "баскетбол", "боулинг", "спин")))
async def emoji_games(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name); args = m.text.split(); cmd = args[0].lower()
    bet = parse_bet(args[1] if len(args)>1 else "0", u[2])
    if bet < 100: return
    target = args[2].lower() if cmd == "дартс" and len(args)>2 else None
    if cmd == "дартс" and not target: return await m.reply("📖 `дартс [сумма] [б/к/ц/м]`")
    upd_bal(u[0], -bet); emo = {"дартс":"🎯", "футбол":"⚽️", "баскетбол":"🏀", "боулинг":"🎳", "спин":"🎰"}
    msg = await m.answer_dice(emoji=emo[cmd]); val = msg.dice.value; await asyncio.sleep(4)
    win = 0
    if cmd == "дартс":
        res = {1:'м', 2:'б', 3:'к', 4:'б', 5:'к', 6:'ц'}.get(val, 'м')
        if target == res: win = bet * (3 if target in ['ц', 'м'] else 2)
    elif cmd == "футбол" and val >= 3: win = int(bet*1.6)
    elif cmd == "баскетбол" and val >= 4: win = int(bet*1.8)
    elif cmd == "боулинг" and val == 6: win = int(bet*2.2)
    elif cmd == "спин" and val in [1, 22, 43, 64]: win = bet*2
    if win > 0:
        upd_bal(u[0], win); await m.reply(f"✅ Победа! {get_link(u)} +{win:,} лир.", parse_mode="Markdown")
    else: await m.reply(f"❌ Проигрыш! {get_link(u)} -{bet:,} лир.", parse_mode="Markdown")

# --- X50 ---
x50_lobby = {"active": False, "bets": []}

@dp.message(F.text.lower() == "дроп")
async def show_drop(m: types.Message):
    cur.execute("SELECT res FROM x50_history ORDER BY id DESC LIMIT 10")
    h = cur.fetchall()
    # Делаем заголовок и результаты жирными
    txt = "📜 <b>История X50:</b>\n\n" + "\n".join([f"• <b>{x[0]}</b>" for x in h])
    await m.answer(txt, parse_mode="HTML")

@dp.message(F.text.lower().startswith("х50"))
async def x50_start(m: types.Message):
    if m.chat.id != X50_CHAT_ID: 
        return await m.reply("❌ Игра Х50 доступна только в официальном чате!")
    
    args = m.text.split()
    u = get_u(m.from_user.id, m.from_user.full_name)
    
    if len(args) < 3: 
        return await m.reply("📖 Формат: <code>х50 [сумма] [ч/ф/к/з]</code>", parse_mode="HTML")
    
    bet = parse_bet(args[1], u[2])
    col = args[2].lower()
    
    # Маппинг цветов
    cmap = {
        'ч': ('black', '⚫', 2), 
        'ф': ('purple', '🟣', 3), 
        'к': ('red', '🔴', 5), 
        'з': ('green', '🟢', 50)
    }
    
    if col not in cmap or bet <= 0: 
        return await m.reply("❌ Ошибка в ставке или цвете!")
    
    if u[2] < bet:
        return await m.reply("❌ Недостаточно лир!")

    upd_bal(u[0], -bet)
    cur.execute("UPDATE users SET last_x50_bet=? WHERE uid=?", (f"{col}:{bet}", u[0]))
    
    x50_lobby["bets"].append({"uid": u[0], "name": u[1], "bet": bet, "col": cmap[col][0]})
    
    # Сделали имя и сумму жирными
    await m.reply(
        f"{cmap[col][1]} <b>{u[1]}</b> поставил <b>{bet:,}</b> лир на <b>x{cmap[col][2]}</b>", 
        parse_mode="HTML"
    )
    
    if not x50_lobby["active"]:
        x50_lobby["active"] = True
        await asyncio.sleep(15) 
        await run_x50(m.chat.id)

async def run_x50(cid):
    # Генерация результата
    res_k = random.choices(['black','purple','red','green'], weights=[45,35,19,1])[0]
    
    # Маппинг цветов (жирный шрифт только на множителе)
    rmap = {
        'black': ('⚫ <b>x2</b>', 2), 
        'purple': ('🟣 <b>x3</b>', 3), 
        'red': ('🔴 <b>x5</b>', 5), 
        'green': ('🟢 <b>x50</b>', 50)
    }
    
    # Записываем в историю (в историю пишем без HTML-тегов, если БД не поддерживает)
    cur.execute("INSERT INTO x50_history (res) VALUES (?)", (rmap[res_k][0],))
    conn.commit()
    
    # Начало сообщения как на скрине
    text = f"🎡 <b>Результат X50:</b> {rmap[res_k][0]}\n"
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    color_groups = [
        ('black', '⚫', 2), 
        ('purple', '🟣', 3), 
        ('red', '🔴', 5), 
        ('green', '🟢', 50)
    ]
    
    any_bets = False
    for name, emoji, mult in color_groups:
        bets = [b for b in x50_lobby["bets"] if b["col"] == name]
        if not bets:
            continue
            
        any_bets = True
        # Заголовок подгруппы (жирный)
        text += f"{emoji} <u><b>Ставки на x{mult}:</b></u>\n"
        
        for b in bets:
            if b["col"] == res_k:
                win = b["bet"] * mult
                upd_bal(b["uid"], win)
                # ✅ Стиль победы: Имя — Ставка -> Итог
                text += f"💸 <b>{b['name']}</b> — <b>{b['bet']:,}</b> → <b>{win:,}</b>\n"
            else:
                # ❌ Стиль проигрыша: Имя — Ставка -> 0
                text += f"❌ <b>{b['name']}</b> — <b>{b['bet']:,}</b> → <b>0</b>\n"
        
        # Линия после каждой группы ставок
        text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"

    if not any_bets:
        text += "<i>Ставок не было.</i>\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"

    # Клавиатура с кнопкой
    builder = InlineKeyboardBuilder()
    builder.button(text="🔁 Повторить ставку", callback_data="x50_re")
    
    await bot.send_message(
        cid, 
        text, 
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    
    # Очистка лобби
    x50_lobby["active"] = False
    x50_lobby["bets"] = []

#jackpot
import asyncio # Проверь, что это есть в самом верху файла!

# --- JACKPOT CONFIG ---
jackpot_lobby = {"active": False, "bets": []}

@dp.message(F.text.lower().startswith("джекпот"))
async def jackpot_start(m: types.Message):
    # Убедись, что переменная X50_CHAT_ID определена в начале твоего кода
    if m.chat.id != X50_CHAT_ID: 
        return await m.reply("❌ Игра доступна только в официальном чате!")
    
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    
    if len(args) < 2:
        return await m.reply("📖 Формат: <code>джекпот [сумма]</code>", parse_mode="HTML")
    
    bet = parse_bet(args[1], u[2])
    
    if bet < 100: 
        return await m.reply("❌ Минимальная ставка — <b>100</b> лир!", parse_mode="HTML")
    
    if u[2] < bet:
        return await m.reply("❌ Недостаточно лир!")

    # Списываем ставку и добавляем в лобби
    upd_bal(u[0], -bet)
    jackpot_lobby["bets"].append({"uid": u[0], "name": u[1], "bet": bet})
    
    total_bank = sum(b['bet'] for b in jackpot_lobby["bets"])
    
    await m.reply(
        f"🎟 <b>{u[1]}</b> внес в банк <b>{bet:,}</b> лир!\n"
        f"💰 Общий банк: <b>{total_bank:,}</b> лир", 
        parse_mode="HTML"
    )
    
    # Запуск таймера только ОДИН раз (для первой ставки)
    if not jackpot_lobby["active"]:
        jackpot_lobby["active"] = True
        # Мы используем create_task, чтобы код не "зависал" на 30 секундах и принимал другие ставки
        asyncio.create_task(start_jackpot_timer(m.chat.id))

async def start_jackpot_timer(cid):
    await asyncio.sleep(30) # Ждем 30 секунд для сбора всех ставок
    await run_jackpot(cid)


async def run_jackpot(cid):
    # Добавляем явное указание, что мы используем глобальный модуль random
    global random 
    
    bets = jackpot_lobby["bets"].copy()
    if not bets:
        jackpot_lobby["active"] = False
        return

    total_bank = sum(b['bet'] for b in bets)
    
    # Выбираем победителя
    # Ошибка была здесь — Python не видел модуль random
    winner = random.choices(bets, weights=[b['bet'] for b in bets], k=1)[0]
    
    win_chance = round((winner['bet'] / total_bank) * 100, 1)
    
    # Начисляем выигрыш
    upd_bal(winner['uid'], total_bank)
    
    # Оформление (Жирный шрифт и линии как на скринах)
    text = f"🎰 <b>ИТОГИ ДЖЕКПОТА</b>\n"
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    text += f"🏆 Победитель: <b>{winner['name']}</b>\n"
    text += f"💰 Выигрыш: <b>{total_bank:,}</b> лир\n"
    text += f"📈 Шанс победы: <b>{win_chance}%</b>\n"
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    text += "<b>Участники раунда:</b>\n"
    
    for b in bets:
        chance = round((b['bet'] / total_bank) * 100, 1)
        text += f"• <b>{b['name']}</b> — <b>{b['bet']:,}</b> (<i>{chance}%</i>)\n"
    
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"

    # Сбрасываем лобби ПЕРЕД отправкой сообщения
    jackpot_lobby["active"] = False
    jackpot_lobby["bets"] = []

    await bot.send_message(cid, text, parse_mode="HTML")

    
#FORTUNA
    import random
import asyncio
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка секторов (эмодзи, множитель, шанс в весах)
WHEEL_SECTORS = [
    ("🔴", 0, 40),      # Проигрыш (40% шанс)
    ("⚪️", 0.5, 25),    # Возврат половины (25% шанс)
    ("🟡", 1.5, 15),    # Небольшой плюс (15% шанс)
    ("🔵", 2, 10),      # Удвоение (10% шанс)
    ("🟣", 5, 7),       # Пятикратный выигрыш (7% шанс)
    ("💎", 15, 3),      # Джекпот сектора (3% шанс)
]

@dp.message(F.text.lower().startswith("колесо"))
async def wheel_start(m: types.Message):
    if m.chat.id != X50_CHAT_ID: 
        return await m.reply("❌ Игра доступна только в официальном чате!")
    
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    
    # Парсим ставку
    bet = parse_bet(args[1] if len(args) > 1 else "0", u[2])
    
    if bet < 100: 
        return await m.reply("❌ Минимальная ставка — <b>100</b> лир!", parse_mode="HTML")
    if u[2] < bet:
        return await m.reply("❌ У вас недостаточно лир!")

    # Списываем ставку
    upd_bal(u[0], -bet)
    
    # Анимация кручения
    msg = await m.reply(
        f"🎡 <b>{u[1]}</b> запускает колесо...\n"
        f"🎰 Ставка: <b>{bet:,}</b> лир\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"🔄 <code>[ 🔴 🔵 🟡 🟣 ⚪️ ]</code>", 
        parse_mode="HTML"
    )
    
    await asyncio.sleep(1.5)
    
    # Выбор результата на основе весов
    sector_icons = [s[0] for s in WHEEL_SECTORS]
    weights = [s[2] for s in WHEEL_SECTORS]
    res_sector = random.choices(WHEEL_SECTORS, weights=weights, k=1)[0]
    
    icon, mult, _ = res_sector
    win_amount = int(bet * mult)
    
    # Если выиграл, зачисляем
    if win_amount > 0:
        upd_bal(u[0], win_amount)

    # Финальный текст как на твоих скринах
    text = f"🎡 <b>КОЛЕСО ФОРТУНЫ</b>\n"
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    text += f"👤 Игрок: <b>{u[1]}</b>\n"
    text += f"💵 Ставка: <b>{bet:,}</b>\n"
    text += f"🎯 Выпало: {icon} (<b>x{mult}</b>)\n"
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    if win_amount > bet:
        text += f"✅ <b>ВЫИГРЫШ: {win_amount:,} лир!</b>"
    elif win_amount == bet:
        text += f"⚖️ <b>ВЫШЛИ В НОЛЬ!</b>"
    elif win_amount > 0:
        text += f"⚠️ <b>ЧАСТИЧНЫЙ ВОЗВРАТ: {win_amount:,} лир</b>"
    else:
        text += f"❌ <b>ПРОИГРЫШ! Попробуйте снова.</b>"

    await msg.edit_text(text, parse_mode="HTML")


# --- ФЛИП И ОХОТА ---
@dp.message(F.text.lower().startswith("флип"))
async def flip_start(m: types.Message):
    bet = 100 # Твой parse_bet
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="🪙 Орел", callback_data=f"flip_1_{bet}"),
        types.InlineKeyboardButton(text="🦅 Решка", callback_data=f"flip_2_{bet}")
    )
    kb.row(types.InlineKeyboardButton(text="🔄 Автовыбор", callback_data=f"flip_3_{bet}"))
    
    await m.reply(
        f"Вы начали игру в Монетку!\nСтавка: <b>{bet}</b> лир\nКоэффициент: <b>x1.9</b>\nВыберите сторону: ❓",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("flip_"))
async def flip_cb(call: types.CallbackQuery):
    _, choice, bet = call.data.split("_")
    bet = int(bet)
    result = random.choice(["1", "2"]) # 1 - Орел, 2 - Решка
    user_choice = choice if choice != "3" else random.choice(["1", "2"])
    
    win = user_choice == result
    res_text = "🪙 Орел" if result == "1" else "🦅 Решка"
    
    if win:
        upd_bal(call.from_user.id, int(bet * 1.9))
        text = f"✅ Выпало {res_text}! Вы выиграли <b>{int(bet*1.9)}</b>!"
    else:
        text = f"❌ Выпало {res_text}! Вы проиграли."
        
    await call.message.edit_text(text, parse_mode="HTML")
    
@dp.message(F.text.lower().startswith("охота"))
async def hunt(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name); bet = parse_bet(m.text.split()[1] if len(m.text.split())>1 else "0", u[2])
    if bet < 100: return
    upd_bal(u[0], -bet); await m.answer("🏹 Охотимся..."); await asyncio.sleep(2)
    if random.random() < 0.4:
        w = int(bet*2.5); upd_bal(u[0], w); await m.answer(f"🎯 Попал! {get_link(u)} +{w:,}", parse_mode="Markdown")
    else: await m.answer(f"💨 Мимо! {get_link(u)} -{bet:,}", parse_mode="Markdown")

# --- ПРОМОКОДЫ ---
@dp.message(F.text.lower().startswith(("промо", "/promo")))
async def promo_act(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name); args = m.text.split()
    if len(args) < 2: return await m.reply("📖 `промо [код]`")
    code = args[1].upper()
    cur.execute("SELECT amount, uses FROM promo WHERE code=?", (code,))
    p = cur.fetchone()
    if not p: return await m.reply("❌ Нет такого промо!")
    cur.execute("SELECT * FROM promo_history WHERE uid=? AND code=?", (u[0], code))
    if cur.fetchone(): return await m.reply("⚠️ Уже активирован!")
    if p[1] <= 0: return await m.reply("❌ Активации закончились!")
    upd_bal(u[0], p[0]); cur.execute("UPDATE promo SET uses=uses-1 WHERE code=?", (code,))
    cur.execute("INSERT INTO promo_history VALUES (?,?)", (u[0], code)); conn.commit()
    await m.answer(f"✅ Активирован! +{p[0]:,} лир.")

@dp.message(Command("admin"))
async def adm_panel(m: types.Message):
    if m.from_user.id not in ADMIN_ID: return
    
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Выдать", callback_data="adm_give")
    kb.button(text="👥 Юзеры", callback_data="adm_users") # Новая кнопка
    kb.button(text="🎁 Промо", callback_data="adm_promo")
    kb.button(text="📢 Рассылка", callback_data="adm_mail")
    kb.button(text="⚡️ Фаст", callback_data="adm_fast")
    kb.button(text="❓ Викторина", callback_data="adm_vik")
    kb.button(text="♻️ Сброс ТОП", callback_data="adm_reset_top")
    kb.adjust(2)
    await m.answer("⚙️ **ПАНЕЛЬ УПРАВЛЕНИЯ**", reply_markup=kb.as_markup(), parse_mode="Markdown")

# --- ЛОГИКА ВЫДАЧИ (Исправлено по запросу) ---
@dp.callback_query(F.data == "adm_give")
async def adm_give_1(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("👤 Введите **ID пользователя**, которому хотите выдать лиры:")
    await state.set_state(AdminStates.give_id)

@dp.message(AdminStates.give_id)
async def adm_give_2(m: types.Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.reply("❌ Введите корректный числовой ID!")
    await state.update_data(target_id=int(m.text))
    await m.answer("💰 Теперь введите **сумму** (можно использовать 'к'):")
    await state.set_state(AdminStates.give_amount)

@dp.message(AdminStates.give_amount)
async def adm_give_3(m: types.Message, state: FSMContext):
    summ_text = m.text.lower().replace("к", "000").replace("k", "000")
    if not summ_text.isdigit():
        return await m.reply("❌ Введите число!")
    
    data = await state.get_data()
    target_id = data['target_id']
    amount = int(summ_text)
    
    try:
        upd_bal(target_id, amount)
        await m.answer(f"✅ Успешно выдано **{amount:,}** лир пользователю `{target_id}`")
        await bot.send_message(target_id, f"💳 Администратор выдал вам **{amount:,}** лир!")
    except Exception as e:
        await m.answer(f"❌ Ошибка: {e}")
    await state.clear()

# --- ЛОГИКА ПРОМОКОДОВ ---
@dp.callback_query(F.data == "adm_promo")
async def adm_p1(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("📝 Введите название промокода:")
    await state.set_state(AdminStates.promo_name)

@dp.message(AdminStates.promo_name)
async def adm_p2(m: types.Message, state: FSMContext):
    await state.update_data(p_n=m.text.upper())
    await m.answer("💰 Сумма активации:")
    await state.set_state(AdminStates.promo_sum)

@dp.message(AdminStates.promo_sum)
async def adm_p3(m: types.Message, state: FSMContext):
    if not m.text.isdigit(): return await m.reply("❌ Введите число")
    await state.update_data(p_s=int(m.text))
    await m.answer("👥 Количество использований:")
    await state.set_state(AdminStates.promo_uses)

@dp.message(AdminStates.promo_uses)
async def adm_p4(m: types.Message, state: FSMContext):
    if not m.text.isdigit(): return await m.reply("❌ Введите число")
    d = await state.get_data()
    n, s, u = d['p_n'], d['p_s'], int(m.text)
    cur.execute("INSERT INTO promo VALUES (?,?,?)", (n, s, u))
    conn.commit()
    await m.answer(f"✅ Промокод `{n}` создан!")
    await bot.send_message(X50_CHAT_ID, f"🎁 **НОВЫЙ ПРОМОКОД!**\n\n🎫 Код: `{n}`\n💰 Сумма: {s:,}\n👤 Активаций: {u}", parse_mode="Markdown")
    await state.clear()

# --- ЛОГИКА РАССЫЛКИ ---
@dp.callback_query(F.data == "adm_mail")
async def adm_m1(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("📨 Введите текст рассылки для всех пользователей:")
    await state.set_state(AdminStates.mailing_text)

@dp.message(AdminStates.mailing_text)
async def adm_m2(m: types.Message, state: FSMContext):
    cur.execute("SELECT uid FROM users")
    users = cur.fetchall()
    count = 0
    await m.answer(f"🚀 Рассылка запущена на {len(users)} чел...")
    for u in users:
        try:
            await bot.send_message(u[0], m.text)
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    await m.answer(f"✅ Рассылка завершена! Получили: {count} чел.")
    await state.clear()

# --- ЛОГИКА ФАСТ КОНКУРСА (ФК) ---
@dp.callback_query(F.data == "adm_fast")
async def adm_f1(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("💰 <b>Введите сумму для ФАСТ КОНКУРСА:</b>\n(Например: 50000 или 50к)", parse_mode="HTML")
    await state.set_state(AdminStates.fast_amount)

@dp.message(AdminStates.fast_amount)
async def fast_publish(m: types.Message, state: FSMContext):
    # Убираем "к" или "k", если ввели текстом
    summ_text = m.text.lower().replace("к", "000").replace("k", "000").strip()
    
    if not summ_text.isdigit():
        return await m.reply("❌ <b>Введите число!</b>", parse_mode="HTML")
    
    amount = int(summ_text)
    await state.clear() # Очищаем состояние ПЕРЕД публикацией
    
    kb = InlineKeyboardBuilder()
    kb.button(text="💝 ЗАБРАТЬ", callback_data=f"take_fc_{amount}")
    
    await bot.send_message(
        X50_CHAT_ID,
        f"🎁 <b>ФАСТ КОНКУРС</b>\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"УСПЕЙ ПЕРВЫМ НАЖАТЬ НА КНОПКУ!\n\n"
        f"💰 Сумма: <b>{amount:,}</b> лир\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await m.answer(f"✅ <b>ФК на {amount:,} лир запущен!</b>", parse_mode="HTML")

# --- ОБРАБОТКА КНОПКИ ФК ---
@dp.callback_query(F.data.startswith("take_fc_"))
async def take_fast_contest(call: types.CallbackQuery):
    # Извлекаем сумму
    try:
        amount = int(call.data.split("_")[2])
    except:
        return await call.answer("❌ Ошибка данных конкурса")

    # Проверка: не завершен ли конкурс (смотрим на текст сообщения)
    if "ЗАВЕРШЕН" in (call.message.text or ""):
        return await call.answer("❌ Этот приз уже забрали!", show_alert=True)

    try:
        # Сразу отвечаем пользователю, чтобы кнопка не "зависала"
        await call.answer("🎉 Проверка...")

        # Получаем пользователя и обновляем баланс (используем ваши функции)
        u = get_u(call.from_user.id, call.from_user.full_name)
        upd_bal(u[0], amount)
        
        # РЕДАКТИРУЕМ СООБЩЕНИЕ (Ставим флаг ЗАВЕРШЕН первым делом)
        await call.message.edit_text(
            f"✅ <b>ФАСТ КОНКУРС ЗАВЕРШЕН</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Победитель: <b>{call.from_user.full_name}</b>\n"
            f"💰 Сумма: <b>{amount:,}</b> лир\n"
            f"━━━━━━━━━━━━━━\n"
            f"Лиры зачислены на баланс!",
            parse_mode="HTML"
        )
        
    except Exception as e:
        print(f"Ошибка в ФК: {e}")
        await call.answer("❌ Произошла ошибка или вы не успели!", show_alert=False)
        
# --- ЛОГИКА ВИКТОРИНЫ ---
@dp.callback_query(F.data == "adm_vik")
async def adm_v1(c: types.CallbackQuery, state: FSMContext):
    await c.message.answer("💰 <b>Шаг [1/3]:</b> Введите сумму приза:")
    await state.set_state(AdminStates.vik_amount)

@dp.message(AdminStates.vik_amount)
async def vik_get_amount(m: types.Message, state: FSMContext):
    summ_text = m.text.lower().replace("к", "000").replace("k", "000").strip()
    if not summ_text.isdigit():
        return await m.reply("❌ <b>Введите число!</b>")
    
    await state.update_data(amount=int(summ_text))
    await m.answer("❓ <b>Шаг [2/3]:</b> Введите ВОПРОС викторины:")
    await state.set_state(AdminStates.vik_question)

@dp.message(AdminStates.vik_question)
async def vik_get_question(m: types.Message, state: FSMContext):
    await state.update_data(question=m.text)
    await m.answer("📝 <b>Шаг [3/3]:</b> Введите ПРАВИЛЬНЫЙ ОТВЕТ:")
    await state.set_state(AdminStates.vik_answer)

@dp.message(AdminStates.vik_answer)
async def vik_get_answer(m: types.Message, state: FSMContext):
    data = await state.get_data()
    
    # Записываем в глобальный словарь (убедись, что active_vik создан в начале кода)
    active_vik["amount"] = data['amount']
    active_vik["question"] = data['question']
    active_vik["answer"] = m.text.lower().strip()
    active_vik["is_active"] = True
    
    await bot.send_message(
        X50_CHAT_ID, 
        f"🎁 <b>ВИКТОРИНА!</b>\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"❓ Вопрос: <b>{active_vik['question']}</b>\n\n"
        f"💰 Приз: <b>{active_vik['amount']:,}</b> лир\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"Кто первым напишет правильный ответ?",
        parse_mode="HTML"
    )
    await m.answer("✅ <b>Викторина запущена!</b>")
    await state.clear()
    
# --- СБРОС ТОПА ---
@dp.callback_query(F.data == "adm_reset_top")
async def adm_rt(c: types.CallbackQuery):
    cur.execute("UPDATE users SET daily = 0")
    conn.commit()
    await c.message.answer("✅ Ежедневный ТОП успешно обнулен!")
    await c.answer()

# --- ПРОВЕРКА ОТВЕТА ВИКТОРИНЫ ---
@dp.message(lambda m: active_vik.get("is_active") == True)
async def check_vik_answer(m: types.Message):
    # Проверяем, что ответ в нужном чате
    if m.chat.id != X50_CHAT_ID: 
        return

    # Если текста нет (например, прислали стикер) — игнорим
    if not m.text:
        return

    user_answer = m.text.lower().strip()
    correct_answer = str(active_vik["answer"]).lower().strip()

    if user_answer == correct_answer:
        # Мгновенно выключаем активность, чтобы не было 2-х победителей
        active_vik["is_active"] = False 
        
        try:
            u = get_u(m.from_user.id, m.from_user.full_name)
            upd_bal(u[0], active_vik["amount"])
            
            await m.reply(
                f"🎊 <b>ЕСТЬ ПОБЕДИТЕЛЬ!</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"👤 <b>{m.from_user.full_name}</b> ответил правильно: <code>{active_vik['answer']}</code>\n"
                f"💰 Приз <b>{active_vik['amount']:,}</b> лир зачислен!\n"
                f"━━━━━━━━━━━━━━",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Ошибка в выдаче викторины: {e}")

# Нажали "Юзеры" -> просим ID
# Количество игроков на одной странице
USERS_PER_PAGE = 10

@dp.callback_query(F.data.startswith("adm_users"))
async def adm_users_list(call: types.CallbackQuery):
    # Определяем текущую страницу
    data = call.data.split("_")
    page = int(data[2]) if len(data) > 2 else 0
    offset = page * USERS_PER_PAGE

    # Получаем срез игроков из БД
    cur.execute("SELECT uid, name FROM users LIMIT ? OFFSET ?", (USERS_PER_PAGE, offset))
    users = cur.fetchall()

    # Считаем общее количество для навигации
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    kb = InlineKeyboardBuilder()

    # Создаем кнопки для каждого игрока
    for uid, name in users:
        kb.button(text=f"👤 {name} (ID: {uid})", callback_data=f"u_control_{uid}")
    
    kb.adjust(1) # Список в одну колонку

    # Кнопки управления страницами
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⏪ Назад", callback_data=f"adm_users_{page-1}"))
    
    # Кнопка текущей страницы
    nav_buttons.append(types.InlineKeyboardButton(text=f"📄 {page+1}", callback_data="none"))
    
    if offset + USERS_PER_PAGE < total_users:
        nav_buttons.append(types.InlineKeyboardButton(text="⏩ Вперед", callback_data=f"adm_users_{page+1}"))
    
    kb.row(*nav_buttons)
    kb.row(types.InlineKeyboardButton(text="🔙 В админку", callback_data="admin_main"))

    text = f"👥 <b>СПИСОК ИГРОКОВ</b>\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\nВсего в базе: <b>{total_users}</b>"
    
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    
        
@dp.callback_query(F.data.startswith("u_control_"))
async def adm_user_manage(call: types.CallbackQuery):
    target_id = int(call.data.split("_")[2])
    # Получаем данные: [1]-имя, [2]-бал, [10]-бан, [11]-банк
    user = get_u(target_id, "Игрок") 
    
    if not user:
        return await call.answer("❌ Игрок не найден!", show_alert=True)

    bal = user[2]
    bank = user[11] if len(user) > 11 else 0
    is_banned = "🔴 ЗАБАНЕН" if user[10] == 1 else "🟢 Активен"
    
    text = (
        f"👤 <b>УПРАВЛЕНИЕ ИГРОКОМ</b>\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"📝 Ник: <b>{user[1]}</b>\n"
        f"💰 Баланс: <b>{bal:,}</b>\n"
        f"🏦 В банке: <b>{bank:,}</b>\n"
        f"📊 Статус: {is_banned}\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🧹 Обнулить всё", callback_data=f"u_reset_{target_id}")
    kb.button(text="📜 Логи", callback_data=f"u_logs_{target_id}")
    kb.button(text="🚫 Бан/Разбан", callback_data=f"u_ban_{target_id}")
    kb.button(text="💰 Выдать", callback_data=f"u_give_{target_id}")
    kb.button(text="🔙 Назад к списку", callback_data="adm_users_0")
    kb.adjust(1)

    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ИСПРАВЛЕННЫЙ БЛОК ДЕЙСТВИЙ (без SyntaxError)
@dp.callback_query(F.data.startswith("u_"))
async def adm_u_actions(call: types.CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    action = data[1]
    tid = int(data[2])

    if action == "reset":
        cur.execute("UPDATE users SET bal = 0, bank = 0, daily = 0 WHERE uid = ?", (tid,))
        conn.commit()
        await call.answer("🧹 Баланс и банк обнулены!", show_alert=True)
        await adm_user_manage(call) # Обновляем карточку игрока

    elif action == "ban":
        cur.execute("SELECT banned FROM users WHERE uid = ?", (tid,))
        res = cur.fetchone()
        new_status = 1 if res[0] == 0 else 0
        cur.execute("UPDATE users SET banned = ? WHERE uid = ?", (new_status, tid))
        conn.commit()
        await call.answer("✅ Статус изменен!", show_alert=True)
        await adm_user_manage(call) # Обновляем карточку игрока

    elif action == "give":
        await state.update_data(target_id=tid)
        await call.message.answer(f"💰 Введите сумму для <b>{tid}</b> (можно с 'к'):", parse_mode="HTML")
        await state.set_state(AdminStates.give_amount)
#
@dp.callback_query(F.data.startswith("u_logs_"))
async def adm_view_logs(call: types.CallbackQuery):
    tid = int(call.data.split("_")[2])
    
    # Обязательно отвечаем на колбэк в самом начале, чтобы кнопка не лагала
    await call.answer()

    cur.execute("SELECT game, amount, result, date FROM logs WHERE uid = ? ORDER BY id DESC LIMIT 10", (tid,))
    rows = cur.fetchall()
    
    if not rows:
        return await call.message.answer(f"📜 У игрока {tid} пока нет истории игр.")
    
    text = f"📜 <b>ИСТОРИЯ ОПЕРАЦИЙ (ID: {tid})</b>\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    for r in rows:
        date_str = r[3][5:16].replace("-", ".") 
        text += f"📅 <code>{date_str}</code> | <b>{r[0]}</b>\n💰 {r[1]:,} | {r[2]}\n\n"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data=f"u_control_{tid}")
    
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest:
        pass # Если логи не изменились, ничего не делаем    




        
@dp.message((F.text == "👤 Профиль") | (F.text.lower() == "профиль"))
async def profile_handler(m: types.Message):
    # Если реплай — смотрим чужой профиль, иначе свой
    target = m.reply_to_message.from_user if m.reply_to_message else m.from_user
    
    cur.execute("""SELECT uid, name, bal, reg, level, used_limit, bank, reputation, bio, hide_bal, hide_bank 
                   FROM users WHERE uid = ?""", (target.id,))
    u = cur.fetchone()
    
    if not u: 
        return await m.reply("❌ Игрок еще не зарегистрирован в боте.")

    uid, name, bal, reg, lv, used, bank, rep, bio, h_bal, h_bank = u
    
    # Логика скрытия (владелец профиля всегда видит свои цифры, остальные — "Скрыто")
    is_owner = m.from_user.id == uid
    bal_display = f"{bal:,} лир" if (h_bal == 0 or is_owner) else "🔒 Скрыто"
    bank_display = f"{bank:,} лир" if (h_bank == 0 or is_owner) else "🔒 Скрыто"
    
    # Лимиты
    max_l = LEVELS[lv]["limit"]
    remains = max(0, max_l - used)
    limit_val = f"{remains:,}" if lv < 10 else "Безлимит"

    text = (
        f"👤 **ПРОФИЛЬ ИГРОКА**\n\n"
        f"🎭 Ник: **{name}**\n"
        f"🆔 ID: `{uid}`\n"
        f"📝 Описание: {bio}\n\n"
        f"💰 **ФИНАНСЫ**\n"
        f"├ 💰 Баланс: **{bal_display}**\n"
        f"├ 🏦 Банк: **{bank_display}**\n"
        f"├ ⭐ LVL лимита: **{lv}**\n"
        f"├ 💳 Лимит: **{limit_val}** лир\n"
        f"└ 🔒 Кошелёк: {'Закрыт' if h_bal == 1 else 'Открыт'}\n\n"
        f"📈 **ПРОГРЕСС**\n"
        f"└ 🫡 Репутация: **{rep}**\n\n"
        f"📅 Регистрация: {reg}"
    )
    await m.answer(text, parse_mode="Markdown")
    

# Изменить описание
@dp.message(F.text.lower().startswith("+описание "))
async def set_bio(m: types.Message):
    new_bio = m.text[10:].strip()
    if len(new_bio) > 100: return await m.reply("❌ Описание слишком длинное (макс 100 симв.)")
    cur.execute("UPDATE users SET bio = ? WHERE uid = ?", (new_bio, m.from_user.id))
    conn.commit()
    await m.reply("✅ Описание успешно обновлено!")

# Скрыть/Показать баланс или банк
@dp.message(F.text.lower().startswith("скрыть "))
async def hide_info(m: types.Message):
    what = m.text.lower().split()[1]
    col = "hide_bal" if what == "б" else "hide_bank" if what == "банк" else None
    if not col: return
    
    cur.execute(f"UPDATE users SET {col} = 1 WHERE uid = ?", (m.from_user.id,))
    conn.commit()
    await m.reply(f"🔒 Вы скрыли свой {what} в профиле!")

@dp.message(F.text.lower().startswith("открыть ")) # Доп. функция для возврата
async def show_info(m: types.Message):
    what = m.text.lower().split()[1]
    col = "hide_bal" if what == "б" else "hide_bank" if what == "банк" else None
    if not col: return
    
    cur.execute(f"UPDATE users SET {col} = 0 WHERE uid = ?", (m.from_user.id,))
    conn.commit()
    await m.reply(f"🔓 Ваш {what} снова виден всем!")

@dp.message((F.text.lower().startswith("+реп")) | (F.text.lower().startswith("-реп")))
async def change_rep(m: types.Message):
    if not m.reply_to_message: return await m.reply("❌ Ответьте на сообщение игрока!")
    if m.reply_to_message.from_user.id == m.from_user.id: return await m.reply("❌ Нельзя менять репутацию себе!")
    
    try:
        val = int(m.text.split()[1])
        if val < 1 or val > 150: return await m.reply("❌ Сумма репутации должна быть от 1 до 150!")
    except: return await m.reply("❌ Формат: `+реп 50` или `-реп 50`")

    sign = 1 if "+реп" in m.text.lower() else -1
    total_change = val * sign
    
    cur.execute("UPDATE users SET reputation = reputation + ? WHERE uid = ?", (total_change, m.reply_to_message.from_user.id))
    conn.commit()
    
    status = "повысил" if sign > 0 else "понизил"
    await m.answer(f"🫡 Вы {status} репутацию игроку на **{val}**!")

import re

# Вспомогательная функция для обработки сумм (чтобы работало "банк положить все" или "банк положить 1к")
def parse_amount(text, user_bal):
    text = text.lower().replace('к', '000').replace('k', '000').replace(',', '').replace(' ', '')
    if text in ["все", "всё", "all"]:
        return user_bal
    if text.endswith('%'):
        pct = int(text.replace('%', ''))
        return int(user_bal * pct / 100)
    return int(text)

@dp.message(F.text.lower().startswith("банк"))
async def bank_handler(m: types.Message):
    # Получаем данные игрока: uid[0], name[1], balance[2], bank[6] (проверь индекс bank в своем SELECT)
    # Предположим, твоя функция get_u возвращает список, где balance - это индекс 2
    u = get_u(m.from_user.id, m.from_user.full_name)
    uid = u[0]
    user_balance = u[2]
    
    # Получаем актуальный баланс банка напрямую из БД
    cur.execute("SELECT bank FROM users WHERE uid = ?", (uid,))
    user_bank = cur.fetchone()[0]

    args = m.text.split()

    # 1. Просто команда "банк" — показываем баланс
    if len(args) == 1:
        return await m.reply(
            f"🏦 **Ваш банковский счёт**\n\n"
            f"💰 В хранилище: **{user_bank:,}** лир\n\n"
            f"ℹ️ Чтобы положить: `банк положить [сумма]`\n"
            f"ℹ️ Чтобы снять: `банк снять [сумма]`",
            parse_mode="Markdown"
        )

    # Проверяем, что есть действие и сумма
    if len(args) < 3:
        return await m.reply("❌ Используйте: `банк положить/снять [сумма]`")

    action = args[1].lower()
    amount_raw = args[2]

    try:
        # Если кладем — считаем от баланса на руках, если снимаем — от баланса в банке
        limit = user_balance if action == "положить" else user_bank
        amount = parse_amount(amount_raw, limit)
        
        if amount <= 0:
            return await m.reply("❌ Сумма должна быть больше 0!")
    except:
        return await m.reply("❌ Ошибка! Введите сумму числом или напишите 'все'.")

    # 2. Логика "банк положить"
    if action in ["положить", "внести", "депозит"]:
        if user_balance < amount:
            return await m.reply(f"❌ У вас на руках только **{user_balance:,}** лир.")
        
        # Обновляем БД
        upd_bal(uid, -amount) # Снимаем с рук (твоя функция)
        cur.execute("UPDATE users SET bank = bank + ? WHERE uid = ?", (amount, uid))
        conn.commit()
        
        await m.reply(f"✅ Вы успешно положили в банк **{amount:,}** лир.")

    # 3. Логика "банк снять"
    elif action in ["снять", "вывести"]:
        if user_bank < amount:
            return await m.reply(f"❌ В банке недостаточно средств (у вас там **{user_bank:,}** лир).")
        
        # Обновляем БД
        cur.execute("UPDATE users SET bank = bank - ? WHERE uid = ?", (amount, uid))
        upd_bal(uid, amount) # Добавляем на руки
        conn.commit()
        
        await m.reply(f"✅ Вы успешно сняли из банка **{amount:,}** лир.")
    
    else:
        await m.reply("❌ Неизвестная операция. Используйте `положить` или `снять`.")
        
@dp.message(F.text.lower().in_(["топ", "🏆 Топ игроки", "/top_day"]))
async def top_daily_win(m: types.Message):
    # Берем топ 5 по колонке daily (где мы теперь храним чистый плюс)
    cur.execute("SELECT name, daily FROM users WHERE daily > 0 ORDER BY daily DESC LIMIT 5")
    rows = cur.fetchall()
    
    if not rows:
        return await m.reply("📊 <b>Топ дня пока пуст.</b>\nСтаньте первым, кто уйдет в плюс!", parse_mode="HTML")
    
    text = "🏆 <b>ЛИДЕРЫ ДНЯ (ПРИБЫЛЬ)</b>\n"
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, row in enumerate(rows):
        name, profit = row
        text += f"{medals[i]} <b>{name}</b> — <b>+{profit:,}</b> лир\n"
        
    text += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    text += "<i>Показывает чистый плюс за 24ч</i>"
    
    await m.answer(text, parse_mode="HTML")

    
@dp.message(F.text.lower().in_(["🎁 бонус", "бонус"]))
async def bonus_cmd(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name)
    now = datetime.now()
    
    # Проверка на КД (24 часа)
    # u[7] — это столбец 'bonus' в твоей таблице users
    if u[7]:
        last_bonus_time = datetime.strptime(u[7], "%Y-%m-%d %H:%M:%S")
        if last_bonus_time + timedelta(hours=24) > now:
            # Считаем, сколько осталось ждать
            remaining = (last_bonus_time + timedelta(hours=24)) - now
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds // 60) % 60
            return await m.reply(f"❌ Вы уже забирали бонус!\nПриходите через **{hours}ч. {minutes}мин.**")

    # Генерируем случайную сумму от 1000 до 5000
    gift = random.randint(1000, 5000)
    
    # Обновляем баланс и время бонуса
    # Мы используем upd_bal для начисления денег
    upd_bal(u[0], gift)
    
    # Записываем время получения бонуса в базу
    cur.execute("UPDATE users SET bonus = ? WHERE uid = ?", (now.strftime("%Y-%m-%d %H:%M:%S"), u[0]))
    conn.commit()
    
    await m.reply(f"🎁 {get_link(u)}, вы получили ежедневный бонус **{gift:,}** лир!", parse_mode="Markdown")

@dp.message(F.text.lower().in_(["📍 помощь", "помощь"]))
async def help_cmd(m: types.Message):
    # Тег <blockquote> открывается в начале и закрывается в самом конце
    help_text = (
        "📍 <b>Помощь</b>\n\n"
        "<blockquote>"
        "<b>🎮 Игры:</b>\n"
        "🎡<b>Х50 [ставка] [исход] ч,ф,к,з</b>\n"
        "💣<b>Мины [ставка] [кол мины]</b>\n"
        "🧮<b>Хл [ставка]</b>\n"
        "🐊<b>Охота [ставка]</b>\n"
        "🪙<b>Флип [ставка]</b>\n"
        "🏀<b>Баскетбол [ставка]</b>\n"
        "⚽️<b>Футбол [ставка]</b>\n"
        "🎳<b>Боулинг [ставка]</b>\n"
        "🎰<b>Спин [ставка]</b>\n"
        "🐸<b>Жаба [ставка]</b>\n"
        "🔫<b>Рулетка [ставка] [исход]</b>\n"
        "🗼<b>Башня [ставка] [кол мины]</b>\n"
        "🏴‍☠️<b>Пират [ставка] [1-2]</b>\n\n"
        "🔑 <b>Ключевые команды:</b>\n"
        "<b>Б</b> — баланс игрока\n"
        "<b>Топ</b> — Топ 10 игроков\n"
        "<b>Дать [сумма]</b> на ответ игрока — передача валюты\n"
        "<b>Помощь</b> — помощь\n"
        "<b>Шар [текст]</b> — шар ответит рандомно\n"
        "<b>Промо [код]</b> — активировать промо\n\n"
        "<b>📞 Контакты</b>\n"
        "🛎️ <b>Новостной Канал</b> — @LiraGameNews\n"
        "💬 <b>Основной Чат</b> — @Lirachatik\n"
        "🧑‍💻 <b>Основатель</b> — @ren1ved"
        "</blockquote>"
    )
    
    await m.answer(help_text, parse_mode="HTML")

@dp.message(F.text == "➕ Добавить")
async def add_bot_to_chat(m: types.Message):
    # Создаем инлайн-кнопку со ссылкой
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(
        text="➕ Добавить в чат", 
        url="https://t.me/LiraGame_Bot?startgroup=0")
    )
    
    # Отправляем сообщение
    await m.answer(
        "🤖 **Добавьте бота в чат!**\n\n"

             "Чтобы начать играть с друзьями, нажмите кнопку ниже и выберите свою группу. "
        "Не забудьте выдать боту права администратора.",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown"
    )

# --- ЛОГИКА ОВЕРГО (ОБЛЕГЧЕННАЯ ВЕРСИЯ) ---

@dp.message(F.text.lower().startswith("оверго"))
async def game_overgo(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    
    # Проверка аргументов
    if len(args) < 3:
        return await m.reply("📖 Формат: **Оверго [ставка] [коэф]**\nПример: `Оверго 100 2.0`", parse_mode="Markdown")
    
    bet = parse_bet(args[1], u[2])
    try:
        target_coef = float(args[2].replace(",", "."))
    except:
        return await m.reply("❌ Укажите корректный **коэффициент**!")

    if bet < 100: return await m.reply("❌ Минимальная ставка — **100** лир!")
    if target_coef <= 1.0: return await m.reply("❌ Коэффициент должен быть выше **1.0**!")

    # --- ОБЛЕГЧЕННЫЙ RTP ---
    # Шанс моментального слива (1.0x) теперь всего 3-5%
    if random.random() < 0.04: 
        crash_point = 1.0
    else:
        # Улучшенная формула: теперь чаще выпадают играбельные иксы
        # Мы берем случайное число и "вытягиваем" его в сторону средних значений
        base = random.uniform(0.1, 1.0)
        crash_point = round(0.98 / base, 2)
        
        # Ограничиваем слишком огромные иксы, чтобы не разорить банк бота
        if crash_point > 100: crash_point = round(random.uniform(50, 100), 2)

    # Небольшая пауза для эффекта ожидания
    await asyncio.sleep(0.8)

    if crash_point >= target_coef:
        # ✅ ПОБЕДА
        win_sum = int(bet * target_coef) - bet
        upd_bal(u[0], win_sum)
        
        text = (
            f"🎮 Игра: **ОверГо**\n"
            f"🎢 График: **{crash_point}x**\n\n"
            f"✅ **Победа!**\n"
            f"💰 Вы выиграли: **{int(bet * target_coef):,}** лир"
        )
    else:
        # 💥 ПОРАЖЕНИЕ
        upd_bal(u[0], -bet)
        
        text = (
            f"🎮 Игра: **ОверГо**\n"
            f"🎢 График: **{crash_point}x**\n\n"
            f"💥 **Поражение.**\n"
            f"📉 Вы проиграли: **{bet:,}** лир"
        )

    await m.reply(text, parse_mode="Markdown")
 

# Глобальная переменная для хранения активной викторины
active_vik = {
    "is_active": False,
    "amount": 0,
    "question": "",
    "answer": ""
}

# --- ИГРА ПИРАТ ---
@dp.message(F.text.lower().startswith("пират"))
async def pirate_start(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    
    bet = parse_bet(args[1] if len(args) > 1 else "0", u[2])
    if bet < 100: return await m.reply("❌ Ставка от **100** лир!")
    
    # Количество сокровищ (по умолчанию 1, если не указано 2)
    treasures = 2 if len(args) > 2 and args[2] == "2" else 1
    coef = 1.44 if treasures == 2 else 2.88
    
    # Списываем ставку
    upd_bal(u[0], -bet)
    
    kb = InlineKeyboardBuilder()
    for i in range(1, 4):
        kb.button(text=f"💀 {i}", callback_data=f"pirate_play_{i}_{treasures}_{bet}")
    kb.button(text="🤖 Авто-выбор", callback_data=f"pirate_play_auto_{treasures}_{bet}")
    kb.adjust(3, 1)
    
    await m.answer(
        f"⚓️ Игра в **Brawl Pirate**!\n"
        f"💰 Ставка: **{bet:,}** лир\n"
        f"🎁 Сокровищ: **{treasures}** (Коэффициент: **x{coef}**)\n"
        f"💀 Выберите 1 из 3 черепов!",
        reply_markup=kb.as_markup(), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("pirate_play_"))
async def pirate_callback(call: types.CallbackQuery):
    data = call.data.split("_")
    choice = data[2]
    treasures = int(data[3])
    bet = int(data[4])
    
    if choice == "auto":
        choice = random.randint(1, 3)
    else:
        choice = int(choice)
        
    # Логика шанса: если 1 сокровище — шанс 1/3, если 2 — шанс 2/3
    is_win = random.random() < (treasures / 3)
    coef = 1.44 if treasures == 2 else 2.88
    
    if is_win:
        # Зачисляем полную сумму ставки * коэффициент
        win_total = int(bet * coef)
        upd_bal(call.from_user.id, win_total)
        
        text = (f"💎 **Вы нашли сокровище!**\n\n"
                f"🎰 Выбор пал на череп №{choice}\n"
                f"📈 Коэффициент: **x{coef}**\n"
                f"🏆 Выигрыш: **{win_total:,}** лир")
    else:
        text = (f"💀 **Там было пусто...**\n\n"
                f"🎰 Выбор пал на череп №{choice}\n"
                f"📉 Проигрыш: **{bet:,}** лир")
                
    await call.message.edit_text(text, reply_markup=None, parse_mode="Markdown")

@dp.message(F.text.lower().startswith(("шар", "вероятность")))
async def magic_ball(m: types.Message):
    answers = [
        "🔮 Я думаю — Нет",
        "🔮 Мне кажется — Нет",
        "🔮 Думаю — Да",
        "🔮 Знаки говорят — Да",
        "🔮 Вероятность крайне мала",
        "🔮 Скорее всего — Да",
        "🔮 Звезды говорят — Нет",
        "🔮 Определенно — Да"
    ]
    await m.reply(random.choice(answers))

import random

import random

@dp.message(F.text.lower().startswith("шанс"))
async def chance_cmd(m: types.Message):
    # Генерируем случайное число от 1 до 100
    percent = random.randint(1, 100)
    
    # Формируем текст строго по твоему запросу
    text = f"🎱 <b>Шанс этого {percent}%</b>"
    
    # Отвечаем реплаем на сообщение пользователя
    await m.reply(text, parse_mode="HTML")

import re
import random
import time
import sqlite3
from aiogram import types, F

# --- КОНФИГУРАЦИЯ ---
RED_NUMS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

# Разрешенные текстовые типы ставок
VALID_TYPES = {
    'к': 'красное', 'красное': 'красное',
    'ч': 'черное', 'черное': 'черное',
    'з': 'зеро', 'зеро': 'зеро', '0': 'зеро',
    'евен': 'чет', 'чет': 'чет',
    'одд': 'нечет', 'нечет': 'нечет',
    'м': '1-18', 'б': '19-36'
}

roulette_games = {}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def log_roulette_result(num, emoji):
    conn = sqlite3.connect("lira_ultimate_v2.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO roulette_history (number, color_emoji) VALUES (?, ?)", (num, emoji))
    cur.execute("DELETE FROM roulette_history WHERE id NOT IN (SELECT id FROM roulette_history ORDER BY id DESC LIMIT 10)")
    conn.commit()
    conn.close()

# --- КОМАНДА: СТАВКА И ОТМЕНА ---
@dp.message(F.text.lower().startswith("рул"))
async def roulette_handler(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.lower().split()
    cid = m.chat.id

    # Обработка отмены: "рул отмена"
    if len(args) > 1 and args[1] in ["отмена", "cancel"]:
        if cid in roulette_games and u[0] in roulette_games[cid]['players']:
            total_return = sum(b['bet'] for b in roulette_games[cid]['players'][u[0]])
            upd_bal(u[0], total_return)
            del roulette_games[cid]['players'][u[0]]
            return await m.reply(f"принял ✅ {get_link(u)}, ваши ставки аннулированы. Возвращено: **{total_return:,}** лир.", parse_mode="Markdown")
        return await m.reply("❌ У вас нет активных ставок для отмены.")

    if len(args) < 3:
        return await m.reply("🎰 **РУЛЕТКА**\n\n📝 `рул [сумма] [тип]`\n🎨 Типы: `к`, `ч`, `з`, `евен`, `одд`, `м`, `б`\n🔢 Числа: `1,5,10` (через запятую)\n\n❌ `рул отмена` — забрать ставки", parse_mode="Markdown")

    # Валидация типа
    target = args[2]
    is_valid_word = target in VALID_TYPES
    is_valid_numbers = re.fullmatch(r'^(\d{1,2},?)+$', target)

    if not (is_valid_word or is_valid_numbers):
        return await m.reply(f"❌ Тип `{target}` не распознан. Ставка не принята!")

    if is_valid_numbers:
        nums = [int(x) for x in target.split(',') if x]
        if any(n > 36 for n in nums):
            return await m.reply("❌ В рулетке только числа от 0 до 36!")

    # Валидация суммы
    try:
        amount = parse_bet(args[1], u[2])
    except: return

    if amount < 100: return await m.reply("❌ Минимум 100 лир!")
    if u[2] < amount: return await m.reply("❌ Недостаточно лир!")

    # Регистрация
    if cid not in roulette_games:
        roulette_games[cid] = {'players': {}, 'start_time': time.time()}
    
    if u[0] not in roulette_games[cid]['players']:
        roulette_games[cid]['players'][u[0]] = []

    roulette_games[cid]['players'][u[0]].append({'bet': amount, 'target': target})
    upd_bal(u[0], -amount)

    await m.answer(f"✅ {get_link(u)} поставил **{amount:,}** на `{target}`\n🚀 Пиши `го` для запуска!")

# --- КОМАНДА: ЗАПУСК (го) ---
@dp.message(F.text.lower() == "го")
async def roulette_spin(m: types.Message):
    cid = m.chat.id
    if cid not in roulette_games or not roulette_games[cid]['players']:
        return await m.reply("❌ Ставок еще нет!")
    
    game = roulette_games[cid]
    if time.time() - game['start_time'] < 10:
        return await m.reply(f"⏳ Рано! Ждите {int(10 - (time.time() - game['start_time']))} сек.")

    res_num = random.randint(0, 36)
    color = "🟢" if res_num == 0 else "🔴" if res_num in RED_NUMS else "⚫️"
    log_roulette_result(res_num, color)

    header = f"🎰 **ВЫПАЛО: {res_num} {color}**\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    report = ""

    for uid, bets in game['players'].items():
        player = get_u(uid)
        win_total = 0
        details = ""
        
        for b in bets:
            t, a = b['target'], b['bet']
            win, mult = False, 2
            
            if t in ['к', 'красное'] and res_num in RED_NUMS: win = True
            elif t in ['ч', 'черное'] and res_num in BLACK_NUMS: win = True
            elif t in ['з', 'зеро', '0'] and res_num == 0: win, mult = True, 36
            elif t in ['евен', 'чет'] and res_num != 0 and res_num % 2 == 0: win = True
            elif t in ['одд', 'нечет'] and res_num % 2 != 0: win = True
            elif t == 'м' and 1 <= res_num <= 18: win = True
            elif t == 'б' and 19 <= res_num <= 36: win = True
            elif t.replace(',', '').isdigit():
                nums = [int(x) for x in t.split(',') if x]
                if res_num in nums: win, mult = True, 36 / len(nums)

            if win:
                w_amt = int(a * mult)
                win_total += w_amt
                details += f"  ✅ `{t}`: +{w_amt:,}\n"
            else:
                details += f"  ❌ `{t}`: -{a:,}\n"
        
        if win_total > 0:
            upd_bal(uid, win_total)
        report += f"👤 {get_link(player)}:\n{details}"

    del roulette_games[cid]
    await m.answer(header + report, parse_mode="Markdown")

# --- КОМАНДА: ЛОГ (лог) ---
@dp.message(F.text.lower() == "лог")
async def roulette_log(m: types.Message):
    conn = sqlite3.connect("lira_ultimate_v2.db")
    cur = conn.cursor()
    cur.execute("SELECT number, color_emoji FROM roulette_history ORDER BY id DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    
    if not rows: return await m.reply("История пуста")
    
    history = " • ".join([f"{r[0]}{r[1]}" for r in rows])
    await m.answer(f"📃 **ИСТОРИЯ ВЫПАДЕНИЙ:**\n\n{history}", parse_mode="Markdown")

# --- СИСТЕМА КАЗНЫ ---

def get_treasury():
    cur.execute("SELECT balance, reward_per_user FROM treasury WHERE id = 1")
    return cur.fetchone()

@dp.message(F.text.lower() == "казна")
async def show_treasury(m: types.Message):
    res = get_treasury()
    await m.answer(f"🏛 **СОСТОЯНИЕ КАЗНЫ**\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
                   f"💰 Баланс: **{res[0]:,}** лир\n"
                   f"🎁 Награда за 1 чел: **{res[1]:,}** лир", parse_mode="Markdown")

@dp.message(F.text.lower().startswith("пополнить казну "))
async def fill_treasury(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        amount = int(m.text.split()[2].lower().replace("к", "000").replace("кк", "000000"))
        cur.execute("UPDATE treasury SET balance = balance + ? WHERE id = 1", (amount,))
        conn.commit()
        await m.answer(f"✅ Казна пополнена на **{amount:,}** лир!")
    except:
        await m.answer("❌ Формат: `пополнить казну [сумма]`")

@dp.message(F.text.lower().startswith("изменить приз "))
async def change_reward(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        amount = int(m.text.split()[2].lower().replace("к", "000").replace("кк", "000000"))
        cur.execute("UPDATE treasury SET reward_per_user = ? WHERE id = 1", (amount,))
        conn.commit()
        await m.answer(f"⚙️ Награда за приглашение изменена на **{amount:,}** лир!")
    except:
        await m.answer("❌ Формат: `изменить приз [сумма]`")

# --- ОБРАБОТКА ДОБАВЛЕНИЯ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(F.new_chat_members)
async def on_user_added(m: types.Message):
    inviter = m.from_user  # Тот, кто добавил
    new_users = m.new_chat_members  # Список тех, кого добавили
    
    res = get_treasury()
    balance, reward = res[0], res[1]
    
    # Считаем общее вознаграждение
    total_reward = reward * len(new_users)
    
    if balance < total_reward:
        return await m.answer("🏛 В казне недостаточно средств для выплаты вознаграждения.")
    
    # Начисляем пригласившему
    upd_bal(inviter.id, total_reward)
    
    # Списываем из казны
    cur.execute("UPDATE treasury SET balance = balance - ? WHERE id = 1", (total_reward,))
    conn.commit()
    
    # Получаем ники новых участников
    new_names = ", ".join([u.first_name for u in new_users])
    u_inv = get_u(inviter.id, inviter.full_name)
    
    new_balance = balance - total_reward
    
    text = (f"👤 {get_link(u_inv)} добавил **{new_names}**\n"
            f"💰 Вам из казны зачисляем **{total_reward:,}** лир.\n"
            f"🏛 Остаток казны — **{new_balance:,}** лир")
    
    await m.answer(text, parse_mode="Markdown")

import asyncio
import random
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- КОМАНДА ЗАПУСКА КУБОВ ---
@dp.message(F.text.lower().startswith("кубы"))
async def cubes_start(m: types.Message):
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    
    # Парсим ставку
    try:
        bet = parse_bet(args[1] if len(args) > 1 else "0", u[2])
    except:
        return await m.reply("❌ Формат: `кубы [ставка]` (ответом на сообщение игрока)")

    if not m.reply_to_message:
        return await m.reply("❌ Нужно ответить на сообщение игрока, которого зовете на дуэль!")
    
    target_user = m.reply_to_message.from_user
    if target_user.id == m.from_user.id:
        return await m.reply("❌ Нельзя играть с самим собой!")
    
    if u[2] < bet:
        return await m.reply("❌ У вас недостаточно лир!")

    # Кнопки принятия/отклонения
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"cube_acc_{m.from_user.id}_{target_user.id}_{bet}")
    kb.button(text="❌ Отклонить", callback_data=f"cube_dec_{m.from_user.id}_{target_user.id}")
    
    await m.answer(
        f"🎲 {get_link(u)} вызывает на кубы {get_link(get_u(target_user.id, target_user.full_name))}\n"
        f"💰 Ставка: **{bet:,}** лир",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown"
    )

# --- ОБРАБОТКА КНОПОК ---
@dp.callback_query(F.data.startswith("cube_"))
async def cubes_callback(call: types.CallbackQuery):
    data = call.data.split("_")
    action = data[1]
    creator_id = int(data[2])
    target_id = int(data[3])
    
    # 1. Защита "Не вами предназначено"
    if call.from_user.id not in [creator_id, target_id]:
        return await call.answer("❌ Эта игра не предназначена для вас!", show_alert=True)

    # 2. ОТКЛОНЕНИЕ / ОТМЕНА
    if action == "dec":
        if call.from_user.id == target_id: # Отклонил оппонент
            await call.message.edit_text("❌ Дуэль отклонена оппонентом.")
        else: # Отменил создатель
            await call.message.edit_text("❌ Создатель отменил вызов.")
        return

    # 3. ПРИНЯТИЕ
    if action == "acc":
        if call.from_user.id != target_id:
            return await call.answer("❌ Только оппонент может принять вызов!", show_alert=True)
        
        bet = int(data[4])
        creator = get_u(creator_id)
        target = get_u(target_id)

        # Проверка балансов еще раз
        if creator[2] < bet or target[2] < bet:
            return await call.message.edit_text("❌ У одного из игроков не хватает лир.")

        # Списываем ставки
        upd_bal(creator[0], -bet)
        upd_bal(target[0], -bet)

        # Анимация начала
        await call.message.edit_text("🎲 Определяем, кто первый бросает кубы...")
        await asyncio.sleep(3)

        # Бросок первого игрока
        players = [creator, target]
        random.shuffle(players)
        p1, p2 = players[0], players[1]

        await call.message.edit_text(f"🎲 Кидает {get_link(p1)}...")
        msg_dice1 = await call.message.answer_dice("🎲")
        val1 = msg_dice1.dice.value
        await asyncio.sleep(3)

        await call.message.answer(f"🎲 А теперь {get_link(p2)}...")
        msg_dice2 = await call.message.answer_dice("🎲")
        val2 = msg_dice2.dice.value
        await asyncio.sleep(3)

        # Результаты
        res_text = (
            f"📊 **Результат:**\n"
            f"👤 {p1[1]}: {val1}\n"
            f"👤 {p2[1]}: {val2}\n\n"
        )

        if val1 == val2:
            # Ничья - возврат
            upd_bal(p1[0], bet)
            upd_bal(p2[0], bet)
            res_text += "🤝 **Ничья!** Ставки возвращены."
        else:
            winner = p1 if val1 > val2 else p2
            win_sum = int(bet * 1.9) # 1.9x (10% комиссия)
            upd_bal(winner[0], win_sum)
            res_text += f"🏆 Итоги\nПобедитель: **{winner[1]}**\n💰 Выигрыш: **{win_sum:,}** лир"
            
            # Логируем в историю (если она у вас есть)
            log_game(winner[0], "Кубы", bet, win_sum, 1.9)

        await call.message.answer(res_text, parse_mode="Markdown")

import random
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

# --- СОСТОЯНИЯ ---
class TowerStates(StatesGroup):
    playing = State()

# --- КОЭФФИЦИЕНТЫ (для 1, 2, 3 и 4 мин) ---
TOWER_COEFFS = {
    1: [1.19, 1.42, 1.86, 2.32, 2.9, 3.52],
    2: [1.58, 2.64, 4.4, 7.33, 10.5, 15.0],
    3: [2.38, 5.94, 10.5, 27.11, 72.0, 131.0],
    4: [4.75, 13.0, 58.0, 150.0, 280.0, 500.0]
}

# --- ФУНКЦИЯ ГЕНЕРАЦИИ ПОЛЯ ---
def get_tower_kb(current_row, mines_count, game_data, game_over=False):
    kb = InlineKeyboardBuilder()
    coeffs = TOWER_COEFFS[mines_count]
    
    # Строим башню сверху вниз (с 5 ряда до 0)
    for row_idx in range(5, -1, -1):
        row_buttons = []
        for col_idx in range(5):
            # Если игра окончена и тут была мина
            if game_over and game_data['mines_pos'].get(row_idx) == col_idx:
                row_buttons.append(InlineKeyboardButton(text="💣", callback_data="ignore"))
            # Если ячейка уже успешно открыта игроком
            elif row_idx < current_row and game_data['history'].get(row_idx) == col_idx:
                row_buttons.append(InlineKeyboardButton(text="📦", callback_data="ignore"))
            # Если это текущий активный ряд
            elif row_idx == current_row and not game_over:
                row_buttons.append(InlineKeyboardButton(text="☁️", callback_data=f"twstep_{row_idx}_{col_idx}"))
            # Остальные закрытые ячейки
            else:
                row_buttons.append(InlineKeyboardButton(text="☁️", callback_data="ignore"))
        
        # Добавляем коэффициент ряда слева
        kb.row(InlineKeyboardButton(text=f"x{coeffs[row_idx]}", callback_data="ignore"), *row_buttons)

    # Кнопка "Забрать", если пройден хотя бы один ряд
    if not game_over and current_row > 0:
        current_win = int(game_data['bet'] * coeffs[current_row-1])
        kb.row(InlineKeyboardButton(text=f"💰 ЗАБРАТЬ {current_win:,}", callback_data="tw_collect"))
    
    return kb.as_markup()

# --- КОМАНДА СТАРТА: башня [ставка] [мины] ---
import random
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

# Коэффициенты (множители для каждого из 10 уровней)
TOWER_LEVELS = [1.2, 1.5, 2.0, 2.8, 3.8, 5.2, 7.2, 10.0, 15.0, 25.0]

# --- Функция отрисовки ---
async def tower_render(m, bet, lvl, bombs, history, finished=False, result="lose"):
    kb = InlineKeyboardBuilder()
    levels = TOWER_LEVELS
    
    # Рисуем уровни сверху вниз (с 10-го по 1-й)
    for i in range(9, -1, -1):
        row_btns = []
        for j in range(3): # В каждом ряду 3 ячейки
            
            # Состояние ПОСЛЕ игры (Раскрытие всего поля)
            if finished:
                if j == bombs[i]:
                    # Если это бомба, на которую наступили
                    if i == lvl and result == "lose" and history.get(f"lvl_{i}") == j:
                        text = "💥"
                    else:
                        text = "💣"
                else:
                    # Показываем, что выбрал игрок, а что нет
                    text = "💎" if history.get(f"lvl_{i}") == j else "🧊"
                row_btns.append(types.InlineKeyboardButton(text=text, callback_data="none"))
            
            # Состояние ВО ВРЕМЯ игры
            else:
                if i < lvl:
                    # Пройденные уровни (показываем где была мина и где алмаз)
                    if j == bombs[i]:
                        text = "💣"
                    elif history.get(f"lvl_{i}") == j:
                        text = "💎"
                    else:
                        text = "🧊"
                    row_btns.append(types.InlineKeyboardButton(text=text, callback_data="none"))
                elif i == lvl:
                    # Текущий активный ряд
                    row_btns.append(types.InlineKeyboardButton(text="❓", callback_data=f"tower_step_{j}"))
                else:
                    # Будущие ряды
                    row_btns.append(types.InlineKeyboardButton(text="⬛", callback_data="none"))
        
        kb.row(*row_btns)

    # Кнопки управления (только если игра не закончена)
    if not finished:
        kb.row(types.InlineKeyboardButton(text="🎲 Автовыбор", callback_data="tower_auto"))
        if lvl > 0:
            current_win = int(bet * levels[lvl-1])
            kb.row(types.InlineKeyboardButton(text=f"💰 ЗАБРАТЬ {current_win:,}", callback_data="tower_stop"))

    # Текст сообщения
    status = "🎮 Игра идет..."
    if finished:
        if result == "win":
            win_amount = int(bet * levels[lvl-1]) if lvl > 0 else bet
            status = f"✅ <b>ПОБЕДА!</b>\nВыигрыш: <b>{win_amount:,}</b> лир"
        else:
            status = f"💥 <b>БАШНЯ РУХНУЛА!</b>\nПотеряно: <b>{bet:,}</b> лир"

    txt = (
        f"🏰 <b>БАШНЯ</b> | Уровень {min(lvl+1, 10)}/10\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Ставка: <b>{bet:,}</b>\n"
        f"📈 Коэф: <b>x{levels[lvl-1] if lvl > 0 else 1.0}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"{status}"
    )

    if isinstance(m, types.Message):
        await m.reply(txt, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        try:
            await m.message.edit_text(txt, reply_markup=kb.as_markup(), parse_mode="HTML")
        except:
            pass

# --- Команда старта ---
@dp.message(F.text.lower().startswith("башня"))
async def tower_start(m: types.Message, state: FSMContext):
    u = get_u(m.from_user.id, m.from_user.full_name)
    args = m.text.split()
    
    # Парсим ставку
    bet = parse_bet(args[1] if len(args) > 1 else "0", u[2])
    
    if bet < 100: 
        return await m.reply("❌ Минимальная ставка — 100 лир!")
    if u[2] < bet: 
        return await m.reply("❌ У вас недостаточно лир на балансе!")

    # Списываем ставку сразу
    upd_bal(m.from_user.id, -bet)
    
    # Генерируем случайное положение мин для всех 10 этажей (0, 1 или 2)
    bombs = [random.randint(0, 2) for _ in range(10)]
    
    await state.set_state(GameStates.tower)
    await state.update_data(bet=bet, bombs=bombs, lvl=0, history={})
    
    await tower_render(m, bet, 0, bombs, {})

# --- Обработка ходов ---
@dp.callback_query(F.data.startswith("tower_"), GameStates.tower)
async def tower_logic(call: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d: return await call.answer()
    
    bet, lvl, bombs, history = d['bet'], d['lvl'], d['bombs'], d['history']

    # Если игрок решил забрать деньги
    if call.data == "tower_stop":
        win_total = int(bet * TOWER_LEVELS[lvl-1])
        upd_bal(call.from_user.id, win_total)
        await tower_render(call, bet, lvl, bombs, history, finished=True, result="win")
        await state.clear()
        return await call.answer(f"💰 Забрали {win_total:,} лир!")

    # Логика выбора ячейки
    if call.data == "tower_auto":
        choice = random.randint(0, 2)
    else:
        choice = int(call.data.split("_")[2])

    # Записываем ход в историю
    history[f"lvl_{lvl}"] = choice
    
    if choice == bombs[lvl]:
        # ПРОИГРЫШ (наступил на мину)
        await tower_render(call, bet, lvl, bombs, history, finished=True, result="lose")
        await state.clear()
        await call.answer("💥 БУМ! Вы проиграли.", show_alert=True)
    else:
        # УСПЕХ (прошел уровень)
        new_lvl = lvl + 1
        if new_lvl == 10:
            # Если прошел всю башню до конца
            win_total = int(bet * TOWER_LEVELS[9])
            upd_bal(call.from_user.id, win_total)
            await tower_render(call, bet, 10, bombs, history, finished=True, result="win")
            await state.clear()
            await call.answer("🏆 НЕВЕРОЯТНО! ВЫ ПРОШЛИ ВСЮ БАШНЮ!", show_alert=True)
        else:
            # Переход на следующий уровень
            await state.update_data(lvl=new_lvl, history=history)
            await tower_render(call, bet, new_lvl, bombs, history)
            await call.answer("💎 Чисто! Поднимаемся выше.")

# --- КОМАНДЫ СНЯТИЯ БАЛАНСА (ТОЛЬКО ДЛЯ АДМИНА) ---

# 1. Снятие через ответ на сообщение (Реплай)
@dp.message(F.text.lower().startswith("снять "))
async def adm_remove_reply(m: types.Message):
    # 1. Проверка доступа для списка админов
    if m.from_user.id not in ADMIN_ID: 
        return

    # 2. Проверка на реплай
    if not m.reply_to_message:
        return await m.reply("❌ **Ответьте на сообщение игрока, у которого нужно снять лиры!**", parse_mode="Markdown")
    
    try:
        args = m.text.split()
        if len(args) < 2:
            return await m.reply("❌ **Введите сумму или слово 'все'**\nПример: `снять 50к` или `снять все`", parse_mode="Markdown")

        target_uid = m.reply_to_message.from_user.id
        target_name = m.reply_to_message.from_user.full_name
        
        # Получаем данные игрока (u[2] — это баланс)
        u = get_u(target_uid, target_name)
        current_balance = u[2]

        # 3. Обработка суммы
        input_val = args[1].lower()
        if input_val == "все" or input_val == "всё":
            amount = current_balance
        else:
            # Поддержка к, кк, k, kk
            summ_raw = input_val.replace("кк", "000000").replace("kk", "000000").replace("к", "000").replace("k", "000")
            amount = int(summ_raw)

        # 4. Проверки баланса
        if amount <= 0:
            return await m.reply("❌ **Сумма должна быть больше 0!**")
        
        if amount > current_balance:
            amount = current_balance # Забираем всё, что есть, если просят больше
            
        # 5. Списание (передаем отрицательное число в вашу функцию)
        upd_bal(target_uid, -amount)
        
        await m.answer(
            f"📉 **ИЗЪЯТИЕ СРЕДСТВ**\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Игрок: **{u[1]}**\n"
            f"💰 Списано: **{amount:,}** лир\n"
            f"━━━━━━━━━━━━━━\n"
            f"Действие выполнил администратор.", 
            parse_mode="Markdown"
        )
        
    except ValueError:
        await m.reply("❌ **Ошибка!** Введите корректную сумму (например: `снять 10к`).", parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка в команде снять: {e}")
        await m.reply("❌ **Произошла ошибка при выполнении команды.**")
        
# 2. Снятие по ID игрока
@dp.message(F.text.lower().startswith("обнулить "))
async def adm_remove_id(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    
    try:
        args = m.text.split() # обнулить [id] [сумма]
        target_id = int(args[1])
        u = get_u(target_id)
        
        if args[2].lower() == "все":
            amount = u[2]
        else:
            amount = int(args[2].lower().replace("к", "000").replace("кк", "000000"))
            
        upd_bal(target_id, -amount)
        await m.answer(f"📉 С баланса игрока `{target_id}` снято **{amount:,}** лир!", parse_mode="Markdown")
    except:
        await m.reply("❌ Формат: `обнулить [ID] [сумма/все]`")

import string
import random
import os
from PIL import Image, ImageDraw, ImageFont
from aiogram.types import FSInputFile

# Функция генерации кода
def generate_random_code(length=12):
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))

async def auto_create_promo():
    promo_name = generate_random_code().lower() # Код как на скрине
    promo_sum = random.randint(2000, 6000)      # Случайная сумма
    promo_uses = random.randint(15, 30)         # Случайные активации
    
    # Сохраняем в вашу таблицу promo
    cur.execute("INSERT INTO promo (name, sum, uses) VALUES (?, ?, ?)", 
                (promo_name, promo_sum, promo_uses))
    conn.commit()

    try:
        # 1. Открываем фон (файл должен быть в папке с ботом)
        img = Image.open("promo_bg.png") 
        draw = ImageDraw.Draw(img)
        
        # 2. Загружаем шрифт (размер подберите под картинку)
        # Если запускаете на Windows, arial.ttf обычно доступен
        font_code = ImageFont.truetype("arial.ttf", 55) # Для промокода
        font_data = ImageFont.truetype("arial.ttf", 35) # Для суммы и юзов

        # 3. Рисуем текст (координаты X и Y нужно подправить под ваш шаблон!)
        # Рисуем промокод в центре синей рамки
        draw.text((280, 245), promo_name, font=font_code, fill="#00d2ff")
        
        # Рисуем сумму (желтым)
        draw.text((230, 360), str(promo_sum), font=font_data, fill="#ffcc00")
        
        # Рисуем количество активаций (зеленым)
        draw.text((545, 360), str(promo_uses), font=font_data, fill="#00ff42")

        # 4. Сохраняем готовую картинку
        path = "current_promo.png"
        img.save(path)

        # 5. Отправляем в основной чат
        await bot.send_photo(
            chat_id=X50_CHAT_ID,
            photo=FSInputFile(path),
            caption="#промо #lira"
        )
        
    except Exception as e:
        print(f"Ошибка при создании фото промо: {e}")
        # Если картинка не удалась, отправляем текстом, чтобы промо не пропал
        await bot.send_message(X50_CHAT_ID, f"🎁 **НОВЫЙ ПРОМОКОД!**\n\n🎫 Код: `{promo_name}`\n💰 Сумма: {promo_sum}\n👤 Юзов: {promo_uses}")

import warnings
# Игнорируем предупреждение об устаревании pkg_resources
warnings.filterwarnings("ignore", category=UserWarning, module='apscheduler')

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Инициализация планировщика с вашим часовым поясом (например, Астана/Алматы)
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Almaty"))

async def auto_create_promo():
    promo_name = generate_random_code().lower()
    promo_sum = random.randint(2000, 6000)
    promo_uses = random.randint(15, 30)
    
    cur.execute("INSERT INTO promo (name, sum, uses) VALUES (?, ?, ?)", 
                (promo_name, promo_sum, promo_uses))
    conn.commit()

    try:
        # Убедитесь, что файлы promo_bg.png и arial.ttf лежат в папке с ботом!
        img = Image.open("promo_bg.png") 
        draw = ImageDraw.Draw(img)
        font_code = ImageFont.truetype("arial.ttf", 55)
        font_data = ImageFont.truetype("arial.ttf", 35)

        # Рисуем данные (подправьте координаты под ваш фон)
        draw.text((280, 245), promo_name, font=font_code, fill="#00d2ff") # Код
        draw.text((230, 360), str(promo_sum), font=font_data, fill="#ffcc00") # Сумма
        draw.text((545, 360), str(promo_uses), font=font_data, fill="#00ff42") # Юзы

        path = "current_promo.png"
        img.save(path)

        await bot.send_photo(
            chat_id=X50_CHAT_ID,
            photo=FSInputFile(path),
            caption="#промо #lira"
        )
    except Exception as e:
        # Если картинка не создалась (например, нет файла), шлем текст:
        await bot.send_message(X50_CHAT_ID, f"🎁 **НОВЫЙ ПРОМОКОД!**\n\n🎫 Код: `{promo_name}`\n💰 Сумма: {promo_sum}\n👤 Юзов: {promo_uses}")
        print(f"Ошибка промо: {e}")

# Добавляем задачу: каждый час в 00 минут
scheduler.add_job(auto_create_promo, "cron", minute=0)


from datetime import datetime
import pytz

@dp.message(F.text.lower() == "время")
async def show_city_time(m: types.Message):
    # Определяем часовые пояса
    zones = {
        "Киев": "Europe/Kyiv",
        "Москва": "Europe/Moscow",
        "Омск": "Asia/Omsk",
        "Китай": "Asia/Shanghai",
        "Астана": "Asia/Almaty"
    }
    
    text = "•-• **Текущее время в:**\n\n"
    
    for city, zone in zones.items():
        now = datetime.now(pytz.timezone(zone))
        fmt_time = now.strftime("%d.%m.%Y %H:%M:%S")
        text += f"{city} — {fmt_time}\n"
        
    await m.answer(text, parse_mode="Markdown")

@dp.message(F.text.lower().startswith("+админ"))
async def add_admin_db(m: types.Message):
    # Только главный владелец может добавлять других (замените ID на свой)
    if m.from_user.id != 8049948727: 
        return await m.reply("❌ **Только главный владелец может назначать админов!**", parse_mode="Markdown")

    new_id = None
    if m.reply_to_message:
        new_id = m.reply_to_message.from_user.id
    elif len(m.text.split()) > 1 and m.text.split()[1].isdigit():
        new_id = int(m.text.split()[1])

    if new_id:
        cur.execute("INSERT OR IGNORE INTO admins VALUES (?)", (new_id,))
        conn.commit()
        await m.answer(f"✅ **Пользователь** `{new_id}` **теперь администратор!**", parse_mode="Markdown")
    else:
        await m.reply("📖 **Используйте:** `+админ [ID]` или ответом на сообщение.")

@dp.message(F.text.lower().startswith("-админ"))
async def del_admin_db(m: types.Message):
    if m.from_user.id != 8049948727: return
    
    target_id = None
    if m.reply_to_message:
        target_id = m.reply_to_message.from_user.id
    elif len(m.text.split()) > 1 and m.text.split()[1].isdigit():
        target_id = int(m.text.split()[1])

    if target_id == 8049948727:
        return await m.reply("❌ **Нельзя снять права с главного владельца!**")

    if target_id:
        cur.execute("DELETE FROM admins WHERE uid = ?", (target_id,))
        conn.commit()
        await m.answer(f"🗑 **Пользователь** `{target_id}` **лишен прав администратора.**", parse_mode="Markdown")

@dp.message(Command("admin"))
async def admin_panel(m: types.Message):
    if is_admin(m.from_user.id):
        await m.answer("🔧 **Админ-панель Lira:**", reply_markup=admin_inline(), parse_mode="Markdown")
    else:
        await m.answer("❌ **Доступ запрещен.**")

@dp.message(F.text.lower() == "куровень")
async def buy_level_request(m: types.Message):
    cur.execute("SELECT level FROM users WHERE uid = ?", (m.from_user.id,))
    res = cur.fetchone()
    u_lv = res[0] if res else 1
    
    if u_lv >= 10:
        return await m.reply("⭐ У вас максимальный уровень!")

    next_lv = u_lv + 1
    price = LEVELS[next_lv]["price"]
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Купить", callback_data=f"buy_lv_up_{next_lv}")
    kb.button(text="❌ Отмена", callback_data="buy_lv_stop")
    
    await m.answer(
        f"⬆️ **ПОВЫШЕНИЕ УРОВНЯ**\n"
        f"━━━━━━━━━━━━━━\n"
        f"Желаете купить **{next_lv} уровень**?\n"
        f"💰 Цена: **{price:,}** лир\n"
        f"📊 Новый лимит: **{LEVELS[next_lv]['limit']:,}**\n"
        f"━━━━━━━━━━━━━━",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("buy_lv_"))
async def buy_level_callback(call: types.CallbackQuery):
    if call.data == "buy_lv_stop":
        return await call.message.edit_text("❌ Покупка отменена.")
    
    next_lv = int(call.data.split("_")[3])
    price = LEVELS[next_lv]["price"]
    
    cur.execute("SELECT bal FROM users WHERE uid = ?", (call.from_user.id,))
    user_bal = cur.fetchone()[0]
    
    if user_bal < price:
        return await call.answer(f"❌ Недостаточно лир! Нужно {price:,}", show_alert=True)
    
    # Списываем баланс и обновляем уровень
    upd_bal(call.from_user.id, -price)
    cur.execute("UPDATE users SET level = ?, used_limit = 0 WHERE uid = ?", (next_lv, call.from_user.id))
    conn.commit()
    
    await call.message.edit_text(f"✅ **Уровень {next_lv} успешно куплен!**\nСуточный лимит повышен.", parse_mode="Markdown")
    

import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройки уровней
LEVELS = {
    1: {"limit": 75000, "price": 0},
    2: {"limit": 125000, "price": 150000},
    3: {"limit": 200000, "price": 250000},
    4: {"limit": 300000, "price": 400000},
    5: {"limit": 400000, "price": 500000},
    6: {"limit": 500000, "price": 750000},
    7: {"limit": 750000, "price": 1000000},
    8: {"limit": 1000000, "price": 1250000},
    9: {"limit": 10000000, "price": 20000000},
    10: {"limit": 999999999999, "price": 35000000} # Безлимит
}

# Вставь это в init_db, чтобы бот не выдавал ошибку "no such column: level"
try:
    cur.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
    conn.commit()
except:
    pass

@dp.message(F.text.lower() == "уровень")
async def show_level(m: types.Message):
    cur.execute("SELECT level, used_limit FROM users WHERE uid = ?", (m.from_user.id,))
    res = cur.fetchone()
    
    u_lv = res[0] if res else 1
    u_used = res[1] if res else 0
    
    max_l = LEVELS[u_lv]["limit"]
    remains = max_l - u_used
    if remains < 0: remains = 0
    
    l_text = f"{max_l:,}" if u_lv < 10 else "Безлимит"
    
    await m.answer(
        f"📊 **ВАШ СТАТУС**\n"
        f"━━━━━━━━━━━━━━\n"
        f"⭐ Уровень: **{u_lv}**\n"
        f"💰 Суточный лимит: **{l_text}**\n"
        f"📉 Осталось на сегодня: **{remains:,}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔄 Обнуление лимитов в **22:00 МСК**\n"
        f"🛒 Повысить лимит: `куровень`",
        parse_mode="Markdown"
    )

async def reset_daily_limits():
    cur.execute("UPDATE users SET used_limit = 0")
    conn.commit()
    print("Лог: Суточные лимиты всех игроков обнулены (22:00 МСК).")

# Настройка планировщика
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
# Ставим задачу на 22:00 каждый день
scheduler.add_job(reset_daily_limits, 'cron', hour=22, minute=0)
scheduler.start()

def get_u(uid, name, username=None):
    cur.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    res = cur.fetchone()
    if not res:
        reg_date = datetime.now().strftime("%d.%m.%Y")
        # Сохраняем имя и юзернейм (очищенный от @)
        uname = username.replace("@", "") if username else None
        cur.execute("INSERT INTO users (uid, name, reg, level, used_limit, username) VALUES (?, ?, ?, ?, ?, ?)", 
                    (uid, name, reg_date, 1, 0, uname))
        conn.commit()
        return get_u(uid, name, username)
    return res

# --- КЛИЕНТСКАЯ ЧАСТЬ ---

@dp.message(Command("q"), F.chat.type == "private")
async def cmd_q(message: types.Message, state: FSMContext):
    await message.answer("💬 <b>Опишите вашу проблему.</b>\n\nВы можете отправить текст, фото или фото с описанием. Админы рассмотрят ваше обращение.", parse_mode="HTML")
    await state.set_state(SupportStates.waiting_for_report)

@dp.message(SupportStates.waiting_for_report)
async def process_support_report(message: types.Message, state: FSMContext):
    # Создаем кнопки для админа
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="✅ Ответить", callback_data=f"support_ans_{message.from_user.id}"),
        types.InlineKeyboardButton(text="❌ Игнорить", callback_data="support_ignore")
    )
    
    admin_text = f"📩 <b>Новое обращение!</b>\n\n"
    user_info = f"\n\n👤 <b>От:</b> {message.from_user.full_name} (<code>{message.from_user.id}</code>)"
    
    # Отправляем всем админам из вашего конфига (ADMIN_ID)
    for admin_id in ADMIN_ID:
        try:
            if message.photo:
                caption = (message.caption or "<i>[Без текста]</i>") + user_info
                await bot.send_photo(admin_id, message.photo[-1].file_id, caption=caption, reply_markup=kb.as_markup(), parse_mode="HTML")
            else:
                await bot.send_message(admin_id, admin_text + message.text + user_info, reply_markup=kb.as_markup(), parse_mode="HTML")
        except:
            pass

    await message.answer("✅ <b>Ваше сообщение отправлено!</b> Ожидайте ответа от администрации.", parse_mode="HTML")
    await state.clear()

# --- АДМИНСКАЯ ЧАСТЬ ---

@dp.callback_query(F.data.startswith("support_"))
async def admin_support_actions(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_ID:
        return await call.answer("Вы не админ!", show_alert=True)

    if call.data == "support_ignore":
        await call.message.delete()
        return await call.answer("Удалено.")

    user_id = call.data.split("_")[2]
    await call.message.answer(f"✍️ <b>Введите ответ для пользователя</b> {user_id}:")
    await state.set_state(SupportStates.waiting_for_admin_answer)
    await state.update_data(reply_to_user=user_id)
    await call.answer()

@dp.message(SupportStates.waiting_for_admin_answer)
async def send_admin_answer(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_ID: return
    
    data = await state.get_data()
    user_id = data.get("reply_to_user")

    try:
        await bot.send_message(user_id, f"⚠️ <b>Ответ от администрации:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer(f"✅ Ответ отправлен пользователю <code>{user_id}</code>")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")
    
    await state.clear()

import random
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State


# --- Команда старта ---
@dp.message(F.text.lower() == "вилин")
async def vilin_start(m: types.Message, state: FSMContext):
    u = get_u(m.from_user.id, m.from_user.full_name)
    balance = u[2]

    if balance <= 0:
        return await m.reply("❌ У вас 0 лир, играть не на что!")

    # Ставим коэффициент ровно 2x
    win_amount = int(balance * 2)
    
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="✅ Принять", callback_data="vilin_accept"),
        types.InlineKeyboardButton(text="❌ Отклонить", callback_data="vilin_decline")
    )

    await m.reply(
        f"🛑 <b>ВНИМАНИЕ!</b>\n\n"
        f"Вы уверены, что хотите сыграть в игру <b>ВСЕ или НИЧЕГО</b>?\n"
        f"Вы можете <b>ПРОИГРАТЬ</b> {balance:,} лир или же <b>ВЫИГРАТЬ</b> {win_amount:,} лир.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    
    # Сохраняем данные во временное хранилище (стейт)
    await state.set_state(VilinStates.confirm)
    await state.update_data(bet=balance, win=win_amount, user_id=m.from_user.id)

# --- Обработка кнопок ---
@dp.callback_query(F.data.startswith("vilin_"), VilinStates.confirm)
async def vilin_logic(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # Проверка, что на кнопку нажал именно тот, кто запустил команду
    if call.from_user.id != data.get("user_id"):
        return await call.answer("Это не ваша игра!", show_alert=True)

    if call.data == "vilin_decline":
        await call.message.edit_text("🚫 <b>Вы отказались от игры.</b>", parse_mode="HTML")
        await state.clear()
        return await call.answer()

    # Логика принятия игры
    bet = data.get("bet")
    win_amount = data.get("win")
    
    # Шанс 50 на 50
    if random.choice([True, False]):
        # ПОБЕДА (Баланс удваивается)
        upd_bal(call.from_user.id, bet) # Прибавляем сумму ставки к текущему балансу (итог = bet * 2)
        await call.message.edit_text(f"✅ Твой баланс теперь <b>{win_amount:,}</b> лир!", parse_mode="HTML")
    else:
        # ПРОИГРЫШ (Баланс обнуляется)
        upd_bal(call.from_user.id, -bet) # Отнимаем всё
        await call.message.edit_text(f"✅ Твой баланс теперь <b>0</b> лир!", parse_mode="HTML")

    await state.clear()
    await call.answer()

@dp.message(F.text.lower().in_(["гайд колесо", "к помощь"]))
async def wheel_instruction(m: types.Message):
    text = (
        f"🎡 <b>ИНСТРУКЦИЯ: КОЛЕСО ФОРТУНЫ</b>\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"Испытай свою удачу! Ставь лиры и крути колесо, чтобы приумножить свой баланс.\n\n"
        f"📝 <b>Как играть:</b>\n"
        f"Введите: <code>колесо [сумма]</code>\n"
        f"Например: <code>колесо 1000</code>\n\n"
        f"📊 <b>Шансы и Сектора:</b>\n"
        f"🔴 <b>x0</b> — Проигрыш (40%)\n"
        f"⚪️ <b>x0.5</b> — Возврат половины (25%)\n"
        f"🟡 <b>x1.5</b> — Небольшой плюс (15%)\n"
        f"🔵 <b>x2</b> — Удвоение (10%)\n"
        f"🟣 <b>x5</b> — Крупный выигрыш (7%)\n"
        f"💎 <b>x15</b> — ДЖЕКПОТ (3%)\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"⚠️ <i>Минимальная ставка: 100 лир.</i>"
    )
    await m.reply(text, parse_mode="HTML")

@dp.message(F.text.lower() == "турнир")
async def tournament_info(m: types.Message):
    text = (
        "🏆 <b>ТУРНИР: КОРОЛЬ КОЭФФИЦИЕНТОВ</b>\n\n"
        "Суть: Сделай самый высокий коэффициент в игре <b>Хл</b> и забери приз!\n\n"
        "🎁 <b>Призы:</b>\n"
        "1️⃣ место — <b>1,000,000</b> лир\n"
        "2️⃣ место — <b>750,000</b> лир\n"
        "3️⃣ место — <b>500,000</b> лир\n\n"
        "⚠️ <b>Важно:</b> Чтобы рекорд засчитался, нужно нажать кнопку <b>«Забрать»</b>!"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Топ рекордов", callback_data="tour_top")
    await m.reply(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "tour_top")
async def tournament_top(call: types.CallbackQuery):
    await call.answer()
    # Сортировка DESC обязательна, чтобы самые большие числа были сверху
    cur.execute("SELECT username, max_coef FROM tournament ORDER BY max_coef DESC LIMIT 10")
    rows = cur.fetchall()
    # ... дальше вывод текста ...
    
    text = "🏆 <b>ТОП 10 РЕКОРДСМЕНОВ:</b>\n\n"
    if not rows:
        text += "Пока рекордов нет. Будь первым!"
    else:
        for i, r in enumerate(rows, 1):
            text += f"{i}. <b>{r[0]}</b> — x{r[1]}\n"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="tour_back")
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "tour_back")
async def tour_back(call: types.CallbackQuery):
    await call.answer()
    # Повторяем текст из турнира (или просто вызываем функцию турнира)
    text = "🏆 <b>ТУРНИР: КОРОЛЬ КОЭФФИЦИЕНТОВ</b>\n\nСуть: Кто сделает самый большой коэф в <b>Хл</b>...\n(полный текст выше)"
    kb = InlineKeyboardBuilder().button(text="📊 Топ рекордов", callback_data="tour_top")
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")



    
@dp.message(Command("start"))
async def start(m: types.Message):
    get_u(m.from_user.id, m.from_user.full_name)
    await m.answer("🎰 Добро пожаловать в Lira! Заходите в основной чат:@lirachatik", reply_markup=main_kb())
    

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())

