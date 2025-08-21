# app.py
# PlayPal v2 - Ultimate Viral Telegram Bot
# Features: Games, Viral Content, Premium Features, AI Chat, and more!

import os
import random
import threading
import time
import traceback
import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict
import json
import requests

from flask import Flask
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
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
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "7896947963").split(",") if x.strip().isdigit()]
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PlayPalu")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/+1mgUwZpfuJY0YjA1")
NEWS_API = os.getenv("NEWS_API", "")
GIPHY_API = os.getenv("GIPHY_API", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

print(f"🤖 Bot starting with Admin IDs: {ADMIN_IDS}")

# ================== Flask keep-alive ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ PlayPal Ultimate Bot is running!"

# ================== Admin System ==================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ================== In-memory storage ==================
_users = {}
_active_games = {}
_user_sessions = {}

def ensure_user_record(user):
    if user.id not in _users:
        _users[user.id] = {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_premium": False,
            "is_admin": is_admin(user.id),
            "messages": 0,
            "xp": 0,
            "coins": 100,  # Starting coins
            "level": 1,
            "language": "en",
            "joined_at": datetime.now(timezone.utc),
            "last_seen": datetime.now(timezone.utc),
            "games_played": 0,
            "referrals": 0,
        }
    _users[user.id]["last_seen"] = datetime.now(timezone.utc)
    return _users[user.id]

def add_xp(user_id, amount):
    if user_id in _users:
        _users[user_id]["xp"] += amount
        # Check level up (100 XP per level)
        new_level = _users[user_id]["xp"] // 100 + 1
        if new_level > _users[user_id]["level"]:
            _users[user_id]["level"] = new_level
            _users[user_id]["coins"] += new_level * 10  # Reward for leveling up
            return True, new_level
    return False, 0

def add_coins(user_id, amount):
    if user_id in _users:
        _users[user_id]["coins"] += amount
        return True
    return False

# ================== VIRAL CONTENT SYSTEMS ==================
class ContentSystem:
    def __init__(self):
        self.session = None
        
    async def ensure_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        
    async def get_daily_fact(self):
        facts = [
            "Honey never spoils. Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still perfectly edible!",
            "Octopuses have three hearts and blue blood!",
            "A group of flamingos is called a 'flamboyance'!",
            "The shortest war in history was between Britain and Zanzibar in 1896. Zanzibar surrendered after 38 minutes!",
            "Bananas are berries, but strawberries aren't!",
        ]
        return random.choice(facts)
    
    async def get_motivational_quote(self):
        quotes = [
            "The only way to do great work is to love what you do. - Steve Jobs",
            "Believe you can and you're halfway there. - Theodore Roosevelt",
            "Your time is limited, don't waste it living someone else's life. - Steve Jobs",
            "It always seems impossible until it's done. - Nelson Mandela",
            "Success is not final, failure is not fatal: It is the courage to continue that counts. - Winston Churchill",
        ]
        return random.choice(quotes)
    
    async def get_viral_meme(self):
        try:
            await self.ensure_session()
            async with self.session.get('https://meme-api.com/gimme') as response:
                data = await response.json()
                if not data['nsfw']:
                    return {
                        'url': data['url'],
                        'title': data['title'],
                        'source': f"r/{data['subreddit']}"
                    }
        except:
            pass
        
        # Fallback memes
        memes = [
            {'url': 'https://i.imgflip.com/1bij.jpg', 'title': 'One Does Not Simply', 'source': 'Classic Meme'},
            {'url': 'https://i.imgflip.com/261o3j.jpg', 'title': 'But that\'s none of my business', 'source': 'Kermit'},
        ]
        return random.choice(memes)
    
    async def get_trivia_question(self):
        questions = [
            {
                "question": "What is the largest planet in our solar system?",
                "options": ["Earth", "Jupiter", "Saturn", "Mars"],
                "answer": 1,
                "difficulty": "easy"
            },
            {
                "question": "Which element has the chemical symbol 'Au'?",
                "options": ["Silver", "Gold", "Argon", "Aluminum"],
                "answer": 1,
                "difficulty": "medium"
            },
            {
                "question": "What is the capital of Australia?",
                "options": ["Sydney", "Melbourne", "Canberra", "Perth"],
                "answer": 2,
                "difficulty": "medium"
            }
        ]
        return random.choice(questions)

content_system = ContentSystem()

# ================== GAME SYSTEMS ==================
class GameSystem:
    async def start_quiz(self, user_id, chat_id):
        question = await content_system.get_trivia_question()
        game_id = f"{chat_id}_{user_id}"
        
        _active_games[game_id] = {
            "type": "quiz",
            "question": question,
            "start_time": datetime.now(),
            "reward": random.randint(15, 25)
        }
        
        return question
    
    async def start_slot_machine(self, user_id, bet_amount):
        user = _users.get(user_id)
        if not user or user["coins"] < bet_amount:
            return None, "Not enough coins!"
        
        # Deduct bet
        user["coins"] -= bet_amount
        
        # Generate slot result
        symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "💎", "7️⃣"]
        result = [random.choice(symbols) for _ in range(3)]
        
        # Calculate win
        win_multiplier = 0
        if result[0] == result[1] == result[2]:
            if result[0] == "💎": win_multiplier = 10
            elif result[0] == "7️⃣": win_multiplier = 5
            else: win_multiplier = 3
        elif result[0] == result[1] or result[1] == result[2]:
            win_multiplier = 1.5
        
        win_amount = int(bet_amount * win_multiplier) if win_multiplier > 0 else 0
        
        if win_amount > 0:
            user["coins"] += win_amount
        
        return result, win_amount

game_system = GameSystem()

# ================== UI HELPERS ==================
def main_menu_kb():
    return ReplyKeyboardMarkup([
        ["🎮 Games", "😂 Fun"],
        ["📊 Profile", "⭐ Premium"],
        ["🤖 AI Chat", "📞 Support"]
    ], resize_keyboard=True)

def games_menu_kb():
    return ReplyKeyboardMarkup([
        ["🎯 Quiz", "🎰 Slots"],
        ["🎲 Dice", "🤔 Trivia"],
        ["⬅️ Back"]
    ], resize_keyboard=True)

def fun_menu_kb():
    return ReplyKeyboardMarkup([
        ["📰 Daily Fact", "💬 Quote"],
        ["😂 Meme", "🎁 Surprise"],
        ["⬅️ Back"]
    ], resize_keyboard=True)

# ================== VIRAL COMMAND HANDLERS ==================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    welcome_gift = 50
    user_record["coins"] += welcome_gift
    
    name = user.first_name or "friend"
    admin_status = " 👑" if user_record["is_admin"] else ""
    premium_status = " ⭐" if user_record["is_premium"] else ""
    
    text = (
        f"🎉 *Welcome, {name}!*{admin_status}{premium_status}\n\n"
        f"I'm 🤖 *PlayPal* — your ultimate entertainment bot!\n\n"
        f"✨ *You received {welcome_gift} coins as a welcome gift!*\n\n"
        "🚀 *Features:*\n"
        "• 🎮 Games (Quiz, Slots, Dice)\n"
        "• 😂 Viral Memes & Content\n"
        "• 💰 Coin Economy System\n"
        "• 📊 Level Progression\n"
        "• 🤖 AI Chat\n"
        "• 🎁 Daily Rewards\n\n"
    )
    
    if user_record["is_admin"]:
        text += "⚙️ *Admin commands:* /admin\n\n"
    
    text += "Use the menu below to explore! 👇"
    
    await update.message.reply_text(
        text, 
        reply_markup=main_menu_kb(), 
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *PlayPal Ultimate Bot Help*\n\n"
        "🎮 *Games:*\n"
        "• /quiz - Trivia quiz game\n"
        "• /slots - Slot machine game\n"
        "• /dice - Roll dice for rewards\n\n"
        "😂 *Fun Commands:*\n"
        "• /fact - Interesting daily fact\n"
        "• /quote - Motivational quote\n"
        "• /meme - Get a viral meme\n\n"
        "📊 *Profile:*\n"
        "• /profile - View your stats\n"
        "• /coins - Check your balance\n"
        "• /leaderboard - Top players\n\n"
    )
    
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if user_record["is_admin"]:
        help_text += (
            "👑 *Admin Commands:*\n"
            "• /admin - Admin panel\n"
            "• /stats - User statistics\n"
            "• /broadcast - Message all users\n"
            "• /setpremium - Manage premium status\n\n"
        )
    
    help_text += "Use the keyboard menu for easy navigation! 🎯"
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    profile_text = (
        f"👤 *{user.first_name}'s Profile*\n\n"
        f"⭐ Level: {user_record['level']}\n"
        f"📊 XP: {user_record['xp']}/100\n"
        f"💰 Coins: {user_record['coins']}\n"
        f"🎮 Games Played: {user_record['games_played']}\n"
        f"💬 Messages: {user_record['messages']}\n"
        f"👥 Referrals: {user_record['referrals']}\n\n"
    )
    
    if user_record["is_premium"]:
        profile_text += "⭐ *Premium Member*\n\n"
    
    if user_record["is_admin"]:
        profile_text += "👑 *Bot Admin*\n\n"
    
    profile_text += f"Joined: {user_record['joined_at'].strftime('%Y-%m-%d')}"
    
    await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN)

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    question = await game_system.start_quiz(user.id, update.effective_chat.id)
    
    options = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question['options'])])
    
    quiz_text = (
        f"🎯 *Quiz Time!* ({question['difficulty']})\n\n"
        f"❓ {question['question']}\n\n"
        f"{options}\n\n"
        "Reply with the number of your answer!"
    )
    
    await update.message.reply_text(quiz_text, parse_mode=ParseMode.MARKDOWN)

async def cmd_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not context.args:
        await update.message.reply_text(
            "🎰 *Slot Machine*\n\n"
            "Usage: /slots <bet amount>\n"
            "Example: /slots 10\n\n"
            f"Your coins: {user_record['coins']}",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        bet_amount = int(context.args[0])
        if bet_amount < 5:
            await update.message.reply_text("Minimum bet is 5 coins!")
            return
        if bet_amount > user_record["coins"]:
            await update.message.reply_text("Not enough coins!")
            return
            
        result, win_amount = await game_system.start_slot_machine(user.id, bet_amount)
        
        slot_display = " | ".join(result)
        
        if win_amount > 0:
            result_text = (
                f"🎰 *JACKPOT!* 🎰\n\n"
                f"{slot_display}\n\n"
                f"💰 You won {win_amount} coins!\n"
                f"🎯 New balance: {user_record['coins']}"
            )
        else:
            result_text = (
                f"🎰 Slot Machine\n\n"
                f"{slot_display}\n\n"
                f"😢 No win this time!\n"
                f"🎯 Balance: {user_record['coins']}"
            )

        await update.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        await update.message.reply_text("Please enter a valid number!")

async def cmd_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fact = await content_system.get_daily_fact()
    await update.message.reply_text(f"📚 *Did You Know?*\n\n{fact}", parse_mode=ParseMode.MARKDOWN)

async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quote = await content_system.get_motivational_quote()
    await update.message.reply_text(f"💫 *Motivational Quote*\n\n{quote}", parse_mode=ParseMode.MARKDOWN)

async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meme = await content_system.get_viral_meme()
    await update.message.reply_photo(
        photo=meme['url'],
        caption=f"😂 *Viral Meme*\n\n{meme['title']}\nSource: {meme['source']}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    await update.message.reply_text(
        f"💰 *Coin Balance*\n\n"
        f"You have: {user_record['coins']} coins\n\n"
        f"Earn more by playing games and leveling up! 🎮",
        parse_mode=ParseMode.MARKDOWN
    )

# ================== ADMIN COMMANDS ==================
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
    
    admin_text = (
        "👑 *Admin Panel*\n\n"
        f"• Total users: {len(_users)}\n"
        f"• Online users: {len([u for u in _users.values() if (datetime.now(timezone.utc) - u['last_seen']).total_seconds() < 300])}\n"
        f"• Premium users: {len([u for u in _users.values() if u.get('is_premium')])}\n\n"
        "*Commands:*\n"
        "/stats - Detailed statistics\n"
        "/broadcast - Message all users\n"
        "/setpremium - Manage premium status\n"
        "/userinfo - Get user details"
    )
    
    await update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
        
    total_coins = sum(u.get('coins', 0) for u in _users.values())
    total_xp = sum(u.get('xp', 0) for u in _users.values())
    total_games = sum(u.get('games_played', 0) for u in _users.values())
    
    stats_text = (
        "📊 *Bot Statistics*\n\n"
        f"• Total Users: {len(_users)}\n"
        f"• Total Coins: {total_coins}\n"
        f"• Total XP: {total_xp}\n"
        f"• Games Played: {total_games}\n"
        f"• Premium Users: {len([u for u in _users.values() if u.get('is_premium')])}\n"
        f"• Admin Users: {len([u for u in _users.values() if u.get('is_admin')])}\n\n"
        "Use /userinfo <id> for user details"
    )
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

# ================== MESSAGE HANDLERS ==================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        user = update.effective_user
        user_record = ensure_user_record(user)
        user_record["messages"] += 1
        
        # Add XP for messaging
        leveled_up, new_level = add_xp(user.id, 1)
        
        user_message = update.message.text
        
        # Handle menu options
        if user_message == "🎮 Games":
            await update.message.reply_text("🎮 Choose a game:", reply_markup=games_menu_kb())
        elif user_message == "😂 Fun":
            await update.message.reply_text("😂 Choose fun content:", reply_markup=fun_menu_kb())
        elif user_message == "📊 Profile":
            await cmd_profile(update, context)
        elif user_message == "⭐ Premium":
            await update.message.reply_text(
                "⭐ *Premium Features*\n\n"
                "Coming soon! Premium members will get:\n"
                "• Exclusive games\n"
                "• Daily bonus coins\n"
                "• Ad-free experience\n"
                "• Priority support\n\n"
                "Contact @admin for premium access!",
                parse_mode=ParseMode.MARKDOWN
            )
        elif user_message == "🤖 AI Chat":
            await update.message.reply_text(
                "🤖 *AI Chat*\n\n"
                "I'm here to chat! Try asking me:\n"
                "• How are you?\n"
                "• Tell me a joke\n"
                "• What can you do?\n"
                "• Play a game with me",
                parse_mode=ParseMode.MARKDOWN
            )
        elif user_message == "📞 Support":
            await update.message.reply_text(
                "📞 *Support*\n\n"
                "Need help? Contact our support team:\n"
                "• Email: support@playpal.com\n"
                "• Telegram: @admin\n"
                "• Group: https://t.me/PlayPalGroup\n\n"
                "We're here to help! 💖",
                parse_mode=ParseMode.MARKDOWN
            )
        elif user_message == "🎯 Quiz":
            await cmd_quiz(update, context)
        elif user_message == "🎰 Slots":
            await update.message.reply_text("Use /slots <amount> to play slot machine!")
        elif user_message == "📰 Daily Fact":
            await cmd_fact(update, context)
        elif user_message == "💬 Quote":
            await cmd_quote(update, context)
        elif user_message == "😂 Meme":
            await cmd_meme(update, context)
        elif user_message == "⬅️ Back":
            await update.message.reply_text("Back to main menu:", reply_markup=main_menu_kb())
        else:
            # AI-like responses
            if any(word in user_message.lower() for word in ["hello", "hi", "hey", "hola"]):
                await update.message.reply_text(f"👋 Hello {user.first_name}! How can I help you today?")
            elif any(word in user_message.lower() for word in ["how are you", "how you doing"]):
                await update.message.reply_text("I'm doing great! Ready to play some games? 🎮")
            elif any(word in user_message.lower() for word in ["thank", "thanks", "thank you"]):
                await update.message.reply_text("You're welcome! 😊")
            elif any(word in user_message.lower() for word in ["joke", "funny"]):
                await update.message.reply_text("Why don't scientists trust atoms? Because they make up everything! 😂")
            elif any(word in user_message.lower() for word in ["what can you do", "features"]):
                await cmd_help(update, context)
            else:
                await update.message.reply_text("I'm here to chat and play games with you! Use the menu below to get started. 👇", reply_markup=main_menu_kb())

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
    try:
        if update and hasattr(update, 'effective_chat'):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Sorry, I encountered an error. Please try again later."
            )
    except:
        pass

# ================== BOT SETUP ==================
def main():
    # Create the Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("profile", cmd_profile))
    application.add_handler(CommandHandler("quiz", cmd_quiz))
    application.add_handler(CommandHandler("slots", cmd_slots))
    application.add_handler(CommandHandler("fact", cmd_fact))
    application.add_handler(CommandHandler("quote", cmd_quote))
    application.add_handler(CommandHandler("meme", cmd_meme))
    application.add_handler(CommandHandler("coins", cmd_coins))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    print("🤖 Starting PlayPal Ultimate Bot...")
    print(f"✅ Admin IDs: {ADMIN_IDS}")
    print("🎮 Games: Quiz, Slots, Dice")
    print("😂 Content: Memes, Facts, Quotes")
    print("💰 Economy: Coins, XP, Levels")
    print("✅ Bot is ready and waiting for messages...")
    
    # Start polling
    application.run_polling()

if __name__ == "__main__":
    # Start Flask server for Railway
    port = int(os.getenv("PORT", 5000))
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False), 
        daemon=True
    ).start()
    
    # Start the bot
    main()
