import os
import random
import requests
from datetime import datetime
from flask import Flask, request
from pymongo import MongoClient
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)

# ----------------------------
# ENV VARIABLES
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@PlayPalu")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "supersecret")

# ----------------------------
# DATABASE (MongoDB)
# ----------------------------
client = MongoClient(MONGO_URI)
db = client["playpalu"]
users = db["users"]
settings = db["settings"]

# ----------------------------
# FLASK DASHBOARD
# ----------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ PlayPalu Bot Dashboard is running!"

@app.route("/leaderboard")
def leaderboard():
    top = users.find().sort("messages", -1).limit(10)
    html = "<h1>📊 Leaderboard</h1><ul>"
    for u in top:
        html += f"<li>@{u.get('username','unknown')} — {u.get('messages',0)} msgs</li>"
    html += "</ul>"
    return html

@app.route("/admin", methods=["GET", "POST"])
def admin():
    secret = request.args.get("secret")
    if secret != ADMIN_SECRET:
        return "❌ Unauthorized"
    if request.method == "POST":
        msg = request.form["msg"]
        return f"✅ Broadcast ready: {msg}"
    return '''
        <h1>Admin Dashboard</h1>
        <form method="post">
            <input name="msg" placeholder="Broadcast message">
            <button type="submit">Send</button>
        </form>
    '''

# ----------------------------
# UTILITIES
# ----------------------------
def update_user(user):
    users.update_one(
        {"user_id": user.id},
        {"$inc": {"messages": 1},
         "$set": {"username": user.username, "last_active": datetime.utcnow()}},
        upsert=True
    )

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def gate_premium(user_id: int, feature: str) -> bool:
    u = users.find_one({"user_id": user_id})
    if u and u.get("premium", False):
        return True
    return False

# ----------------------------
# COMMANDS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to PlayPalu Bot! Type /help to explore features.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Available Commands:\n"
        "/quote — Random motivational quote\n"
        "/joke — Random joke\n"
        "/roll — Dice roll 🎲\n"
        "/flip — Flip a coin 🪙\n"
        "/rps <rock/paper/scissors>\n"
        "/poll <question> opt1,opt2,opt3\n"
        "/random opt1,opt2,opt3\n"
        "/compliment @user\n"
        "/roast @user\n"
        "/stats — Your activity stats\n"
        "/leaderboard — Top users\n"
        "\n✨ Premium Commands:\n"
        "/meme — Get a meme\n"
        "/gif <keyword> — Get a gif\n"
        "/quiz — Trivia question\n"
        "\n🔑 Use /premium to learn more."
    )

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get("https://api.quotable.io/random").json()
    await update.message.reply_text(f"💡 {r['content']} — {r['author']}")

async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get("https://v2.jokeapi.dev/joke/Any").json()
    if r.get("type") == "single":
        await update.message.reply_text(r["joke"])
    else:
        await update.message.reply_text(f"{r['setup']} … {r['delivery']}")

async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🎲 You rolled {random.randint(1,6)}")

async def flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🪙 {random.choice(['Heads','Tails'])}")

async def rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rps rock|paper|scissors")
        return
    user = context.args[0].lower()
    bot = random.choice(["rock","paper","scissors"])
    result = "🤝 Draw!"
    if (user=="rock" and bot=="scissors") or (user=="paper" and bot=="rock") or (user=="scissors" and bot=="paper"):
        result = "🎉 You win!"
    elif user != bot:
        result = "😢 You lose!"
    await update.message.reply_text(f"You: {user}\nBot: {bot}\n{result}")

async def poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /poll Question | opt1,opt2,opt3")
        return
    text = " ".join(context.args)
    if "|" not in text:
        await update.message.reply_text("Format: /poll Question | opt1,opt2")
        return
    question, opts = text.split("|",1)
    options = [o.strip() for o in opts.split(",")]
    await context.bot.send_poll(update.effective_chat.id, question.strip(), options)

async def random_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /random opt1,opt2,opt3")
        return
    options = " ".join(context.args).split(",")
    await update.message.reply_text(f"🎯 {random.choice(options).strip()}")

async def compliment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = " ".join(context.args) if context.args else update.effective_user.first_name
    compliments = ["You're awesome!","You rock!","Looking sharp!","Legend!"]
    await update.message.reply_text(f"💖 {target}, {random.choice(compliments)}")

async def roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = " ".join(context.args) if context.args else update.effective_user.first_name
    roasts = ["Did you run out of brain cells?","I've seen smarter potatoes.","Try harder, buddy."]
    await update.message.reply_text(f"🔥 {target}, {random.choice(roasts)}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = users.find_one({"user_id": update.effective_user.id}) or {}
    await update.message.reply_text(
        f"📊 Stats for @{update.effective_user.username}:\n"
        f"Messages: {u.get('messages',0)}\n"
        f"Last Active: {u.get('last_active','Never')}"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = users.find().sort("messages", -1).limit(5)
    text = "🏆 Leaderboard:\n"
    for i,u in enumerate(top,1):
        text += f"{i}. @{u.get('username','unknown')} — {u.get('messages',0)} msgs\n"
    await update.message.reply_text(text)

# ----------------------------
# PREMIUM FEATURES
# ----------------------------
QUIZ = [
    {"q":"Capital of France?","opts":["Paris","Berlin","Rome"],"ans":0},
    {"q":"5+7?","opts":["10","12","13"],"ans":1},
]

async def meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not gate_premium(update.effective_user.id, "meme"):
        await update.message.reply_text("🔒 Premium required. Use /premium.")
        return
    r = requests.get("https://meme-api.com/gimme").json()
    await update.message.reply_photo(r["url"], caption=r["title"])

async def gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not gate_premium(update.effective_user.id, "gif"):
        await update.message.reply_text("🔒 Premium required. Use /premium.")
        return
    q = " ".join(context.args) or "funny"
    r = requests.get(f"https://g.tenor.com/v1/search?q={q}&key=LIVDSRZULELA&limit=5").json()
    gif_url = random.choice(r["results"])["media"][0]["gif"]["url"]
    await update.message.reply_animation(gif_url)

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not gate_premium(update.effective_user.id, "quiz"):
        await update.message.reply_text("🔒 Premium required. Use /premium.")
        return
    q = random.choice(QUIZ)
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"quiz:{i}")]
                for i,opt in enumerate(q["opts"])]
    context.user_data["quiz_ans"] = q["ans"]
    context.user_data["quiz_q"] = q["q"]
    await update.message.reply_text(q["q"], reply_markup=InlineKeyboardMarkup(keyboard))

async def quiz_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = int(query.data.split(":")[1])
    ans = context.user_data.get("quiz_ans")
    q = context.user_data.get("quiz_q")
    if choice == ans:
        await query.edit_message_text(f"✅ Correct! {q}")
    else:
        await query.edit_message_text(f"❌ Wrong! {q}")

async def premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ Premium unlocks: /meme, /gif, /quiz.\n"
        "Ask admin to grant you access!"
    )

# ----------------------------
# ADMIN COMMANDS
# ----------------------------
async def grant_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /grantpremium <user_id>")
        return
    uid = int(context.args[0])
    users.update_one({"user_id": uid}, {"$set":{"premium":True}}, upsert=True)
    await update.message.reply_text(f"✅ Premium granted to {uid}")

async def revoke_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /revokepremium <user_id>")
        return
    uid = int(context.args[0])
    users.update_one({"user_id": uid}, {"$set":{"premium":False}}, upsert=True)
    await update.message.reply_text(f"❌ Premium revoked for {uid}")

# ----------------------------
# HANDLERS
# ----------------------------
async def message_logger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        update_user(update.effective_user)

def main():
    app_telegram = Application.builder().token(BOT_TOKEN).build()

    app_telegram.add_handler(CommandHandler("start", start))
    app_telegram.add_handler(CommandHandler("help", help_cmd))
    app_telegram.add_handler(CommandHandler("quote", quote))
    app_telegram.add_handler(CommandHandler("joke", joke))
    app_telegram.add_handler(CommandHandler("roll", roll))
    app_telegram.add_handler(CommandHandler("flip", flip))
    app_telegram.add_handler(CommandHandler("rps", rps))
    app_telegram.add_handler(CommandHandler("poll", poll))
    app_telegram.add_handler(CommandHandler("random", random_choice))
    app_telegram.add_handler(CommandHandler("compliment", compliment))
    app_telegram.add_handler(CommandHandler("roast", roast))
    app_telegram.add_handler(CommandHandler("stats", stats))
    app_telegram.add_handler(CommandHandler("leaderboard", leaderboard))

    # Premium
    app_telegram.add_handler(CommandHandler("meme", meme))
    app_telegram.add_handler(CommandHandler("gif", gif))
    app_telegram.add_handler(CommandHandler("quiz", cmd_quiz))
    app_telegram.add_handler(CallbackQueryHandler(quiz_button, pattern="^quiz:"))
    app_telegram.add_handler(CommandHandler("premium", premium_info))

    # Admin
    app_telegram.add_handler(CommandHandler("grantpremium", grant_premium))
    app_telegram.add_handler(CommandHandler("revokepremium", revoke_premium))

    # Logger
    app_telegram.add_handler(MessageHandler(filters.ALL, message_logger))

    app_telegram.run_polling()

if __name__ == "__main__":
    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    main()