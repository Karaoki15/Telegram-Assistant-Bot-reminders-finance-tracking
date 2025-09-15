# 🧾 Telegram Assistant Bot — reminders + finance tracking

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](#-requirements)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-4B8BBE.svg)](https://docs.aiogram.dev/)
[![APScheduler](https://img.shields.io/badge/APScheduler-3.x-6C757D.svg)](https://apscheduler.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](#)

Telegram bot that helps you **set reminders** and **track personal finances**. Supports batch input, weekly reminders, and analytics with charts (income/expenses, period comparison, monthly category breakdown).

---

## 📚 Table of Contents

* [Features](#-features)
* [Screenshots](#-screenshots)
* [Requirements](#-requirements)
* [Installation](#-installation)
* [Configuration](#-configuration)
* [Run](#-run)
* [Usage (examples)](#-usage-examples)

---

## ✨ Features

**Reminders**

* One-time: `Meeting with client 25.12 18:30`, `Call mom tomorrow 9:00`
* Weekly: choose weekday and time with scheduler
* Batch mode: multiple lines in one message

**Finance tracking**

* Record **expenses** and **income** with categories
* View and delete entries by period: **today / yesterday / week**

**Analytics**

* Summary for **day / week / month** (income, expenses, balance)
* Monthly **category report** (stacked bars)
* **Period comparison**: week-to-week, month-to-month (income vs expenses bar charts)

---

## 🖼️ Screenshots

> Replace placeholders with your own images from `assets/` or remove this section.

* Main menu — `assets/main_menu.png`
* Monthly report — `assets/monthly_report.png`
* Period comparison — `assets/comparison.png`

```text
repo/
└─ assets/
   ├─ main_menu.png
   ├─ monthly_report.png
   └─ comparison.png
```

---

## 🧩 Requirements

* Python **3.10+**
* Telegram Bot Token (from @BotFather)
* SQLite (built-in with Python)

**Dependencies (pip):** aiogram 3.x, APScheduler, matplotlib, numpy, python-dotenv (optional)

---

## 🛠 Installation

```bash
git clone https://github.com/<username>/<project>.git
cd <project>
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## ⚙️ Configuration

**1) Bot token**
It’s safer to store the token in an environment variable or in a `.env` file.

* Option A — `.env`:

  ```env
  BOT_TOKEN=123456:ABC...your_token
  TZ=Europe/Kiev
  ```

  In code:

  ```python
  from dotenv import load_dotenv
  import os
  load_dotenv()
  BOT_TOKEN = os.getenv("BOT_TOKEN")
  ```

* Option B — environment variable:

  ```bash
  export BOT_TOKEN=123456:ABC...your_token
  export TZ=Europe/Kiev
  ```

**2) Scheduler timezone**
The project uses `Europe/Kiev` timezone. Change if needed.

**3) Database**
SQLite file is created automatically (e.g., `my_assistant_v7.1.db`). For a clean start just delete the file.

---

## ▶️ Run

```bash
python main.py
```

On first start the bot will:

* initialize the DB
* start the scheduler
* load weekly reminders into the schedule

---

## 💡 Usage (examples)

**Command /start** — opens main menu and batch input examples.

### Batch mode (multiple lines)

Send in one message:

```
Meeting with client tomorrow 10:00
Call the bank 15
Expense 250 groceries
Income 5000 salary
```

The bot will parse reminders, expenses, and income, creating corresponding records.

### Add expense

* Via menu → “💰 Record expense”
* Or by message: `150.50 Taxi`

### Add income

* Via menu → “📈 Record income”
* Or by message: `5000 Salary`

### One-time reminder (smart date parser)

Examples:
`Call mom 25.12 18:30`
`Meeting tomorrow 9:00`
`Buy gifts 15-30` (interpreted as 15:30)

### Weekly reminders

Menu → “🔁 Weekly reminders” → “➕ Create new” → select day and time.

### Analytics

Menu → “📊 Finance center”:

* Summary for day/week/month
* “📈 Monthly report (chart)” — choose month, category breakdown
* “🆚 Compare periods” — week↔week, month↔month

### Delete entries

Menu → “🗑️ Delete entry” → choose type (income/expense) and period (today/yesterday/week).
