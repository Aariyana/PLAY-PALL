# app.py
# PlayPal v2 — Polling-only, professional Telegram bot (Assamese + multilingual + premium)
# Single-file. Set env vars as instructed.

import os
import random
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, List

import requests
from flask import Flask
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ServerSelectionTimeoutError
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Poll,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================== Configuration ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()]
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PlayPalu")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/+1mgUwZpfuJY0YjA1")
TENOR_API_KEY = os.getenv("TENOR_API_KEY", "").strip()
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "").strip()
AUTO_FETCH_INTERVAL_MIN = int(os.getenv("AUTO_FETCH_INTERVAL_MIN", "360"))  # default 6 hours
BOT_OWNER_AUTO_PREMIUM = os.getenv("BOT_OWNER_AUTO_PREMIUM", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

# ================== Flask keep-alive ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ PlayPal v2 (Polling) is running."

# ================== MongoDB (optional) ==================
use_mongo = bool(MONGODB_URI)
db = None
users_col = None
cache_col = None
bans_col = None

if use_mongo:
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
        # pick DB name from URI if present
        try:
            db_name = MONGODB_URI.split("/")[-1].split("?")[0] or "playpal"
        except Exception:
            db_name = "playpal"
        db = client[db_name]
        users_col = db["users"]
        cache_col = db["cache"]
        bans_col = db["bans"]
        users_col.create_index([("user_id", ASCENDING)], unique=True)
        users_col.create_index([("messages", DESCENDING)])
        cache_col.create_index([("type", ASCENDING)])
        print("Connected to MongoDB.")
    except ServerSelectionTimeoutError:
        print("WARNING: Cannot connect to MongoDB. Falling back to in-memory store.")
        use_mongo = False
else:
    print("No MONGODB_URI set — using in-memory store (non-persistent).")

# in-memory fallback stores
_inmem_users = {}
_inmem_cache = {"memes": [], "gifs": []}
_inmem_bans = set()

def _now():
    return datetime.now(timezone.utc)

# ================== Storage helpers ==================
def ensure_user_record(user) -> dict:
    """Ensure user exists; return user doc."""
    if use_mongo:
        doc = users_col.find_one({"user_id": user.id})
        if doc:
            users_col.update_one({"user_id": user.id}, {"$set": {"username": user.username, "first_name": user.first_name}})
            return users_col.find_one({"user_id": user.id})
        new = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_premium": False,
            "messages": 0,
            "xp": 0,
            "language": "en",
            "joined_at": _now(),
            "referrals": 0,
            "referred_by": None
        }
        if BOT_OWNER_AUTO_PREMIUM and str(user.id) == BOT_OWNER_AUTO_PREMIUM:
            new["is_premium"] = True
        users_col.insert_one(new)
        return new
    else:
        doc = _inmem_users.get(user.id)
        if doc:
            doc["username"] = user.username
            doc["first_name"] = user.first_name
            return doc
        new = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_premium": (BOT_OWNER_AUTO_PREMIUM and str(user.id) == BOT_OWNER_AUTO_PREMIUM),
            "messages": 0,
            "xp": 0,
            "language": "en",
            "joined_at": _now(),
            "referrals": 0,
            "referred_by": None
        }
        _inmem_users[user.id] = new
        return new

def update_user_counter(user_id: int, field: str, amount: int = 1):
    if use_mongo:
        users_col.update_one({"user_id": user_id}, {"$inc": {field: amount}}, upsert=True)
    else:
        d = _inmem_users.get(user_id)
        if not d:
            return
        d[field] = d.get(field, 0) + amount

def get_user(user_id: int) -> Optional[dict]:
    if use_mongo:
        return users_col.find_one({"user_id": user_id})
    else:
        return _inmem_users.get(user_id)

def set_user_field(user_id: int, k: str, v):
    if use_mongo:
        users_col.update_one({"user_id": user_id}, {"$set": {k: v}}, upsert=True)
    else:
        d = _inmem_users.get(user_id)
        if not d:
            return
        d[k] = v

def add_cached_item(kind: str, item: dict):
    if use_mongo:
        cache_col.insert_one({"type": kind, "data": item, "fetched_at": _now()})
    else:
        _inmem_cache.setdefault(kind, []).append(item)

def get_cached_items(kind: str, limit: int = 20) -> List[dict]:
    if use_mongo:
        docs = list(cache_col.find({"type": kind}).sort("fetched_at", DESCENDING).limit(limit))
        return [d["data"] for d in docs]
    else:
        return list(reversed(_inmem_cache.get(kind, [])[-limit:]))

def ban_user(user_id: int):
    if use_mongo:
        bans_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id, "banned_at": _now()}}, upsert=True)
    else:
        _inmem_bans.add(user_id)

def unban_user(user_id: int):
    if use_mongo:
        bans_col.delete_one({"user_id": user_id})
    else:
        _inmem_bans.discard(user_id)

def is_banned_user(user_id: int) -> bool:
    if use_mongo:
        return bans_col.find_one({"user_id": user_id}) is not None
    else:
        return user_id in _inmem_bans

# ================== Hardcoded content (EN / HI / AS) ==================
JOKES = {
    "en": {
        "general": [
            "I told my computer I needed a break — it said 'No problem, I'll go to sleep.'",
            "Why don’t scientists trust atoms? Because they make up everything!"
        ],
        "tech": ["Why do programmers prefer dark mode? Because light attracts bugs."],
        "school": ["Teacher: 'Use the word aesthetic in a sentence.' Student: 'I ate a stick.'"],
        "couple": ["Love is sharing your popcorn."],
        "random": ["I’m reading a book on anti-gravity. It’s impossible to put down!"]
    },
    "hi": {
        "general": ["कम्प्यूटर भी ब्रेक चाहता है — तभी ये 'हैश' करता है!"],
        "tech": ["प्रोग्रामर को bugs पसंद नहीं, इसलिए वह debug करता है।"],
        "random": ["मैंने कल एक जोक पकाया — बहुत मसालेदार निकला।"]
    },
    "as": {  # Assamese (mandatory)
        "general": [
            "মই দেউতাকক ক’লো যে মই বাগৰি গ’লো — তেওঁ মোক ক’লে, 'বগা ল’ৰা, তুমিয়ে বাগৰি নাহেৰিবা'।",
            "জীৱনত শিকিব লাগে — কিয়নো ক’ৰবাৰ উপৰিও জানিব লাগে।"
        ],
        "tech": ["কেনেকৈ লিখকজন ডিবাগ কৰে? সেয়া ৰ'দৰ কোডত।"],
        "school": ["শিক্ষকে: 'জলটো ক’লৈ গ'ল?' ছাত্ৰ: 'দস্যু'।"],
        "couple": ["তুমি মোৰ চাহ, মই তোমাৰ চেনি।"],
        "random": ["চকুৱে ক'লে: মোমবাতি জ্বলাই লোৱা — জুই নাই।"]
    }
}

QUIZZES = {
    "en": [
        {"q": "Which planet is known as the Red Planet?", "opts": ["Mars", "Venus", "Jupiter"], "ans": 0},
        {"q": "What is 7 + 5?", "opts": ["10", "12", "13"], "ans": 1}
    ],
    "hi": [
        {"q": "भारत की राजधानी क्या है?", "opts": ["मुंबई", "दिल्ली", "कोलकाता"], "ans": 1}
    ],
    "as": [
        {"q": "অসমৰ ৰাজধানী কোনটো?", "opts": ["গুৱাহাটী", "ডিব্ৰুগড়", "শহৰ নোহোৱা"], "ans": 0}
    ]
}

# ================== UI Helpers ==================
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Help", callback_data="help_menu"), InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
        [InlineKeyboardButton("💎 Premium", callback_data="premium_info"), InlineKeyboardButton("🎮 Games", callback_data="games_menu")],
        [InlineKeyboardButton("🌐 Channel", url=CHANNEL_LINK), InlineKeyboardButton("💬 Group", url=GROUP_LINK)]
    ])

def premium_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Contact admin to upgrade", callback_data="upgrade_contact")],
        [InlineKeyboardButton("↩️ Back", callback_data="back_main")]
    ])

def games_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Quiz", callback_data="game_quiz"), InlineKeyboardButton("✂️ RPS", callback_data="game_rps")],
        [InlineKeyboardButton("🔢 Guess Number", callback_data="game_guess"), InlineKeyboardButton("🔤 Scramble", callback_data="game_scramble")],
        [InlineKeyboardButton("↩️ Back", callback_data="back_main")]
    ])

# ================== Auto-fetch background worker ==================
def auto_fetch_loop():
    while True:
        try:
            print("[autofetch] cycle start", datetime.now())
            # fetch memes from meme-api
            try:
                r = requests.get("https://meme-api.com/gimme", timeout=8)
                if r.ok:
                    data = r.json()
                    # single meme
                    if data.get("url"):
                        add_cached_item("memes", {"url": data["url"], "title": data.get("title")})
            except Exception:
                pass

            # fetch gifs via Tenor or Giphy
            gifs = []
            if TENOR_API_KEY:
                try:
                    params = {"q": "funny", "key": TENOR_API_KEY, "limit": 5}
                    r = requests.get("https://tenor.googleapis.com/v2/search", params=params, timeout=8)
                    if r.ok:
                        jr = r.json()
                        for res in jr.get("results", [])[:5]:
                            gif = res.get("media_formats", {}).get("gif", {}).get("url")
                            if gif:
                                gifs.append({"url": gif})
                except Exception:
                    pass
            if not gifs and GIPHY_API_KEY:
                try:
                    r = requests.get("https://api.giphy.com/v1/gifs/trending", params={"api_key": GIPHY_API_KEY, "limit": 5}, timeout=8)
                    if r.ok:
                        jr = r.json()
                        for it in jr.get("data", [])[:5]:
                            gifs.append({"url": it["images"]["original"]["url"]})
                except Exception:
                    pass

            for g in gifs:
                add_cached_item("gifs", g)

            print("[autofetch] done. memes:", len(get_cached_items("memes", 200)), "gifs:", len(get_cached_items("gifs",200)))
        except Exception:
            traceback.print_exc()
        time.sleep(max(60, AUTO_FETCH_INTERVAL_MIN * 60))

threading.Thread(target=auto_fetch_loop, daemon=True).start()

# ================== Command Handlers ==================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    if is_banned_user(user.id):
        return
    # referral handling if present
    args = context.args or []
    referred_by = None
    if args and args[0].startswith("ref_"):
        try:
            referred_by = int(args[0].split("_",1)[1])
        except:
            referred_by = None

    doc = ensure_user_record(user)
    if referred_by and not doc.get("referred_by") and referred_by != user.id:
        set_user_field(user.id, "referred_by", referred_by)
        update_user_counter(referred_by, "referrals", 1)

    name = user.first_name or "friend"
    text = (
        f"👋 *Welcome, {name}!* \n\n"
        "I’m 🤖 *PlayPal* — your professional fun & utility bot.\n\n"
        "✨ I provide:\n"
        "• 🎲 Games & Quizzes\n"
        "• 😄 Jokes in Assamese / Hindi / English\n"
        "• 📊 Personal stats & Leaderboard\n"
        "• 💎 Premium goodies (memes, GIFs, advanced quizzes)\n\n"
        "👇 Use the menu below to start — it's fast and friendly."
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Open the menu below.", reply_markup=main_menu_kb())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    data = q.data
    if data == "help_menu":
        await q.edit_message_text("Use /lang <en|hi|as> to change language. Choose features from the menu.", reply_markup=main_menu_kb())
    elif data == "my_stats":
        u = ensure_user_record(q.from_user)
        text = (
            f"👤 *Your Profile*\n"
            f"• ID: `{u['user_id']}`\n"
            f"• Name: {u.get('first_name')}\n"
            f"• Messages: {u.get('messages',0)}\n"
            f"• XP: {u.get('xp',0)}\n"
            f"• Premium: {'✅' if u.get('is_premium') else '❌'}\n"
        )
        await q.edit_message_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.MARKDOWN)
    elif data == "premium_info":
        await q.edit_message_text("Premium unlocks memes, GIFs, advanced quizzes. Contact admin to upgrade.", reply_markup=premium_kb())
    elif data == "upgrade_contact":
        await q.answer("Contact the admin to upgrade. Admin IDs available in bot config.", show_alert=True)
    elif data == "games_menu":
        await q.edit_message_text("Games menu", reply_markup=games_kb())
    elif data == "game_quiz":
        await q.edit_message_text("Use /quiz to play a quiz (premium).", reply_markup=main_menu_kb())
    elif data == "game_rps":
        await q.edit_message_text("Use /rps rock|paper|scissors to play.", reply_markup=main_menu_kb())
    elif data == "game_guess":
        await q.edit_message_text("Use /guess start to play guess-the-number.", reply_markup=main_menu_kb())
    elif data == "game_scramble":
        await q.edit_message_text("Use /scramble start to play word scramble.", reply_markup=main_menu_kb())
    elif data == "back_main":
        await q.edit_message_text("Back to main menu", reply_markup=main_menu_kb())
    else:
        await q.edit_message_text("Unknown action.", reply_markup=main_menu_kb())

# language selection
async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /lang <en|hi|as>")
        return
    code = context.args[0].lower()
    if code not in ("en","hi","as"):
        await update.message.reply_text("Supported: en, hi, as")
        return
    ensure_user_record(update.effective_user)
    set_user_field(update.effective_user.id, "language", code)
    await update.message.reply_text(f"Language set to {code}")

# message logger
async def message_logger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    if is_banned_user(update.effective_user.id):
        return
    if update.message and update.message.text and update.message.text.startswith("/"):
        # don't count commands
        return
    ensure_user_record(update.effective_user)
    update_user_counter(update.effective_user.id, "messages", 1)
    update_user_counter(update.effective_user.id, "xp", random.randint(1,3))

# jokes
async def cmd_joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_record(update.effective_user)
    lang = u.get("language","en")
    cat = "general"
    if context.args:
        cat = context.args[0].lower()
    if cat not in JOKES.get(lang, {}):
        # fallback to random
        cat = "random" if "random" in JOKES.get(lang, {}) else list(JOKES.get(lang, {}).keys())[0]
    pool = JOKES.get(lang, {}).get(cat, [])
    if not pool:
        pool = JOKES["en"].get("general", ["No jokes right now."])
    await update.message.reply_text(random.choice(pool))

# RPS
async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rps rock|paper|scissors")
        return
    user_choice = context.args[0].lower()
    if user_choice not in ("rock","paper","scissors"):
        await update.message.reply_text("Use rock|paper|scissors")
        return
    bot_choice = random.choice(["rock","paper","scissors"])
    result = "Draw!"
    if (user_choice, bot_choice) in [("rock","scissors"),("paper","rock"),("scissors","paper")]:
        result = "You win! 🎉"
        update_user_counter(update.effective_user.id, "xp", 5)
    elif user_choice != bot_choice:
        result = "Bot wins 😅"
    await update.message.reply_text(f"You: {user_choice}\nBot: {bot_choice}\n\n{result}")

# Guess number
async def cmd_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /guess start  OR  /guess <number>")
        return
    if context.args[0].lower() == "start":
        secret = random.randint(1,100)
        context.chat_data["guess_secret"] = secret
        context.chat_data["guess_tries"] = 0
        await update.message.reply_text("I picked a number 1–100. Guess with /guess <number>!")
        return
    try:
        n = int(context.args[0])
    except:
        await update.message.reply_text("Send a number.")
        return
    secret = context.chat_data.get("guess_secret")
    if secret is None:
        await update.message.reply_text("Start with /guess start")
        return
    context.chat_data["guess_tries"] = context.chat_data.get("guess_tries",0) + 1
    if n == secret:
        tries = context.chat_data.pop("guess_tries", 0)
        context.chat_data.pop("guess_secret", None)
        update_user_counter(update.effective_user.id, "xp", 20)
        await update.message.reply_text(f"🎉 Correct! You guessed in {tries} tries.")
    elif n < secret:
        await update.message.reply_text("Too low!")
    else:
        await update.message.reply_text("Too high!")

# Scramble
async def cmd_scramble(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /scramble start OR /scramble <guess>")
        return
    if context.args[0].lower() == "start":
        words = ["assam", "guwahati", "friend", "telegram", "python"]
        w = random.choice(words)
        scrambled = "".join(random.sample(list(w), len(w)))
        context.chat_data["scramble_word"] = w
        await update.message.reply_text(f"Unscramble: *{scrambled}*", parse_mode=ParseMode.MARKDOWN)
        return
    guess = " ".join(context.args).strip().lower()
    target = context.chat_data.get("scramble_word")
    if not target:
        await update.message.reply_text("Start with /scramble start")
        return
    if guess == target:
        update_user_counter(update.effective_user.id, "xp", 10)
        context.chat_data.pop("scramble_word", None)
        await update.message.reply_text("✅ Correct! +10 XP")
    else:
        await update.message.reply_text("❌ Not yet — try again.")

# Quiz (premium)
async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_record(update.effective_user)
    if not u.get("is_premium"):
        await update.message.reply_text("🔒 Premium only. Upgrade to access quizzes.", reply_markup=premium_kb())
        return
    lang = u.get("language","en")
    pool = QUIZZES.get(lang, QUIZZES["en"])
    q = random.choice(pool)
    buttons = [[InlineKeyboardButton(opt, callback_data=f"quiz_ans:{i}")] for i, opt in enumerate(q["opts"])]
    context.user_data["quiz_answer"] = q["ans"]
    context.user_data["quiz_q"] = q["q"]
    await update.message.reply_text(q["q"], reply_markup=InlineKeyboardMarkup(buttons))

async def quiz_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    if not cq.data.startswith("quiz_ans:"):
        return
    try:
        choice = int(cq.data.split(":",1)[1])
    except:
        return
    ans = context.user_data.get("quiz_answer")
    qtext = context.user_data.get("quiz_q","Quiz")
    if ans is None:
        await cq.edit_message_text("Quiz expired.")
        return
    if choice == ans:
        update_user_counter(cq.from_user.id, "xp", 10)
        await cq.edit_message_text(f"✅ Correct! {qtext}\n+10 XP")
    else:
        await cq.edit_message_text(f"❌ Wrong! {qtext}")

# Meme (premium) uses cache
async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_record(update.effective_user)
    if not u.get("is_premium"):
        await update.message.reply_text("🔒 Premium only.", reply_markup=premium_kb())
        return
    memes = get_cached_items("memes", limit=50)
    if memes:
        pick = random.choice(memes)
        url = pick.get("url")
        caption = pick.get("title") or "Here’s a meme"
        try:
            await update.message.reply_photo(photo=url, caption=caption)
            return
        except Exception:
            pass
    await update.message.reply_text("No memes cached yet. Try again soon.")

# GIF (premium) uses cache
async def cmd_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_record(update.effective_user)
    if not u.get("is_premium"):
        await update.message.reply_text("🔒 Premium only.", reply_markup=premium_kb())
        return
    gifs = get_cached_items("gifs", limit=50)
    if gifs:
        pick = random.choice(gifs)
        url = pick.get("url")
        try:
            await update.message.reply_animation(animation=url)
            return
        except Exception:
            pass
    await update.message.reply_text("No GIFs cached yet. Try again soon.")

# Stats / leaderboard / invite
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_record(update.effective_user)
    doc = get_user(u["user_id"])
    await update.message.reply_text(
        f"👤 Profile\n• Name: {doc.get('first_name')}\n• Messages: {doc.get('messages',0)}\n• XP: {doc.get('xp',0)}\n• Premium: {'✅' if doc.get('is_premium') else '❌'}"
    )

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if use_mongo:
        top = list(users_col.find().sort("xp", -1).limit(10))
    else:
        top = sorted(_inmem_users.values(), key=lambda x: x.get("xp",0), reverse=True)[:10]
    lines = ["🏆 Leaderboard:"]
    for i, u in enumerate(top,1):
        name = ("@" + u.get("username")) if u.get("username") else u.get("first_name") or str(u.get("user_id"))
        lines.append(f"{i}. {name} — {u.get('xp',0)} XP")
    await update.message.reply_text("\n".join(lines))

async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    uid = update.effective_user.id
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    await update.message.reply_text(f"Share this to invite friends and earn referrals:\n{link}")

# Admin commands
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Unauthorized.")
        return
    total = users_col.estimated_document_count() if use_mongo else len(_inmem_users)
    prem = users_col.count_documents({"is_premium": True}) if use_mongo else sum(1 for u in _inmem_users.values() if u.get("is_premium"))
    await update.message.reply_text(f"🛠 Admin Panel\n• Total users: {total}\n• Premium users: {prem}")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <text>")
        return
    text = " ".join(context.args)
    sent = 0
    if use_mongo:
        cursor = users_col.find({}, {"user_id":1})
        for doc in cursor:
            try:
                await context.bot.send_message(chat_id=doc["user_id"], text=text)
                sent += 1
            except Exception:
                pass
    else:
        for uid in _inmem_users.keys():
            try:
                await context.bot.send_message(chat_id=uid, text=text)
                sent += 1
            except Exception:
                pass
    await update.message.reply_text(f"Broadcast attempted to {sent} users.")

async def cmd_setpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setpremium <user_id> on|off")
        return
    target = int(context.args[0])
    flag = context.args[1].lower() == "on"
    set_user_field(target, "is_premium", flag)
    await update.message.reply_text(f"Premium for {target} set to {flag}")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    target = int(context.args[0])
    ban_user(target)
    await update.message.reply_text(f"Banned {target}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    target = int(context.args[0])
    unban_user(target)
    await update.message.reply_text(f"Unbanned {target}")

# error handler
async def err_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("Error:", context.error)

# ================== Bot bootstrap (Polling) ==================
def run_bot():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # core / navigation
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))

    # language and logger
    application.add_handler(CommandHandler("lang", cmd_lang))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_logger))

    # jokes & content
    application.add_handler(CommandHandler("joke", cmd_joke))
    application.add_handler(CommandHandler("meme", cmd_meme))
    application.add_handler(CommandHandler("gif", cmd_gif))
    application.add_handler(CommandHandler("quote", cmd_joke))  # simple fallback
    application.add_handler(CommandHandler("rps", cmd_rps))
    application.add_handler(CommandHandler("guess", cmd_guess))
    application.add_handler(CommandHandler("scramble", cmd_scramble))
    application.add_handler(CommandHandler("quiz", cmd_quiz))
    application.add_handler(CallbackQueryHandler(quiz_answer_handler, pattern="^quiz_ans:"))

    # profile / social
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    application.add_handler(CommandHandler("invite", cmd_invite))

    # admin
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(CommandHandler("setpremium", cmd_setpremium))
    application.add_handler(CommandHandler("ban", cmd_ban))
    application.add_handler(CommandHandler("unban", cmd_unban))

    application.add_error_handler(err_handler)

    print("Bot polling started.")
    application.run_polling()

if __name__ == "__main__":
    # start bot thread and flask server for Railway health
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
