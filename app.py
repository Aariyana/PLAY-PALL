app.py

Telegram Fun Bot + Flask Dashboard (MongoDB, Premium, Channel/Group linking)

Deploy on Railway (single service). BOT runs via polling, Flask serves dashboard on $PORT.

import os import re import random import logging import threading from datetime import datetime from urllib.parse import quote_plus

import requests from flask import Flask, request, jsonify, redirect from pymongo import MongoClient from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.constants import ParseMode from telegram.ext import ( ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ) from telegram import Bot

-------------------- Config --------------------

load_dotenv() BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip() MONGO_URI = os.getenv("MONGO_URI", "").strip() CHANNEL_ID = os.getenv("CHANNEL_ID", "@PlayPalu").strip()  # default to your channel GROUP_ID = os.getenv("GROUP_ID", "").strip()  # optional: set fixed group id TENOR_API_KEY = os.getenv("TENOR_API_KEY", "").strip() GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "").strip() ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()} ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme") DEFAULT_DB = os.getenv("DB_NAME", "playpalu")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s") logger = logging.getLogger("playpalu")

if not BOT_TOKEN: raise SystemExit("BOT_TOKEN is required.") if not MONGO_URI: raise SystemExit("MONGO_URI is required.")

mongo = MongoClient(MONGO_URI) db = mongo[DEFAULT_DB] users_col = db["users"] settings_col = db["settings"] premium_col = db["premium"]

Seed settings

settings_col.update_one({"_id": "feature_flags"}, {"$setOnInsert": { "meme_enabled": True, "gif_enabled": True, "roast_enabled": True, "compliment_enabled": True, "quiz_enabled": True, }}, upsert=True)

-------------------- Data --------------------

QUOTES = [ "Believe you can and you're halfway there.", "Dream big. Start small. Act now.", "Stay hungry, stay foolish.", ] JOKES = [ "Why did the developer go broke? Because he used up all his cache!", "Parallel lines have so much in common. It’s a shame they’ll never meet.", "I told my computer I needed a break, and it froze.", ] COMPLIMENTS = [ "You're the spark this group needed!", "Your vibes are immaculate ✨", ] ROASTS = [ "You’re like a cloud. When you disappear, it’s a beautiful day.", "Lagta hai Wi‑Fi weak hai… logic connect hi nahi ho raha.", ] QUIZ = [ {"q": "Which planet is known as the Red Planet?", "opts": ["Earth","Mars","Jupiter","Venus"], "ans": 1}, {"q": "2 + 2 * 2 = ?", "opts": ["6","8","4","22"], "ans": 0}, ]

Premium gating: commands listed here require premium

PREMIUM_ONLY = {"gif", "meme", "quiz"}

EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u26FF]")

-------------------- Helpers --------------------

def is_admin(user_id: int) -> bool: return user_id in ADMIN_IDS

def is_premium(user_id: int) -> bool: doc = premium_col.find_one({"user_id": user_id}) return bool(doc and doc.get("active"))

def gate_premium(user_id: int, feature: str) -> bool: if feature in PREMIUM_ONLY and not is_premium(user_id): return False return True

def inc_stats(user, text: str = ""): if not user: return emojis = len(EMOJI_RE.findall(text or "")) users_col.update_one( {"user_id": user.id}, {"$set": { "username": user.username, "first_name": user.first_name, "last_active": datetime.utcnow(), }, "$inc": {"messages": 1, "emojis": emojis}}, upsert=True )

def get_linked_channel() -> str: row = settings_col.find_one({"_id": "channel"}) if row and row.get("username"): return row["username"] return CHANNEL_ID

def set_linked_channel(username: str): if not username.startswith("@"):  # normalize username = "@" + username settings_col.update_one({"_id": "channel"}, {"$set": {"username": username}}, upsert=True)

-------------------- Telegram Bot --------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "👋 Hi! I’m PlayPalu Bot — games, memes, polls, stats.\n" "Type /help to see everything.\n" "Want extra powers? Try /premium" )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE): text = ( "Commands\n" "/quote, /joke\n" "/roll, /flip, /rps <rock|paper|scissors>\n" "/poll Question | opt1, opt2, ...\n" "/random opt1, opt2, ...\n" "/compliment [@user], /roast [@user]\n" "/countdown YYYY-MM-DD EventName\n" "/stats — leaderboard\n" "Premium: /meme, /gif <term>, /quiz\n" "Admin: /linkchannel @handle, /announce <text>, /grantpremium <user_id>, /revokepremium <user_id>" ) await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = update.effective_user.id if is_premium(user_id): await update.message.reply_text("✅ You already have Premium! Enjoy /meme, /gif, /quiz.") else: await update.message.reply_text( "⭐ Premium unlocks: /meme, /gif, /quiz.\n" "Ask an admin for access or contact channel owner.")

async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(random.choice(QUOTES))

async def cmd_joke(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(random.choice(JOKES))

async def cmd_roll(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(f"🎲 You rolled {random.randint(1,6)}")

async def cmd_flip(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(f"🪙 {random.choice(['Heads','Tails'])}")

async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE): choices = ["rock","paper","scissors"] user = (context.args[0].lower() if context.args else "") if user not in choices: await update.message.reply_text("Usage: /rps rock|paper|scissors") return bot = random.choice(choices) if (user, bot) in [("rock","scissors"),("paper","rock"),("scissors","paper")]: res = "You win!" elif user == bot: res = "Draw" else: res = "Bot wins!" await update.message.reply_text(f"You: {user} | Bot: {bot} → {res}")

async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE): try: text = update.message.text.partition(" ")[2] question, opts = text.split("|") options = [o.strip() for o in re.split(r",||", opts) if o.strip()] if len(options) < 2: raise ValueError await update.effective_chat.send_poll(question.strip(), options, is_anonymous=False) except Exception: await update.message.reply_text("Usage: /poll Question | opt1, opt2, ...")

async def cmd_random(update: Update, context: ContextTypes.DEFAULT_TYPE): text = update.message.text.partition(" ")[2] items = [i.strip() for i in re.split(r",||", text) if i.strip()] if len(items) < 2: await update.message.reply_text("Usage: /random a, b, c") return await update.message.reply_text("🎯 I pick: " + random.choice(items))

async def cmd_compliment(update: Update, context: ContextTypes.DEFAULT_TYPE): target = update.message.reply_to_message.from_user.first_name if update.message.reply_to_message else (" ".join(context.args) or update.effective_user.first_name) await update.message.reply_text(f"{target}, {random.choice(COMPLIMENTS)}")

async def cmd_roast(update: Update, context: ContextTypes.DEFAULT_TYPE): # Respect toggle if not settings_col.find_one({"_id": "feature_flags", "roast_enabled": True}): await update.message.reply_text("Roast is disabled by admin.") return target = update.message.reply_to_message.from_user.first_name if update.message.reply_to_message else (" ".join(context.args) or update.effective_user.first_name) await update.message.reply_text(f"{target}, {random.choice(ROASTS)}")

async def cmd_countdown(update: Update, context: ContextTypes.DEFAULT_TYPE): try: date_str, event = context.args dt = datetime.strptime(date_str, "%Y-%m-%d") diff = dt - datetime.utcnow() if diff.total_seconds() < 0: await update.message.reply_text("⏳ That date is in the past!") return name = " ".join(event) or "Event" days = diff.days hours = int((diff.total_seconds() - days86400)//3600) await update.message.reply_text(f"⏳ {days} days, {hours} hours until {name}!") except Exception: await update.message.reply_text("Usage: /countdown YYYY-MM-DD EventName")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE): top = list(users_col.find().sort("messages", -1).limit(10)) if not top: await update.message.reply_text("No stats yet!") return lines = ["📊 Top talkers:"] for i, u in enumerate(top, 1): nm = u.get("first_name") or u.get("username") or str(u["user_id"]) lines.append(f"{i}. {nm} — {u.get('messages',0)} msgs, {u.get('emojis',0)} emojis") await update.message.reply_text("\n".join(lines))

-------- Premium commands --------

async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE): if not gate_premium(update.effective_user.id, "meme"): await update.message.reply_text("🔒 Premium required. Use /premium to learn more.") return # Try meme-api first try: r = requests.get("https://meme-api.com/gimme", timeout=6) data = r.json() url = data.get("url") title = data.get("title", "") if url: await update.message.reply_photo(photo=url, caption=title) return except Exception: pass # Fallback: Memegen simple template template = random.choice(["buzz","doge","fry","disastergirl","drake"]) top = quote_plus("Random meme") bottom = quote_plus("(fallback)") img = f"https://api.memegen.link/images/{template}/{top}/{bottom}.png" await update.message.reply_photo(photo=img, caption="(fallback via memegen)")

async def cmd_gif(update: Update, context: ContextTypes.DEFAULT_TYPE): if not gate_premium(update.effective_user.id, "gif"): await update.message.reply_text("🔒 Premium required. Use /premium to learn more.") return query = " ".join(context.args) or "funny" # Prefer Tenor if key present if TENOR_API_KEY: try: url = f"https://tenor.googleapis.com/v2/search?q={quote_plus(query)}&key={TENOR_API_KEY}&limit=1" res = requests.get(url, timeout=6).json() if res.get("results"): gif_url = res["results"][0]["media_formats"]["gif"]["url"] await update.message.reply_animation(gif_url) return except Exception: pass # Fallback to Giphy if GIPHY_API_KEY: try: url = f"https://api.giphy.com/v1/gifs/search?api_key={GIPHY_API_KEY}&q={quote_plus(query)}&limit=1" res = requests.get(url, timeout=6).json() data = res.get("data") if data: gif_url = data[0]["images"]["original"]["url"] await update.message.reply_animation(gif_url) return except Exception: pass await update.message.reply_text("Configure TENOR_API_KEY or GIPHY_API_KEY to use /gif.")

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE): if not gate_premium(update.effective_user.id, "quiz"): await update.message.reply_text("🔒 Premium required. Use /premium to learn more.") return q = random.choice(QUIZ) keyboard = [[InlineKeyboardButton(opt, callback_data=f"quiz:{i}") for i, opt in enumerate(q["opts")]]] context.user_data["quiz_ans"] = q["ans"] context.user_data["quiz_q"] = q["q"] await update.message.reply_text(q["q"], reply_markup=InlineKeyboardMarkup(keyboard))

async def cb_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() data = query.data if not data.startswith("quiz:"): return choice = int(data.split(":")[1]) ans = context.user_data.get("quiz_ans") q = context.user_data.get("quiz_q", "") if ans is None: await query.edit_message_text("Quiz expired. Try /quiz again.") return msg = f"Q: {q}\nYour answer: {choice+1} → " + ("✅ Correct" if choice == ans else "❌ Wrong") await query.edit_message_text(msg)

-------- Admin controls --------

async def cmd_linkchannel(update: Update, context: ContextTypes.DEFAULT_TYPE): uid = update.effective_user.id if not is_admin(uid): await update.message.reply_text("Admins only.") return if not context.args: await update.message.reply_text("Usage: /linkchannel @username") return handle = context.args[0] set_linked_channel(handle) await update.message.reply_text(f"✅ Linked channel set to {get_linked_channel()}")

async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE): uid = update.effective_user.id if not is_admin(uid): await update.message.reply_text("Admins only.") return text = update.message.text.partition(" ")[2].strip() if not text: await update.message.reply_text("Usage: /announce <text>") return channel = get_linked_channel() try: await context.bot.send_message(chat_id=channel, text=text) await update.message.reply_text("✅ Announced to channel.") except Exception as e: await update.message.reply_text(f"Failed: {e}")

async def cmd_grantpremium(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): await update.message.reply_text("Admins only.") return if not context.args: await update.message.reply_text("Usage: /grantpremium <user_id>") return try: uid = int(context.args[0]) premium_col.update_one({"user_id": uid}, {"$set": {"active": True, "granted_at": datetime.utcnow()}}, upsert=True) await update.message.reply_text(f"✅ Premium granted to {uid}") except ValueError: await update.message.reply_text("Provide a numeric user_id")

async def cmd_revokepremium(update: Update, context: ContextTypes.DEFAULT_TYPE): if not is_admin(update.effective_user.id): await update.message.reply_text("Admins only.") return if not context.args: await update.message.reply_text("Usage: /revokepremium <user_id>") return try: uid = int(context.args[0]) premium_col.update_one({"user_id": uid}, {"$set": {"active": False, "revoked_at": datetime.utcnow()}}, upsert=True) await update.message.reply_text(f"🚫 Premium revoked for {uid}") except ValueError: await update.message.reply_text("Provide a numeric user_id")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(f"Chat ID: {update.effective_chat.id}\nYour ID: {update.effective_user.id}", parse_mode=ParseMode.MARKDOWN)

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.message and update.effective_user: inc_stats(update.effective_user, update.message.text or "")

-------------------- Flask Dashboard --------------------

app = Flask(name)

@app.get("/") def root(): return "✅ PlayPalu Dashboard is running. /leaderboard /user?user_id=123 /admin?secret=..."

@app.get("/leaderboard") def leaderboard(): top = list(users_col.find().sort("messages", -1).limit(20)) payload = [ { "user_id": u.get("user_id"), "username": u.get("username"), "first_name": u.get("first_name"), "messages": u.get("messages", 0), "emojis": u.get("emojis", 0), } for u in top ] return jsonify(payload)

@app.get("/user") def user_view(): try: uid = int(request.args.get("user_id", "0")) except ValueError: return jsonify({"error": "user_id must be int"}), 400 doc = users_col.find_one({"user_id": uid}) if not doc: return jsonify({"error": "not found"}), 404 premium = is_premium(uid) return jsonify({ "user_id": uid, "username": doc.get("username"), "first_name": doc.get("first_name"), "messages": doc.get("messages", 0), "emojis": doc.get("emojis", 0), "premium": premium, })

@app.route("/admin", methods=["GET", "POST"]) def admin(): secret = request.args.get("secret") or request.headers.get("X-Admin-Secret") if secret != ADMIN_SECRET: return jsonify({"error": "forbidden"}), 403 if request.method == "POST": action = request.form.get("action") if action == "broadcast": text = request.form.get("text", "") target = request.form.get("target", "channel") try: bot = Bot(BOT_TOKEN) if target == "group" and GROUP_ID: bot.send_message(chat_id=int(GROUP_ID), text=text) else: bot.send_message(chat_id=get_linked_channel(), text=text) return "Sent" except Exception as e: return f"Failed: {e}", 500 elif action == "toggle": key = request.form.get("key")  # e.g., meme_enabled val = request.form.get("value", "true").lower() == "true" settings_col.update_one({"_id": "feature_flags"}, {"$set": {key: val}}, upsert=True) return "Toggled" # Simple HTML return ( "<h1>Admin</h1>" "<form method='post'>" "<input name='text' placeholder='Broadcast text'>" "<select name='target'><option value='channel'>Channel</option><option value='group'>Group</option></select>" "<input type='hidden' name='action' value='broadcast'>" "<button>Send</button></form>" "<hr>" "<form method='post'>" "<input name='key' placeholder='meme_enabled'>" "<input name='value' placeholder='true/false'>" "<input type='hidden' name='action' value='toggle'>" "<button>Toggle</button></form>" )

-------------------- Run both (Polling + Flask) --------------------

def run_flask(): port = int(os.getenv("PORT", 8080)) app.run(host="0.0.0.0", port=port)

def run_bot(): application = ApplicationBuilder().token(BOT_TOKEN).build()

# Commands
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CommandHandler("help", cmd_help))
application.add_handler(CommandHandler("premium", cmd_premium))
application.add_handler(CommandHandler("quote", cmd_quote))
application.add_handler(CommandHandler("joke", cmd_joke))
application.add_handler(CommandHandler("roll", cmd_roll))
application.add_handler(CommandHandler("flip", cmd_flip))
application.add_handler(CommandHandler("rps", cmd_rps))
application.add_handler(CommandHandler("poll", cmd_poll))
application.add_handler(CommandHandler("random", cmd_random))
application.add_handler(CommandHandler("compliment", cmd_compliment))
application.add_handler(CommandHandler("roast", cmd_roast))
application.add_handler(CommandHandler("countdown", cmd_countdown))
application.add_handler(CommandHandler("stats", cmd_stats))
application.add_handler(CommandHandler("meme", cmd_meme))
application.add_handler(CommandHandler("gif", cmd_gif))
application.add_handler(CommandHandler("quiz", cmd_quiz))
application.add_handler(CommandHandler("linkchannel", cmd_linkchannel))
application.add_handler(CommandHandler("announce", cmd_announce))
application.add_handler(CommandHandler("grantpremium", cmd_grantpremium))
application.add_handler(CommandHandler("revokepremium", cmd_revokepremium))
application.add_handler(CommandHandler("id", cmd_id))
application.add_handler(CallbackQueryHandler(cb_quiz))

# Message tracker
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

application.run_polling(allowed_updates=Update.ALL_TYPES)

if name == "main": t = threading.Thread(target=run_flask, daemon=True) t.start() run_bot()

