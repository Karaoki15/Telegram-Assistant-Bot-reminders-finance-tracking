import asyncio
import io
import logging
import re
import sqlite3
from datetime import datetime, timedelta, time
from calendar import month_name

import matplotlib.pyplot as plt
import numpy as np 
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, Message,
                           CallbackQuery, BufferedInputFile)
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- 1. КОНФИГУРАЦИЯ ---
BOT_TOKEN = ""
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
scheduler = AsyncIOScheduler(timezone="Europe/Kiev")


# --- 2. БАЗА ДАННЫХ ---
conn = sqlite3.connect('my_assistant_v7.1.db'); cursor = conn.cursor()
def init_db():
    cursor.execute('CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, type TEXT, trigger_date DATETIME, day_of_week INTEGER, trigger_time TIME)')
    cursor.execute('CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, category TEXT, created_at DATETIME)')
    cursor.execute('CREATE TABLE IF NOT EXISTS incomes (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, category TEXT, created_at DATETIME)')
    conn.commit()


def get_incomes_by_category_for_period(user_id, start_date, end_date):
    cursor.execute("SELECT category, SUM(amount) FROM incomes WHERE user_id = ? AND created_at BETWEEN ? AND ? GROUP BY category ORDER BY SUM(amount) DESC", (user_id, start_date, end_date))
    return dict(cursor.fetchall())
def add_income(user_id, amount, category):
    cursor.execute("INSERT INTO incomes (user_id, amount, category, created_at) VALUES (?, ?, ?, ?)", (user_id, amount, category, datetime.now())); conn.commit()
def get_incomes_for_period(user_id, start_date, end_date):
    cursor.execute("SELECT SUM(amount) FROM incomes WHERE user_id = ? AND created_at BETWEEN ? AND ?", (user_id, start_date, end_date)); result = cursor.fetchone()[0]; return result or 0.0
def get_expenses_list_for_period(user_id, start_date, end_date):
    cursor.execute("SELECT id, amount, category, created_at FROM expenses WHERE user_id = ? AND created_at BETWEEN ? AND ? ORDER BY created_at DESC", (user_id, start_date, end_date))
    return cursor.fetchall()
def get_incomes_list_for_period(user_id, start_date, end_date):
    cursor.execute("SELECT id, amount, category, created_at FROM incomes WHERE user_id = ? AND created_at BETWEEN ? AND ? ORDER BY created_at DESC", (user_id, start_date, end_date))
    return cursor.fetchall()
def delete_expense_by_id(expense_id):
    cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,)); conn.commit()
def delete_income_by_id(income_id):
    cursor.execute("DELETE FROM incomes WHERE id = ?", (income_id,)); conn.commit()
def add_one_time_reminder(user_id, text, trigger_date):
    cursor.execute("INSERT INTO reminders (user_id, text, type, trigger_date) VALUES (?, ?, 'one_time', ?)", (user_id, text, trigger_date)); conn.commit()
def add_weekly_reminder(user_id, text, day_of_week, trigger_time):
    cursor.execute("INSERT INTO reminders (user_id, text, type, day_of_week, trigger_time) VALUES (?, ?, 'weekly', ?, ?)", (user_id, text, day_of_week, trigger_time)); conn.commit(); return cursor.lastrowid
def get_user_reminders(user_id):
    cursor.execute("SELECT id, text, type, trigger_date FROM reminders WHERE user_id = ? AND type = 'one_time' ORDER BY trigger_date", (user_id,)); return cursor.fetchall()
def get_weekly_reminders(user_id):
    cursor.execute("SELECT id, text, type, day_of_week, trigger_time FROM reminders WHERE user_id = ? AND type = 'weekly' ORDER BY day_of_week, trigger_time", (user_id,)); return cursor.fetchall()
def get_reminder_by_id(rem_id):
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (rem_id,)); return cursor.fetchone()
def delete_reminder_db(rem_id):
    cursor.execute("DELETE FROM reminders WHERE id = ?", (rem_id,)); conn.commit()
def add_expense(user_id, amount, category):
    cursor.execute("INSERT INTO expenses (user_id, amount, category, created_at) VALUES (?, ?, ?, ?)", (user_id, amount, category, datetime.now())); conn.commit()
def get_total_expenses(user_id: int):
    cursor.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ?", (user_id,)); result = cursor.fetchone()[0]; return result or 0.0
def get_expenses_for_period(user_id, start_date, end_date):
    cursor.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ? AND created_at BETWEEN ? AND ?", (user_id, start_date, end_date)); result = cursor.fetchone()[0]; return result or 0.0
def get_expenses_by_category_for_period(user_id, start_date, end_date):
    cursor.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id = ? AND created_at BETWEEN ? AND ? GROUP BY category ORDER BY SUM(amount) DESC", (user_id, start_date, end_date)); return dict(cursor.fetchall())
# --- 3. FSM ---
class Form(StatesGroup):
    add_reminder = State(); add_expense = State(); add_income = State()
    add_weekly_reminder_text = State(); add_weekly_reminder_day = State(); add_weekly_reminder_time = State()
    delete_entry = State()

# --- 4. УТИЛИТЫ и ПАРСЕР ---
def parse_reminder_text(text: str):
    now = datetime.now(scheduler.timezone);
    text = re.sub(r'^(напомни|нагадай|задача|remind)\s*', '', text, flags=re.I).strip()
    time_match = re.search(r'\b(\d{1,2}[:\-]\d{2}|\d{1,2})\b$', text)
    rem_time = None
    if time_match:
        time_str = time_match.group(0).strip(); text = text.replace(time_str, '').strip()
        try:
            if ':' in time_str or '-' in time_str: rem_time = time.fromisoformat(time_str.replace('-', ':'))
            else: rem_time = time(int(time_str), 0)
        except ValueError: return None, None
    if rem_time is None: rem_time = time(9, 0)
    rem_date = now.date()
    if 'завтра' in text.lower():
        rem_date = now.date() + timedelta(days=1); text = re.sub(r'завтра', '', text, flags=re.I).strip()
    elif 'послезавтра' in text.lower():
        rem_date = now.date() + timedelta(days=2); text = re.sub(r'послезавтра', '', text, flags=re.I).strip()
    else:
        date_match = re.search(r'(\d{1,2})[\./](\d{1,2})', text)
        if date_match:
            day, month = int(date_match.group(1)), int(date_match.group(2)); year = now.year
            try:
                if datetime(year, month, day).date() < now.date(): year += 1
                rem_date = datetime(year, month, day).date(); text = text.replace(date_match.group(0), '').strip()
            except ValueError: return None, None
    final_dt = datetime.combine(rem_date, rem_time, tzinfo=scheduler.timezone)
    if final_dt < now: final_dt += timedelta(days=1)
    clean_task = ' '.join(re.sub(r'\s+(о|в|at|ранку|вечора|дня)\s*', ' ', text, flags=re.I).strip(" ,.-").split())
    if not clean_task: return None, None
    return clean_task, final_dt

def generate_period_comparison_chart(income_current, expense_current, income_prev, expense_prev, period_names):
    labels = [period_names['prev'], period_names['current']]
    income_amounts = [income_prev, income_current]
    expense_amounts = [expense_prev, expense_current]

    x = np.arange(len(labels))  # the label locations
    width = 0.35  # the width of the bars

    fig, ax = plt.subplots(figsize=(10, 7))
    rects1 = ax.bar(x - width/2, income_amounts, width, label='Дохід', color='mediumseagreen')
    rects2 = ax.bar(x + width/2, expense_amounts, width, label='Витрати', color='indianred')

    ax.set_ylabel('Сума, грн')
    ax.set_title(f'Порівняння фінансів: {period_names["current"]} vs {period_names["prev"]}')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.7)

    ax.bar_label(rects1, padding=3, fmt='%.0f')
    ax.bar_label(rects2, padding=3, fmt='%.0f')

    fig.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_financial_summary_chart(income_data, expense_data, title):
    income_labels = list(income_data.keys())
    income_values = list(income_data.values())
    expense_labels = list(expense_data.keys())
    expense_values = list(expense_data.values())
    
    # Используем предопределенные цвета для наглядности
    income_colors = plt.cm.Greens(np.linspace(0.4, 0.8, len(income_values)))
    expense_colors = plt.cm.Reds(np.linspace(0.4, 0.8, len(expense_values)))

    fig, ax = plt.subplots(figsize=(12, 8))
    
    # --- Столбец доходов ---
    bottom = 0
    for i, (label, value) in enumerate(income_data.items()):
        ax.bar('Доходи', value, bottom=bottom, label=f"{label} (Дохід)", color=income_colors[i], width=0.5)
        bottom += value
    
    # --- Столбец расходов ---
    bottom = 0
    for i, (label, value) in enumerate(expense_data.items()):
        ax.bar('Витрати', value, bottom=bottom, label=f"{label} (Витрата)", color=expense_colors[i], width=0.5)
        bottom += value
    
    ax.set_title(title, fontsize=16, pad=20)
    ax.set_ylabel('Сума, грн', fontsize=12)
    ax.legend(title="Категорії", loc="center left", bbox_to_anchor=(1, 0.5))
    ax.grid(axis='y', linestyle='--', alpha=0.6)
    
    # Добавляем общие суммы над столбцами
    total_income = sum(income_values)
    total_expense = sum(expense_values)
    if total_income > 0:
        ax.text('Доходи', total_income, f'{total_income:,.0f} грн', ha='center', va='bottom', fontsize=12, weight='bold')
    if total_expense > 0:
        ax.text('Витрати', total_expense, f'{total_expense:,.0f} грн', ha='center', va='bottom', fontsize=12, weight='bold')

    plt.tight_layout(rect=[0, 0, 0.85, 1]) 
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf

# --- 5. КЛАВИАТУРЫ ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Створити нагадування", callback_data="create_reminder")],[InlineKeyboardButton(text="💰 Записати витрату", callback_data="create_expense"),InlineKeyboardButton(text="📈 Записати дохід", callback_data="create_income")],[InlineKeyboardButton(text="📝 Переглянути нагадування", callback_data="my_reminders")],[InlineKeyboardButton(text="🔁 Щотижневі нагадування", callback_data="manage_weekly_reminders")],[InlineKeyboardButton(text="📊 Фінансовий центр", callback_data="analytics_menu")]])
def get_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")]])
def get_weekdays_keyboard():
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]; buttons = [InlineKeyboardButton(text=day, callback_data=f"rem_day_{i}") for i, day in enumerate(days)]; return InlineKeyboardMarkup(inline_keyboard=[buttons[:4], buttons[4:], [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")]])
def get_month_report_keyboard():
    buttons = []; today = datetime.now(scheduler.timezone)
    month_names_ua = [ "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"]
    for i in range(12):
        month_date = (today.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
        month_num = month_date.month; year = month_date.year; button_text = f"{month_names_ua[month_num - 1]} {year}"
        buttons.append(InlineKeyboardButton(text=button_text, callback_data=f"report_month_{year}-{month_num:02}"))
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]; keyboard.append([InlineKeyboardButton(text="⬅️ Назад до аналітики", callback_data="analytics_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
# --- 6. ПЛАНИРОВЩИК ---
async def send_reminder_job(bot: Bot, user_id: int, text: str):
    try: await bot.send_message(user_id, f"🔔 <b>НАГАДУВАННЯ:</b>\n\n<i>{text}</i>")
    except Exception as e: logging.error(f"Failed to send job reminder to user {user_id}: {e}")
async def check_one_time_reminders(bot: Bot):
    now_aware = datetime.now(scheduler.timezone); reminders_to_fire = cursor.execute("SELECT id, user_id, text FROM reminders WHERE type = 'one_time' AND trigger_date <= ?", (now_aware,)).fetchall()
    for rem_id, user_id, text in reminders_to_fire: await send_reminder_job(bot, user_id, text); delete_reminder_db(rem_id)
def add_job_to_scheduler(rem_id, user_id, text, day_of_week, trigger_time):
    t = time.fromisoformat(trigger_time); job_id = f"rem_{rem_id}"; scheduler.add_job(send_reminder_job, 'cron', day_of_week=day_of_week, hour=t.hour, minute=t.minute, args=[bot, user_id, text], id=job_id, timezone=scheduler.timezone)
def remove_job_from_scheduler(rem_id):
    job_id = f"rem_{rem_id}";
    if scheduler.get_job(job_id): scheduler.remove_job(job_id)
async def load_reminders_on_startup(bot: Bot):
    cursor.execute("SELECT id, user_id, text, day_of_week, trigger_time FROM reminders WHERE type = 'weekly'")
    reminders = cursor.fetchall();
    for rem_id, user_id, text, day, tm in reminders: add_job_to_scheduler(rem_id, user_id, text, day, tm)
    logging.info(f"Loaded {len(reminders)} weekly reminders.")

# --- 7. ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# --- 8. ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
@dp.callback_query(F.data == "main_menu")
async def cmd_start(update: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "Привіт! Я ваш асистент. Оберіть дію або надішліть список задач.\n\n"
        "<b>Пакетний режим (декілька записів в одному повідомленні):</b>\n"
        "<code>Зустріч з клієнтом завтра 10:00\n"
        "Зателефонувати в банк 15\n"
        "Витрата 250 продукти\n"
        "Дохід 5000 зарплата</code>"
    )
    if isinstance(update, Message): await update.answer(text, reply_markup=get_main_menu())
    else: await update.message.edit_text(text, reply_markup=get_main_menu()); await update.answer()

@dp.callback_query(F.data == "cancel_action")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    current_state_str = await state.get_state()
    await state.clear()
    # Умный возврат в меню аналитики
    if current_state_str and 'delete_entry' in current_state_str:
        await analytics_menu(callback)
    else:
        await callback.message.edit_text("Дію скасовано. Оберіть, що робити далі:", reply_markup=get_main_menu())
        await callback.answer()

@dp.message(StateFilter(None), F.text.contains('\n'))
async def handle_batch_input(message: Message):
    lines = message.text.strip().split('\n'); success_count = 0; fail_count = 0
    exp_keywords = ['расход', 'витрата', 'потратил', 'купив']
    inc_keywords = ['доход', 'дохід', 'заробіток', 'зарплата', 'получил']
    for line in lines:
        line = line.strip();
        if not line: continue
        is_processed = False
        match = re.search(r'(\d+[.,]?\d*)\s*(.*)', line, flags=re.I)
        if any(kw in line.lower() for kw in inc_keywords) and match:
            try:
                amount = float(match.group(1).replace(',', '.')); category = match.group(2).strip() or "Без категорії"
                add_income(message.from_user.id, amount, category); success_count += 1; is_processed = True
            except: pass
        if is_processed: continue
        if any(kw in line.lower() for kw in exp_keywords) and match:
            try:
                amount = float(match.group(1).replace(',', '.')); category = match.group(2).strip() or "Без категорії"
                add_expense(message.from_user.id, amount, category); success_count += 1; is_processed = True
            except: pass
        if is_processed: continue
        task_text, smart_date = parse_reminder_text(line)
        if task_text and smart_date:
            add_one_time_reminder(message.from_user.id, task_text, smart_date); success_count += 1
            continue
        fail_count += 1
    await message.reply(f"✅ Оброблено!\nСтворено записів: {success_count}\nНе розпізнано рядків: {fail_count}")

@dp.callback_query(F.data == "create_reminder")
async def create_reminder_dialog(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.add_reminder)
    await callback.message.edit_text("Введіть текст і час нагадування (напр., 'Випити каву завтра 9:00')", reply_markup=get_cancel_keyboard())
@dp.message(StateFilter(Form.add_reminder), F.text)
async def process_reminder_dialog(message: Message, state: FSMContext):
    task_text, smart_date = parse_reminder_text(message.text)
    if task_text and smart_date:
        add_one_time_reminder(message.from_user.id, task_text, smart_date)
        await message.answer(f"✅ Нагадування створено!\n<i>«{task_text}»</i> на <b>{smart_date.strftime('%d.%m.%Y %H:%M')}</b>")
        await state.clear(); await cmd_start(message, state)
    else:
        await message.answer("Не зміг розпізнати. Спробуйте ще раз, наприклад: <code>Зателефонувати мамі 25.12 18:30</code>", reply_markup=get_cancel_keyboard())

@dp.callback_query(F.data == "create_expense")
async def create_expense_dialog(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.add_expense)
    await callback.message.edit_text("Введіть суму та категорію (напр., '150.50 Таксі')", reply_markup=get_cancel_keyboard())
@dp.message(StateFilter(Form.add_expense), F.text)
async def process_expense_dialog(message: Message, state: FSMContext):
    match = re.match(r'(\d+[.,]?\d*)\s*(.*)', message.text)
    if match:
        try:
            amount = float(match.group(1).replace(',', '.')); category = match.group(2).strip() or "Без категорії"
            add_expense(message.from_user.id, amount, category)
            await message.answer(f"💸 Витрату <b>{amount:.2f} грн</b> на <i>«{category}»</i> записано!")
            await state.clear(); await cmd_start(message, state)
        except ValueError: await message.answer("Сума має бути числом. Спробуйте ще.", reply_markup=get_cancel_keyboard())
    else: await message.answer("Неправильний формат. Введіть суму та категорію, наприклад: <code>150.50 Таксі</code>", reply_markup=get_cancel_keyboard())

@dp.callback_query(F.data == "create_income")
async def create_income_dialog(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.add_income)
    await callback.message.edit_text("Введіть суму та джерело доходу (напр., '5000 Зарплата')", reply_markup=get_cancel_keyboard())
@dp.message(StateFilter(Form.add_income), F.text)
async def process_income_dialog(message: Message, state: FSMContext):
    match = re.match(r'(\d+[.,]?\d*)\s*(.*)', message.text)
    if match:
        try:
            amount = float(match.group(1).replace(',', '.')); category = match.group(2).strip() or "Без категорії"
            add_income(message.from_user.id, amount, category)
            await message.answer(f"📈 Дохід <b>{amount:.2f} грн</b> з <i>«{category}»</i> записано!")
            await state.clear(); await cmd_start(message, state)
        except ValueError: await message.answer("Сума має бути числом. Спробуйте ще.", reply_markup=get_cancel_keyboard())
    else: await message.answer("Неправильний формат. Введіть суму та джерело, наприклад: <code>5000 Зарплата</code>", reply_markup=get_cancel_keyboard())

# --- Аналитика ---
@dp.callback_query(F.data == "analytics_menu")
async def analytics_menu(callback: CallbackQuery):
    user_id = callback.from_user.id; now = datetime.now(scheduler.timezone)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_week = start_today - timedelta(days=now.weekday())
    start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    today_exp = get_expenses_for_period(user_id, start_today, now)
    week_exp = get_expenses_for_period(user_id, start_week, now)
    month_exp = get_expenses_for_period(user_id, start_month, now)
    today_inc = get_incomes_for_period(user_id, start_today, now)
    week_inc = get_incomes_for_period(user_id, start_week, now)
    month_inc = get_incomes_for_period(user_id, start_month, now)

    text = (
        f"<b>📊 Фінансовий центр</b>\n\n"
        f"<b>Сьогодні:</b>\n"
        f"  Дохід: <code>{today_inc:.2f} грн</code>\n"
        f"  Витрати: <code>{today_exp:.2f} грн</code>\n"
        f"  Баланс: <code>{today_inc - today_exp:+.2f} грн</code>\n\n"
        f"<b>Цього тижня:</b>\n"
        f"  Дохід: <code>{week_inc:.2f} грн</code>\n"
        f"  Витрати: <code>{week_exp:.2f} грн</code>\n"
        f"  Баланс: <code>{week_inc - week_exp:+.2f} грн</code>\n\n"
        f"<b>Цього місяця:</b>\n"
        f"  Дохід: <code>{month_inc:.2f} грн</code>\n"
        f"  Витрати: <code>{month_exp:.2f} грн</code>\n"
        f"  Баланс: <code>{month_inc - month_exp:+.2f} грн</code>\n\n"
        "Оберіть дію:"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Звіт за місяць (діаграма)", callback_data="monthly_report_menu")],
        [InlineKeyboardButton(text="🆚 Порівняти періоди", callback_data="comparison_menu")],
        [InlineKeyboardButton(text="🗑️ Видалити запис", callback_data="delete_entry_menu")],
        [InlineKeyboardButton(text="⬅️ Головне меню", callback_data="main_menu")]
    ])
    
    try:
        if callback.message.photo: await callback.message.delete(); await callback.bot.send_message(callback.from_user.id, text, reply_markup=keyboard)
        else: await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest: pass
    finally: await callback.answer()

@dp.callback_query(F.data == "comparison_menu")
async def comparison_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Тиждень до тижня", callback_data="compare_week")],
        [InlineKeyboardButton(text="Місяць до місяця", callback_data="compare_month")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="analytics_menu")]
    ])
    await callback.message.edit_text("Оберіть періоди для порівняння:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "monthly_report_menu")
async def monthly_report_menu(callback: CallbackQuery):
    text = "Оберіть місяць для детального звіту:"
    keyboard = get_month_report_keyboard()
    if callback.message.photo: await callback.message.delete(); await callback.bot.send_message(callback.from_user.id, text, reply_markup=keyboard)
    else: await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("report_month_"))
async def show_monthly_report(callback: CallbackQuery):
    await callback.answer("⏳ Готую фінансовий звіт...", show_alert=False)
    year, month = map(int, callback.data.split('_')[-1].split('-'))
    user_id = callback.from_user.id
    
    start_date = datetime(year, month, 1)
    end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    
    income_data = get_incomes_by_category_for_period(user_id, start_date, end_date)
    expense_data = get_expenses_by_category_for_period(user_id, start_date, end_date)

    if not income_data and not expense_data:
        await callback.message.edit_text("За цей місяць даних не знайдено.", reply_markup=get_month_report_keyboard())
        return

    month_names_ua = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"]
    title = f"Фінансовий звіт за {month_names_ua[month-1]} {year}"
    
    chart_buffer = generate_financial_summary_chart(income_data, expense_data, title)
    
    total_income = sum(income_data.values())
    total_expense = sum(expense_data.values())
    balance = total_income - total_expense

    caption = f"<b>{title}</b>\n\n"
    caption += f"✅ <b>Загальний дохід:</b> <code>{total_income:.2f} грн</code>\n"
    if income_data:
        for category, amount in income_data.items():
            percent = (amount / total_income) * 100 if total_income > 0 else 0
            caption += f"  ▪️ {category}: <code>{amount:.2f}</code> ({percent:.1f}%)\n"
    
    caption += f"\n❌ <b>Загальні витрати:</b> <code>{total_expense:.2f} грн</code>\n"
    if expense_data:
        for category, amount in expense_data.items():
            percent = (amount / total_expense) * 100 if total_expense > 0 else 0
            caption += f"  ▪️ {category}: <code>{amount:.2f}</code> ({percent:.1f}%)\n"
            
    caption += f"\n💰 <b>Баланс:</b> <code>{balance:+.2f} грн</code>"
    
    await callback.message.delete()
    await bot.send_photo(chat_id=user_id, photo=BufferedInputFile(chart_buffer.getvalue(), filename="summary_chart.png"), caption=caption, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад до вибору місяця", callback_data="monthly_report_menu")]]))

@dp.callback_query(F.data.startswith("compare_"))
async def handle_comparison(callback: CallbackQuery):
    await callback.answer("⏳ Готую порівняльний звіт...", show_alert=False)
    period = callback.data.split('_')[1]
    now = datetime.now(scheduler.timezone)
    user_id = callback.from_user.id
    
    # Определяем периоды
    if period == "week":
        start_current = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start_prev = start_current - timedelta(days=7)
        end_prev = start_current - timedelta(seconds=1)
        period_names = {'current': 'Цей тиждень', 'prev': 'Минулий тиждень'}
    else: 
        start_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_prev = start_current - timedelta(seconds=1)
        start_prev = end_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_names = {'current': 'Цей місяць', 'prev': 'Минулий місяць'}
        
    # Собираем данные
    income_current = get_incomes_for_period(user_id, start_current, now)
    expense_current = get_expenses_for_period(user_id, start_current, now)
    income_prev = get_incomes_for_period(user_id, start_prev, end_prev)
    expense_prev = get_expenses_for_period(user_id, start_prev, end_prev)
    
    if all(v == 0 for v in [income_current, expense_current, income_prev, expense_prev]):
        await callback.message.edit_text("Недостатньо даних для порівняння.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="analytics_menu")]]))
        return
        
    balance_current = income_current - expense_current
    balance_prev = income_prev - expense_prev

    # Формируем текст
    text = f"<b>Порівняння: {period_names['current']} vs {period_names['prev']}</b>\n\n"
    text += f"<u>{period_names['current']}:</u>\n"
    text += f"  Дохід: <code>{income_current:.2f}</code>, Витрати: <code>{expense_current:.2f}</code>\n"
    text += f"  Баланс: <b><code>{balance_current:+.2f} грн</code></b>\n\n"
    
    text += f"<u>{period_names['prev']}:</u>\n"
    text += f"  Дохід: <code>{income_prev:.2f}</code>, Витрати: <code>{expense_prev:.2f}</code>\n"
    text += f"  Баланс: <b><code>{balance_prev:+.2f} грн</code></b>\n\n"
    
    # Считаем разницу в балансе
    diff = balance_current - balance_prev
    emoji = '📈' if diff > 0 else '📉' if diff < 0 else '⚖️'
    text += f"Різниця в балансі: <b><code>{diff:+.2f} грн</code></b> {emoji}"
    
    # Генерируем график и отправляем
    chart_buffer = generate_period_comparison_chart(income_current, expense_current, income_prev, expense_prev, period_names)
    await callback.message.delete()
    await bot.send_photo(
        chat_id=user_id,
        photo=BufferedInputFile(chart_buffer.getvalue(), filename="comparison.png"),
        caption=text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад до аналітики", callback_data="analytics_menu")]])
    )


# --- Остальные обработчики (удаление, напоминания) без изменений ---
@dp.callback_query(F.data == "delete_entry_menu")
async def delete_entry_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.delete_entry) 
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Видалити витрату", callback_data="list_delete_expense")],
        [InlineKeyboardButton(text="Видалити дохід", callback_data="list_delete_income")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="analytics_menu")]
    ])
    await callback.message.edit_text("Оберіть, який тип запису ви хочете видалити:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("list_delete_"))
async def list_entries_for_deletion_period(callback: CallbackQuery):
    entry_type = callback.data.split('_')[-1]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="За сьогодні", callback_data=f"show_del_{entry_type}_today")],
        [InlineKeyboardButton(text="За вчора", callback_data=f"show_del_{entry_type}_yesterday")],
        [InlineKeyboardButton(text="За цей тиждень", callback_data=f"show_del_{entry_type}_week")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="delete_entry_menu")]
    ])
    await callback.message.edit_text("Оберіть період, за який показати записи:", reply_markup=keyboard)
    await callback.answer()

async def show_transactions_for_deletion(callback: CallbackQuery, entry_type: str, period: str):
    user_id = callback.from_user.id; now = datetime.now(scheduler.timezone)
    if period == "today": start_date = now.replace(hour=0, minute=0, second=0, microsecond=0); end_date = now; period_str = "сьогодні"
    elif period == "yesterday": start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0); end_date = start_date.replace(hour=23, minute=59, second=59); period_str = "вчора"
    elif period == "week": start_date = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0); end_date = now; period_str = "цей тиждень"
    else: return
    if entry_type == 'expense': entries = get_expenses_list_for_period(user_id, start_date, end_date); type_str = "витрат"; callback_prefix = "confirm_del_expense_"
    else: entries = get_incomes_list_for_period(user_id, start_date, end_date); type_str = "доходів"; callback_prefix = "confirm_del_income_"
    if not entries: await callback.answer(f"Записів ({type_str}) за {period_str} не знайдено.", show_alert=True); return
    text = f"Натисніть на запис, щоб видалити (показано за {period_str}):\n"; buttons = []
    for entry_id, amount, category, created in entries:
        dt = created if isinstance(created, datetime) else datetime.fromisoformat(created); entry_text = f"{dt.strftime('%H:%M')} - {amount:.2f} грн, {category[:20]}"; buttons.append([InlineKeyboardButton(text=f"❌ {entry_text}", callback_data=f"{callback_prefix}{entry_id}_{period}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад до вибору періоду", callback_data=f"list_delete_{entry_type}")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await callback.answer()

@dp.callback_query(F.data.startswith("show_del_"))
async def handle_show_deletion_list(callback: CallbackQuery):
    _, _, entry_type, period = callback.data.split("_"); await show_transactions_for_deletion(callback, entry_type, period)

@dp.callback_query(F.data.startswith("confirm_del_"))
async def confirm_delete_entry(callback: CallbackQuery):
    parts = callback.data.split('_'); entry_type = parts[2]; entry_id = int(parts[3]); period_to_refresh = parts[4]
    if entry_type == 'expense': delete_expense_by_id(entry_id); await callback.answer("Витрату видалено!", show_alert=False)
    else: delete_income_by_id(entry_id); await callback.answer("Дохід видалено!", show_alert=False)
    await show_transactions_for_deletion(callback, entry_type, period_to_refresh)

@dp.callback_query(F.data == "my_reminders")
async def show_my_reminders(callback: CallbackQuery, state: FSMContext):
    await state.clear(); reminders = get_user_reminders(callback.from_user.id)
    text = "<b>🗓️ Ваші разові нагадування:</b>\n\n"; buttons = []
    if not reminders: text += "<i>Немає запланованих разових нагадувань.</i>"
    else:
        for rem_id, rem_text, _, dt in reminders:
            trigger_dt = datetime.fromisoformat(dt).astimezone(scheduler.timezone); text += f"▫️ {rem_text} (<i>{trigger_dt.strftime('%d.%m.%Y %H:%M')}</i>)\n"
            buttons.append([InlineKeyboardButton(text=f"❌ {rem_text[:25]}...", callback_data=f"del_rem_{rem_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Головне меню", callback_data="main_menu")])
    try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except TelegramBadRequest: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("del_rem_"))
async def delete_reminder_callback(callback: CallbackQuery, state: FSMContext):
    rem_id = int(callback.data.split("_")[2]); reminder_data = get_reminder_by_id(rem_id)
    if reminder_data and reminder_data[3] == 'weekly': remove_job_from_scheduler(rem_id)
    delete_reminder_db(rem_id); await callback.answer("Нагадування видалено!")
    if reminder_data and reminder_data[3] == 'weekly': await manage_weekly_reminders(callback, state)
    else: await show_my_reminders(callback, state)

@dp.callback_query(F.data == "manage_weekly_reminders")
async def manage_weekly_reminders(update: CallbackQuery | Message, state: FSMContext, is_after_creation: bool = False):
    target_message = update if isinstance(update, Message) else update.message; user_id = update.from_user.id
    if not is_after_creation: await state.clear()
    reminders = get_weekly_reminders(user_id); text = "<b>🔁 Ваші щотижневі нагадування:</b>\n\n"; buttons = [[InlineKeyboardButton(text="➕ Створити нове", callback_data="create_weekly_rem")]]
    if not reminders: text += "<i>Немає щотижневих нагадувань.</i>"
    else:
        days_map = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
        for rem_id, rem_text, _, day, tm in reminders:
            trigger_time = time.fromisoformat(tm); text += f"▫️ {rem_text} (<i>Що {days_map[day]} о {trigger_time.strftime('%H:%M')}</i>)\n"; buttons.append([InlineKeyboardButton(text=f"❌ {rem_text[:25]}...", callback_data=f"del_rem_{rem_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Головне меню", callback_data="main_menu")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        if isinstance(update, Message): await update.answer(text, reply_markup=markup)
        else: await target_message.edit_text(text, reply_markup=markup)
    except (TelegramBadRequest, AttributeError) as e: logging.error(e)
    if isinstance(update, CallbackQuery): await update.answer()

@dp.callback_query(F.data == "create_weekly_rem")
async def start_weekly_creation(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.add_weekly_reminder_text); await callback.message.edit_text("Добре, введіть текст для щотижневого нагадування:", reply_markup=get_cancel_keyboard())
    
# --- ЗАПУСК БОТА ---
async def main():
    init_db(); scheduler.add_job(check_one_time_reminders, 'interval', seconds=60, args=[bot]); await load_reminders_on_startup(bot); scheduler.start(); logging.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True); await dp.start_polling(bot)

if __name__ == '__main__':
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logging.info("Bot stopped.")

    finally: conn.close()
