# app.py
# PlayPal v2 - Ultimate Viral Telegram Bot with Group & Channel Integration
# Features: Games, Viral Content, Premium Features, AI Chat, Referrals, and more!

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
CHANNEL_LINK = "https://t.me/PlayPalu"  # Your channel link
GROUP_LINK = "https://t.me/playpalg"    # Your group link
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
            "referral_code": f"ref_{user.id}",
            "referred_by": None,
            "has_joined_channel": False,
            "has_joined_group": False,
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
    
    async def get_surprise_content(self):
        """Get random surprise content"""
        surprises = [
            {"type": "fact", "content": await self.get_daily_fact()},
            {"type": "quote", "content": await self.get_motivational_quote()},
            {"type": "meme", "content": await self.get_viral_meme()},
            {"type": "joke", "content": "Why don't scientists trust atoms? Because they make up everything!"},
            {"type": "tip", "content": "💡 Pro Tip: Play games daily to earn more coins and level up faster!"},
        ]
        return random.choice(surprises)

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

def social_menu_kb():
    return ReplyKeyboardMarkup([
        ["📢 Join Channel", "👥 Join Group"],
        ["🎉 Share Bot", "⬅️ Back"]
    ], resize_keyboard=True)

# ================== REFERRAL SYSTEM ==================
async def handle_referral_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle referral codes in start command"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if context.args and len(context.args) > 0:
        referral_code = context.args[0]
        if referral_code.startswith("ref_") and referral_code != user_record["referral_code"]:
            # Find the referrer
            for uid, data in _users.items():
                if data["referral_code"] == referral_code:
                    # Add referral bonus to both users
                    add_coins(uid, 50)  # Referrer gets 50 coins
                    add_coins(user.id, 50)  # New user gets 50 coins
                    _users[uid]["referrals"] += 1
                    user_record["referred_by"] = uid
                    return True
    return False

# ================== GAME COMMANDS ==================
async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    chat_id = update.effective_chat.id
    
    question = await game_system.start_quiz(user.id, chat_id)
    
    # Format options with numbers
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(question["options"])])
    
    quiz_text = (
        f"🎯 *Quiz Time!* 🎯\n\n"
        f"*{question['question']}*\n\n"
        f"{options_text}\n\n"
        f"💡 Difficulty: {question['difficulty'].title()}\n"
        f"💰 Reward: {_active_games[f'{chat_id}_{user.id}']['reward']} coins\n\n"
        f"Reply with the number of your answer!"
    )
    
    await update.message.reply_text(quiz_text, parse_mode=ParseMode.MARKDOWN)

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    game_id = f"{chat_id}_{user.id}"
    
    if game_id not in _active_games or _active_games[game_id]["type"] != "quiz":
        return
    
    try:
        answer = int(update.message.text.strip()) - 1
        question = _active_games[game_id]["question"]
        reward = _active_games[game_id]["reward"]
        
        if answer == question["answer"]:
            # Correct answer
            add_coins(user.id, reward)
            user_record = ensure_user_record(user)
            user_record["games_played"] += 1
            response = (
                f"✅ *Correct!* 🎉\n\n"
                f"You won {reward} coins!\n"
                f"Your total: {_users[user.id]['coins']} coins"
            )
        else:
            # Wrong answer
            correct_option = question["options"][question["answer"]]
            response = (
                f"❌ *Wrong answer!*\n\n"
                f"The correct answer was: {correct_option}\n\n"
                f"Better luck next time! 😊"
            )
        
        # Remove the active game
        del _active_games[game_id]
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        
    except (ValueError, IndexError):
        await update.message.reply_text("Please reply with a valid number (1, 2, 3, etc.)")

async def cmd_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not context.args:
        await update.message.reply_text("Usage: /slots <bet_amount>\nExample: /slots 10")
        return
    
    try:
        bet_amount = int(context.args[0])
        if bet_amount < 1:
            await update.message.reply_text("Bet amount must be at least 1 coin!")
            return
        
        result, win_amount = await game_system.start_slot_machine(user.id, bet_amount)
        
        if result is None:
            await update.message.reply_text(win_amount)  # Error message
            return
        
        slot_display = " | ".join(result)
        
        if win_amount > 0:
            response = (
                f"🎰 *SLOTS* 🎰\n\n"
                f"{slot_display}\n\n"
                f"🎉 *JACKPOT!* You won {win_amount} coins! 🎉\n\n"
                f"New balance: {user_record['coins']} coins"
            )
        else:
            response = (
                f"🎰 *SLOTS* 🎰\n\n"
                f"{slot_display}\n\n"
                f"❌ No win this time. Try again!\n\n"
                f"Balance: {user_record['coins']} coins"
            )
        
        user_record["games_played"] += 1
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        await update.message.reply_text("Please enter a valid number for your bet!")


# ================== CONTENT COMMANDS ==================
async def cmd_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fact = await content_system.get_daily_fact()
    await update.message.reply_text(f"📚 *Did You Know?*\n\n{fact}", parse_mode=ParseMode.MARKDOWN)

async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quote = await content_system.get_motivational_quote()
    await update.message.reply_text(f"💬 *Motivational Quote*\n\n{quote}", parse_mode=ParseMode.MARKDOWN)

async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meme = await content_system.get_viral_meme()
    await update.message.reply_text(f"😂 *Viral Meme*\n\n*{meme['title']}*\nFrom: {meme['source']}")
    await update.message.reply_photo(meme['url'])

async def cmd_surprise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    surprise = await content_system.get_surprise_content()
    
    if surprise["type"] == "fact":
        await update.message.reply_text(f"🎁 *Surprise Fact!* 🎁\n\n{surprise['content']}", parse_mode=ParseMode.MARKDOWN)
    elif surprise["type"] == "quote":
        await update.message.reply_text(f"🎁 *Surprise Quote!* 🎁\n\n{surprise['content']}", parse_mode=ParseMode.MARKDOWN)
    elif surprise["type"] == "meme":
        meme = surprise['content']
        await update.message.reply_text(f"🎁 *Surprise Meme!* 🎁\n\n*{meme['title']}*\nFrom: {meme['source']}")
        await update.message.reply_photo(meme['url'])
    elif surprise["type"] == "joke":
        await update.message.reply_text(f"🎁 *Surprise Joke!* 🎁\n\n{surprise['content']}")
    elif surprise["type"] == "tip":
        await update.message.reply_text(f"🎁 *Surprise Tip!* 🎁\n\n{surprise['content']}")

# ================== ECONOMY COMMANDS ==================
async def cmd_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    await update.message.reply_text(
        f"💰 *Coin Balance*\n\n"
        f"You have: {user_record['coins']} coins\n\n"
        f"Earn more by:\n"
        f"• Playing games 🎮\n"
        f"• Leveling up ⬆️\n"
        f"• Referring friends 👥\n"
        f"• Daily activities 📅",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_record['referral_code']}"
    
    await update.message.reply_text(
        f"👥 *Referral Program*\n\n"
        f"Share your link with friends:\n"
        f"`{referral_link}`\n\n"
        f"• You get 50 coins for each friend who joins\n"
        f"• Your friend gets 50 bonus coins too!\n"
        f"• Track your referrals with /profile\n\n"
        f"Current referrals: {user_record['referrals']}",
        parse_mode=ParseMode.MARKDOWN
    )

# ================== COMMUNITY COMMANDS ==================
async def cmd_community(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👥 *Join Our Community!*\n\n"
        f"📢 *Channel:* {CHANNEL_LINK}\n"
        f"• Get updates about new features\n"
        f"• See top players and winners\n\n"
        f"💬 *Group:* {GROUP_LINK}\n"
        f"• Chat with other players\n"
        f"• Get help and support\n"
        f"• Share your experiences\n\n"
        f"Use the buttons below to join:",
        reply_markup=social_menu_kb(),
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📢 *Join Our Channel!*\n\n"
        f"Get updates about:\n"
        f"• New games and features 🎮\n"
        f"• Special events and contests 🎉\n"
        f"• Top players and winners 🏆\n"
        f"• Maintenance announcements ⚙️\n\n"
        f"Click here to join: {CHANNEL_LINK}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💬 *Join Our Community Group!*\n\n"
        f"Connect with other players:\n"
        f"• Get help and support 🤝\n"
        f"• Share your experiences 💬\n"
        f"• Suggest new features 💡\n"
        f"• Participate in discussions 🗣️\n\n"
        f"Click here to join: {GROUP_LINK}",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = (await context.bot.get_me()).username
    share_text = (
        f"🎮 *Check out PlayPal Bot!* 🤖\n\n"
        f"An amazing Telegram bot with:\n"
        f"• Fun games to play 🎯🎰\n"
        f"• Viral memes and content 😂\n"
        f"• Coin economy system 💰\n"
        f"• Level progression 📊\n"
        f"• AI chat capabilities 🤖\n\n"
        f"Join the fun now: https://t.me/{bot_username}"
    )
    
    await update.message.reply_text(
        f"🎉 *Share PlayPal with Friends!*\n\n"
        f"Copy the message below and send it to your friends:",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(share_text, parse_mode=ParseMode.MARKDOWN)

# ================== ADMIN COMMANDS ==================
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Access denied. Admin only.")
        return
    
    admin_text = (
        "👑 *Admin Panel*\n\n"
        "Available commands:\n"
        "• /stats - Bot statistics\n"
        "• /broadcast - Send message to all users\n"
        "• /setpremium - Manage premium status\n"
        "• /message - Send message to specific user\n\n"
        f"Total users: {len(_users)}"
    )
    
    await update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ Access denied. Admin only.")
        return
    
    total_users = len(_users)
    total_messages = sum(user_data["messages"] for user_data in _users.values())
    total_games = sum(user_data["games_played"] for user_data in _users.values())
    total_coins = sum(user_data["coins"] for user_data in _users.values())
    
    # Find top 5 users by coins
    top_users = sorted(_users.values(), key=lambda x: x["coins"], reverse=True)[:5]
    top_users_text = "\n".join([f"{i+1}. {u['first_name']}: {u['coins']} coins" for i, u in enumerate(top_users)])
    
    stats_text = (
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total users: {total_users}\n"
        f"💬 Total messages: {total_messages}\n"
        f"🎮 Total games played: {total_games}\n"
        f"💰 Total coins in circulation: {total_coins}\n\n"
        f"🏆 *Top 5 Users by Coins:*\n"
        f"{top_users_text}"
    )
    
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

# ================== VIRAL COMMAND HANDLERS ==================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    # Handle referral first
    referral_bonus = await handle_referral_start(update, context)
    
    welcome_gift = 50
    user_record["coins"] += welcome_gift
    
    name = user.first_name or "friend"
    admin_status = " 👑" if user_record["is_admin"] else ""
    premium_status = " ⭐" if user_record["is_premium"] else ""
    
    text = (
        f"🎉 *Welcome, {name}!*{admin_status}{premium_status}\n\n"
        f"I'm 🤖 *PlayPal* — your ultimate entertainment bot!\n\n"
        f"✨ *You received {welcome_gift} coins as a welcome gift!*\n"
    )
    
    if referral_bonus:
        text += f"✨ *Bonus: 50 coins for using referral link!*\n\n"
    
    text += (
        "🚀 *Features:*\n"
        "• 🎮 Games (Quiz, Slots, Dice)\n"
        "• 😂 Viral Memes & Content\n"
        "• 💰 Coin Economy System\n"
        "• 📊 Level Progression\n"
        "• 🤖 AI Chat\n"
        "• 🎁 Daily Rewards\n"
        "• 📤 Referral Program\n\n"
        f"📢 *Join our community:*\n"
        f"Channel: {CHANNEL_LINK}\n"
        f"Group: {GROUP_LINK}\n\n"
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
        "• /meme - Get a viral meme\n"
        "• /surprise - Random surprise content\n\n"
        "📊 *Profile:*\n"
        "• /profile - View your stats\n"
        "• /coins - Check your balance\n"
        "• /refer - Get referral link\n\n"
        "👥 *Community:*\n"
        "• /community - Join channel & group\n"
        "• /channel - Our official channel\n"
        "• /group - Our community group\n"
        "• /share - Share bot with friends\n\n"
        "📞 *Support:*\n"
        "• @admin - Mention in any message\n"
        "• /contact - Send message to admins\n\n"
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
    
    profile_text += f"Joined: {user_record['joined_at'].strftime('%Y-%m-%d')}\n\n"
    profile_text += f"🔗 *Community Links:*\nChannel: {CHANNEL_LINK}\nGroup: {GROUP_LINK}"
    
    await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN)


# ================== CONTACT ADMIN SYSTEM ==================
async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle contact admin requests"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    message = " ".join(context.args) if context.args else "I would like to get help"
    
    contact_text = (
        f"📩 *Contact Request*\n\n"
        f"• From: {user.first_name} (@{user.username or 'No username'})\n"
        f"• User ID: `{user.id}`\n"
        f"• Message: {message}\n\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    # Send to all admins
    sent_count = 0
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=contact_text,
                parse_mode=ParseMode.MARKDOWN
            )
            sent_count += 1
            # Avoid rate limiting
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Failed to send to admin {admin_id}: {e}")
    
    if sent_count > 0:
        response = (
            "✅ *Message sent to admins!*\n\n"
            "Our team will contact you shortly. "
            "You can also join our support group for faster help:\n"
            f"{GROUP_LINK}"
        )
    else:
        response = (
            "❌ *Could not reach admins*\n\n"
            "Please try again later or join our support group:\n"
            f"{GROUP_LINK}"
        )
    
    await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

async def handle_admin_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle @admin mentions in messages"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    user_message = update.message.text
    
    # Check if message contains @admin
    if "@admin" in user_message.lower():
        contact_text = (
            f"📩 *Admin Mention*\n\n"
            f"• From: {user.first_name} (@{user.username or 'No username'})\n"
            f"• User ID: `{user.id}`\n"
            f"• Message: {user_message}\n\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # Send to all admins
        sent_count = 0
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=contact_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                sent_count += 1
                # Avoid rate limiting
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Failed to send to admin {admin_id}: {e}")
        
        if sent_count > 0:
            response = (
                "👋 *Hi! I see you mentioned @admin*\n\n"
                "Your message has been forwarded to our admin team. "
                "They'll contact you soon!\n\n"
                "For faster support, you can:\n"
                f"• Use /contact <message>\n"
                f"• Join our group: {GROUP_LINK}\n"
                f"• Check /help for common questions"
            )
        else:
            response = (
                "👋 *Hi! I see you mentioned @admin*\n\n"
                "Sorry, we couldn't reach our admin team right now. "
                "Please try:\n"
                f"• Using /contact <message>\n"
                f"• Joining our group: {GROUP_LINK}\n"
                f"• Checking /help for quick answers"
            )
        
        await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        return True
    
    return False

# ================== MESSAGE HANDLERS ==================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        user = update.effective_user
        user_record = ensure_user_record(user)
        user_record["messages"] += 1
        
        # Add XP for messaging
        leveled_up, new_level = add_xp(user.id, 1)
        if leveled_up:
            await update.message.reply_text(
                f"🎉 *Level Up!* 🎉\n\n"
                f"You reached level {new_level}!\n"
                f"+{new_level * 10} coins reward!",
                parse_mode=ParseMode.MARKDOWN
            )
        
        user_message = update.message.text
        chat_id = update.effective_chat.id
        game_id = f"{chat_id}_{user.id}"
        
        # Check if user has an active quiz first
        if game_id in _active_games and _active_games[game_id]["type"] == "quiz":
            await handle_quiz_answer(update, context)
            return
        
        # Check for @admin mention
        if await handle_admin_mention(update, context):
            return
        
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
                "Contact admins using /contact or mention @admin",
                parse_mode=ParseMode.MARKDOWN
            )
        elif user_message == "🤖 AI Chat":
            await update.message.reply_text(
                "🤖 *AI Chat*\n\n"
                "I'm here to chat! Try asking me:\n"
                "• How are you?\n"
                "• Tell me a joke\n"
                "• What can you do?\n"
                "• Play a game with me\n\n"
                "Need admin help? Mention @admin",
                parse_mode=ParseMode.MARKDOWN
            )
        elif user_message == "📞 Support":
            await update.message.reply_text(
                "📞 *Support*\n\n"
                "Need help? Here's how to reach us:\n"
                "• Mention @admin in any message\n"
                "• Use /contact <your message>\n"
                "• Join our group: {GROUP_LINK}\n\n"
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
        elif user_message == "🎁 Surprise":
            await cmd_surprise(update, context)
        elif user_message == "📢 Join Channel":
            await cmd_channel(update, context)
        elif user_message == "👥 Join Group":
            await cmd_group(update, context)
        elif user_message == "🎉 Share Bot":
            await cmd_share(update, context)
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
            elif any(word in user_message.lower() for word in ["admin", "help", "support"]):
                await update.message.reply_text(
                    "Need admin help? You can:\n"
                    "• Mention @admin in any message\n"
                    "• Use /contact <your message>\n"
                    "• Join our group: {GROUP_LINK}",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif any(word in user_message.lower() for word in ["channel", "group", "community"]):
                await cmd_community(update, context)
            else:
                await update.message.reply_text(
                    "I'm here to chat and play games with you! "
                    "Need admin help? Mention @admin 👇", 
                    reply_markup=main_menu_kb()
                )

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

# ================== CLEANUP TASKS ==================
async def cleanup_old_quizzes():
    """Clean up quizzes that are older than 10 minutes"""
    while True:
        try:
            current_time = datetime.now()
            expired_quizzes = []
            
            for game_id, game_data in _active_games.items():
                if game_data["type"] == "quiz":
                    time_diff = (current_time - game_data["start_time"]).total_seconds()
                    if time_diff > 600:  # 10 minutes
                        expired_quizzes.append(game_id)
            
            for game_id in expired_quizzes:
                del _active_games[game_id]
                print(f"Cleaned up expired quiz: {game_id}")
                
            await asyncio.sleep(300)  # Check every 5 minutes
            
        except Exception as e:
            print(f"Error in quiz cleanup: {e}")
            await asyncio.sleep(60)

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
    application.add_handler(CommandHandler("surprise", cmd_surprise))
    application.add_handler(CommandHandler("coins", cmd_coins))
    application.add_handler(CommandHandler("refer", cmd_refer))
    application.add_handler(CommandHandler("contact", cmd_contact))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("community", cmd_community))
    application.add_handler(CommandHandler("channel", cmd_channel))
    application.add_handler(CommandHandler("group", cmd_group))
    application.add_handler(CommandHandler("share", cmd_share))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    # Start quiz cleanup task after the application is running
    application.job_queue.run_repeating(
        lambda context: asyncio.create_task(cleanup_old_quizzes()),
        interval=300,  # Run every 5 minutes
        first=10  # Start after 10 seconds
    )

    print("🤖 Starting PlayPal Ultimate Bot...")
    print(f"✅ Admin IDs: {ADMIN_IDS}")
    print(f"📢 Channel: {CHANNEL_LINK}")
    print(f"👥 Group: {GROUP_LINK}")
    print("🎮 Games: Quiz, Slots, Dice")
    print("😂 Content: Memes, Facts, Quotes, Surprises")
    print("💰 Economy: Coins, XP, Levels, Referrals")
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