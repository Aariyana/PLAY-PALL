# app.py
# PlayPal v2 - Complete Automatic Telegram Bot
# Features: Auto jokes, memes, GIFs, games, and quizzes

import os
import random
import threading
import time
import traceback
import aiohttp
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict

import requests
from flask import Flask
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ServerSelectionTimeoutError
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
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
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PlayPalv2")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/PlayPalGroup")
TENOR_API_KEY = os.getenv("TENOR_API_KEY", "").strip()
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "").strip()
AUTO_FETCH_INTERVAL_MIN = int(os.getenv("AUTO_FETCH_INTERVAL_MIN", "60"))  # default 1 hour
BOT_OWNER_AUTO_PREMIUM = os.getenv("BOT_OWNER_AUTO_PREMIUM", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

# ================== Flask keep-alive ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ PlayPal v2 Bot is running with automatic content!"

# ================== MongoDB Setup ==================
use_mongo = bool(MONGODB_URI)
db = None
users_col = None
cache_col = None
bans_col = None

if use_mongo:
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
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

# In-memory fallback stores
_inmem_users = {}
_inmem_cache = {"memes": [], "gifs": [], "jokes": [], "quizzes": []}
_inmem_bans = set()

def _now():
    return datetime.now(timezone.utc)

# ================== Storage Helpers ==================
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

# ================== Automatic Content Fetcher ==================
class ContentFetcher:
    def __init__(self):
        self.session = None
        
    async def ensure_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
            
    async def fetch_meme(self):
        """Fetch memes from various APIs"""
        await self.ensure_session()
        
        sources = [
            self._fetch_reddit_meme,
            self._fetch_meme_api,
        ]
        
        for source in sources:
            try:
                meme = await source()
                if meme:
                    add_cached_item("memes", meme)
                    return meme
            except Exception as e:
                print(f"Meme fetch error: {e}")
                continue
                
        return self._get_fallback_meme()
        
    async def _fetch_reddit_meme(self):
        try:
            subreddits = ['memes', 'dankmemes', 'wholesomememes', 'me_irl']
            subreddit = random.choice(subreddits)
            url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=20"
            
            async with self.session.get(url, headers={'User-agent': 'TelegramBot/1.0'}) as response:
                data = await response.json()
                posts = [post for post in data['data']['children'] 
                        if not post['data']['over_18'] and 'post_hint' in post['data'] and 
                        post['data']['post_hint'] == 'image']
                
                if posts:
                    post = random.choice(posts)
                    return {
                        'url': post['data']['url'],
                        'title': post['data']['title'],
                        'source': f"r/{subreddit}",
                        'nsfw': False
                    }
        except:
            return None
            
    async def _fetch_meme_api(self):
        try:
            async with self.session.get('https://meme-api.com/gimme') as response:
                data = await response.json()
                if data['nsfw']:
                    return None
                return {
                    'url': data['url'],
                    'title': data['title'],
                    'source': f"r/{data['subreddit']}",
                    'nsfw': data['nsfw']
                }
        except:
            return None
    
    def _get_fallback_meme(self):
        fallback_memes = [
            {'url': 'https://i.imgflip.com/1bij.jpg', 'title': 'One Does Not Simply', 'source': 'ImgFlip'},
            {'url': 'https://i.imgflip.com/261o3j.jpg', 'title': 'But that\'s none of my business', 'source': 'ImgFlip'},
        ]
        return random.choice(fallback_memes)
    
    async def fetch_gif(self, query="funny"):
        """Fetch GIFs from various APIs"""
        await self.ensure_session()
        
        sources = [
            lambda: self._fetch_tenor_gif(query),
            lambda: self._fetch_giphy_gif(query),
        ]
        
        for source in sources:
            try:
                gif = await source()
                if gif:
                    add_cached_item("gifs", gif)
                    return gif
            except Exception as e:
                print(f"GIF fetch error: {e}")
                continue
                
        return self._get_fallback_gif()
        
    async def _fetch_tenor_gif(self, query):
        if not TENOR_API_KEY:
            return None
            
        try:
            url = f"https://api.tenor.com/v1/search?q={query}&key={TENOR_API_KEY}&limit=20"
            async with self.session.get(url) as response:
                data = await response.json()
                if data['results']:
                    gif = random.choice(data['results'])
                    return {
                        'url': gif['media'][0]['gif']['url'],
                        'title': query.capitalize(),
                        'source': 'Tenor'
                    }
        except:
            return None
            
    async def _fetch_giphy_gif(self, query):
        if not GIPHY_API_KEY:
            return None
            
        try:
            url = f"https://api.giphy.com/v1/gifs/search?api_key={GIPHY_API_KEY}&q={query}&limit=20"
            async with self.session.get(url) as response:
                data = await response.json()
                if data['data']:
                    gif = random.choice(data['data'])
                    return {
                        'url': gif['images']['original']['url'],
                        'title': query.capitalize(),
                        'source': 'Giphy'
                    }
        except:
            return None
    
    def _get_fallback_gif(self):
        fallback_gifs = [
            {'url': 'https://media.giphy.com/media/3o7aTskHEUdgCQAXde/giphy.gif', 'title': 'Funny GIF', 'source': 'Fallback'},
            {'url': 'https://media.giphy.com/media/l0HlNQ03J5JxX6lva/giphy.gif', 'title': 'Laughing GIF', 'source': 'Fallback'},
        ]
        return random.choice(fallback_gifs)
    
    async def fetch_joke(self):
        """Fetch jokes from various APIs"""
        await self.ensure_session()
        
        sources = [
            self._fetch_sv443_joke,
            self._fetch_icanhazdadjoke,
        ]
        
        for source in sources:
            try:
                joke = await source()
                if joke:
                    add_cached_item("jokes", joke)
                    return joke
            except Exception as e:
                print(f"Joke fetch error: {e}")
                continue
                
        return self._get_fallback_joke()
        
    async def _fetch_sv443_joke(self):
        try:
            categories = ['Any', 'Programming', 'Misc', 'Pun']
            category = random.choice(categories)
            url = f"https://v2.jokeapi.dev/joke/{category}?type=single"
            
            async with self.session.get(url) as response:
                data = await response.json()
                if data.get('joke'):
                    return {
                        'text': data['joke'],
                        'category': data['category'],
                        'source': 'JokeAPI'
                    }
        except:
            return None
            
    async def _fetch_icanhazdadjoke(self):
        try:
            url = "https://icanhazdadjoke.com/"
            async with self.session.get(url, headers={'Accept': 'application/json'}) as response:
                data = await response.json()
                return {
                    'text': data['joke'],
                    'category': 'Dad Joke',
                    'source': 'icanhazdadjoke'
                }
        except:
            return None
    
    def _get_fallback_joke(self):
        fallback_jokes = [
            {"text": "Why don't scientists trust atoms? Because they make up everything!", "category": "Science", "source": "Fallback"},
            {"text": "Why did the scarecrow win an award? Because he was outstanding in his field!", "category": "Puns", "source": "Fallback"},
            {"text": "I told my computer I needed a break. It said, 'No problem, I'll go to sleep.'", "category": "Tech", "source": "Fallback"},
        ]
        return random.choice(fallback_jokes)
    
    async def fetch_quiz(self, difficulty="medium"):
        """Fetch quizzes from various APIs"""
        await self.ensure_session()
        
        sources = [
            lambda: self._fetch_opentdb_quiz(difficulty),
        ]
        
        for source in sources:
            try:
                quiz = await source()
                if quiz:
                    add_cached_item("quizzes", quiz)
                    return quiz
            except Exception as e:
                print(f"Quiz fetch error: {e}")
                continue
                
        return self._get_fallback_quiz(difficulty)
        
    async def _fetch_opentdb_quiz(self, difficulty):
        try:
            difficulties = ["easy", "medium", "hard"]
            diff = difficulty if difficulty in difficulties else random.choice(difficulties)
            url = f"https://opentdb.com/api.php?amount=1&difficulty={diff}&type=multiple"
            
            async with self.session.get(url) as response:
                data = await response.json()
                if data['results']:
                    quiz_data = data['results'][0]
                    # Decode HTML entities
                    import html
                    question = html.unescape(quiz_data['question'])
                    correct_answer = html.unescape(quiz_data['correct_answer'])
                    incorrect_answers = [html.unescape(ans) for ans in quiz_data['incorrect_answers']]
                    
                    options = incorrect_answers + [correct_answer]
                    random.shuffle(options)
                    
                    return {
                        'question': question,
                        'options': options,
                        'correct_answer': correct_answer,
                        'correct_index': options.index(correct_answer),
                        'category': quiz_data['category'],
                        'difficulty': quiz_data['difficulty'],
                        'source': 'OpenTDB'
                    }
        except:
            return None
    
    def _get_fallback_quiz(self, difficulty):
        fallback_quizzes = {
            "easy": [
                {
                    "question": "What is 2 + 2?",
                    "options": ["3", "4", "5", "6"],
                    "correct_answer": "4",
                    "correct_index": 1,
                    "category": "Math",
                    "difficulty": "easy",
                    "source": "Fallback"
                },
                {
                    "question": "Which planet is known as the Red Planet?",
                    "options": ["Venus", "Mars", "Jupiter", "Saturn"],
                    "correct_answer": "Mars",
                    "correct_index": 1,
                    "category": "Science",
                    "difficulty": "easy",
                    "source": "Fallback"
                }
            ],
            "medium": [
                {
                    "question": "What is the capital of Australia?",
                    "options": ["Sydney", "Melbourne", "Canberra", "Perth"],
                    "correct_answer": "Canberra",
                    "correct_index": 2,
                    "category": "Geography",
                    "difficulty": "medium",
                    "source": "Fallback"
                }
            ],
            "hard": [
                {
                    "question": "Who wrote 'One Hundred Years of Solitude'?",
                    "options": ["Gabriel Garcia Marquez", "Mario Vargas Llosa", "Isabel Allende", "Pablo Neruda"],
                    "correct_answer": "Gabriel Garcia Marquez",
                    "correct_index": 0,
                    "category": "Literature",
                    "difficulty": "hard",
                    "source": "Fallback"
                }
            ]
        }
        
        difficulty = difficulty if difficulty in fallback_quizzes else "easy"
        return random.choice(fallback_quizzes[difficulty])
    
    async def auto_refresh_content(self):
        """Background task to automatically refresh content"""
        while True:
            try:
                print(f"[{datetime.now()}] Auto-refreshing content...")
                
                # Refresh memes
                for _ in range(3):
                    await self.fetch_meme()
                
                # Refresh GIFs
                for _ in range(3):
                    await self.fetch_gif(random.choice(["funny", "cat", "dog", "reaction"]))
                
                # Refresh jokes
                for _ in range(5):
                    await self.fetch_joke()
                
                # Refresh quizzes
                for _ in range(3):
                    await self.fetch_quiz(random.choice(["easy", "medium", "hard"]))
                
                print(f"[{datetime.now()}] Content refreshed: "
                      f"{len(get_cached_items('memes'))} memes, "
                      f"{len(get_cached_items('gifs'))} GIFs, "
                      f"{len(get_cached_items('jokes'))} jokes, "
                      f"{len(get_cached_items('quizzes'))} quizzes")
                
                # Wait before next refresh
                await asyncio.sleep(AUTO_FETCH_INTERVAL_MIN * 60)
                
            except Exception as e:
                print(f"Error in auto_refresh_content: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error

# ================== Game System ==================
class GameSystem:
    def __init__(self):
        self.active_games = {}
        self.leaderboard = {}
        
    async def start_quiz_game(self, chat_id, user_id, difficulty="medium"):
        """Start a quiz game"""
        game_id = f"{chat_id}_{user_id}"
        self.active_games[game_id] = {
            "type": "quiz",
            "score": 0,
            "question_count": 0,
            "max_questions": 5,
            "difficulty": difficulty,
            "start_time": datetime.now(),
            "questions": []
        }
        
        # Get first question
        question = await content_fetcher.fetch_quiz(difficulty)
        self.active_games[game_id]["questions"].append(question)
        
        return question
    
    async def process_quiz_answer(self, game_id, answer_index):
        """Process a quiz answer and return next question or results"""
        if game_id not in self.active_games:
            return None
            
        game = self.active_games[game_id]
        current_question = game["questions"][-1]
        
        # Check if answer is correct
        is_correct = (answer_index == current_question["correct_index"])
        if is_correct:
            game["score"] += 1
            
        game["question_count"] += 1
        
        # Check if game is over
        if game["question_count"] >= game["max_questions"]:
            results = self._end_game(game_id)
            return {"game_over": True, "results": results}
        
        # Get next question
        next_question = await content_fetcher.fetch_quiz(game["difficulty"])
        game["questions"].append(next_question)
        
        return {
            "game_over": False, 
            "next_question": next_question,
            "was_correct": is_correct,
            "score": game["score"]
        }
    
    def _end_game(self, game_id):
        """End game and return results"""
        if game_id not in self.active_games:
            return None
            
        game = self.active_games[game_id]
        user_id = int(game_id.split("_")[1])
        
        # Calculate score and time
        end_time = datetime.now()
        duration = (end_time - game["start_time"]).total_seconds()
        
        results = {
            "score": game["score"],
            "total_questions": game["question_count"],
            "duration": duration,
            "difficulty": game["difficulty"]
        }
        
        # Update leaderboard
        if user_id not in self.leaderboard:
            self.leaderboard[user_id] = []
        
        self.leaderboard[user_id].append(results)
        
        # Keep only top 10 scores per user
        self.leaderboard[user_id].sort(key=lambda x: x["score"], reverse=True)
        self.leaderboard[user_id] = self.leaderboard[user_id][:10]
        
        # Remove game from active games
        del self.active_games[game_id]
        
        return results
    
    def get_leaderboard(self, user_id=None):
        """Get leaderboard for a user or global leaderboard"""
        if user_id:
            return self.leaderboard.get(user_id, [])
        
        # Global leaderboard (top 10 scores across all users)
        all_scores = []
        for uid, scores in self.leaderboard.items():
            for score in scores:
                all_scores.append({
                    "user_id": uid,
                    "score": score["score"],
                    "difficulty": score["difficulty"]
                })
        
        all_scores.sort(key=lambda x: x["score"], reverse=True)
        return all_scores[:10]

# Initialize content fetcher and game system
content_fetcher = ContentFetcher()
game_system = GameSystem()

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
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(content_fetcher.auto_refresh_content())

# Start the auto-fetch thread
fetch_thread = threading.Thread(target=auto_fetch_loop, daemon=True)
fetch_thread.start()

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
        "I'm 🤖 *PlayPal* — your professional fun & utility bot.\n\n"
        "✨ I provide:\n"
        "• 🎲 Games & Quizzes\n"
        "• 😄 Jokes in multiple languages\n"
        "• 📊 Personal stats & Leaderboard\n"
        "• 💎 Premium goodies (memes, GIFs, advanced quizzes)\n\n"
        "👇 Use the menu below to start — it's fast and friendly."
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🎮 *PlayPal Bot Commands* 🎮\n\n"
        "*/start* - Start the bot\n"
        "*/help* - Show this help message\n"
        "*/joke* - Get a random joke\n"
        "*/meme* - Get a random meme\n"
        "*/gif* [query] - Search for a GIF\n"
        "*/quiz* [easy|medium|hard] - Start a quiz game\n"
        "*/rps* rock|paper|scissors - Play Rock Paper Scissors\n"
        "*/guess* start|number - Play guess the number\n"
        "*/scramble* start|word - Play word scramble\n"
        "*/leaderboard* - Show quiz leaderboard\n"
        "*/premium* - Learn about premium features\n"
        "*/settings* - Configure your preferences\n\n"
        "Join our community:\n"
        f"Channel: {CHANNEL_LINK}\n"
        f"Group: {GROUP_LINK}"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

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

# Language selection
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

# Message logger
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

# Jokes command
async def cmd_joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random joke"""
    joke = await content_fetcher.fetch_joke()
    await update.message.reply_text(f"😂 {joke['text']}\n\nCategory: {joke['category']}")

# Meme command
async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random meme"""
    u = ensure_user_record(update.effective_user)
    if not u.get("is_premium"):
        await update.message.reply_text("🔒 Premium only.", reply_markup=premium_kb())
        return
        
    meme = await content_fetcher.fetch_meme()
    if meme:
        await update.message.reply_photo(
            photo=meme['url'],
            caption=f"📸 {meme['title']}\nSource: {meme['source']}"
        )
    else:
        await update.message.reply_text("Couldn't fetch a meme right now. Try again later!")

# GIF command
async def cmd_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random GIF"""
    u = ensure_user_record(update.effective_user)
    if not u.get("is_premium"):
        await update.message.reply_text("🔒 Premium only.", reply_markup=premium_kb())
        return
        
    query = " ".join(context.args) if context.args else "funny"
    gif = await content_fetcher.fetch_gif(query)
    if gif:
        await update.message.reply_animation(
            animation=gif['url'],
            caption=f"🎬 {gif['title']}\nSource: {gif['source']}"
        )
    else:
        await update.message.reply_text("Couldn't fetch a GIF right now. Try again later!")

# Quiz command
async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a quiz game"""
    user = update.effective_user
    difficulty = context.args[0] if context.args else "medium"
    
    if difficulty not in ["easy", "medium", "hard"]:
        await update.message.reply_text("Please choose difficulty: easy, medium, or hard")
        return
    
    question = await game_system.start_quiz_game(update.effective_chat.id, user.id, difficulty)
    
    # Create options keyboard
    keyboard = []
    for i, option in enumerate(question['options']):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_answer:{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎯 Quiz Question ({question['difficulty']}):\n\n{question['question']}",
        reply_markup=reply_markup
    )

# Quiz answer handler
async def quiz_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz answers"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    game_id = f"{query.message.chat.id}_{user.id}"
    answer_index = int(query.data.split(":")[1])
    
    result = await game_system.process_quiz_answer(game_id, answer_index)
    
    if result["game_over"]:
        # Game over, show results
        score = result["results"]["score"]
        total = result["results"]["total_questions"]
        await query.edit_message_text(
            f"🏁 Quiz Finished!\n\nYour score: {score}/{total}\n"
            f"Difficulty: {result['results']['difficulty']}\n"
            f"Time: {result['results']['duration']:.1f} seconds\n\n"
            "Play again with /quiz"
        )
        
        # Award XP based on performance
        xp_earned = score * 10
        update_user_counter(user.id, "xp", xp_earned)
        
    else:
        # Next question
        question = result["next_question"]
        keyboard = []
        for i, option in enumerate(question['options']):
            keyboard.append([InlineKeyboardButton(option, callback_data=f"quiz_answer:{i}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        feedback = "✅ Correct!" if result["was_correct"] else "❌ Incorrect!"
        await query.edit_message_text(
            f"{feedback} Score: {result['score']}\n\n"
            f"🎯 Next Question ({question['difficulty']}):\n\n{question['question']}",
            reply_markup=reply_markup
        )

# Leaderboard command
async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show quiz leaderboard"""
    user_id = update.effective_user.id
    personal_scores = game_system.get_leaderboard(user_id)
    global_scores = game_system.get_leaderboard()
    
    message = "🏆 **Quiz Leaderboard**\n\n"
    message += "**Your Top Scores:**\n"
    
    if personal_scores:
        for i, score in enumerate(personal_scores[:5], 1):
            message += f"{i}. {score['score']}/5 ({score['difficulty']})\n"
    else:
        message += "No scores yet. Play a quiz with /quiz!\n"
    
    message += "\n**Global Top Scores:**\n"
    if global_scores:
        for i, score in enumerate(global_scores[:5], 1):
            message += f"{i}. User #{score['user_id']}: {score['score']}/5 ({score['difficulty']})\n"
    else:
        message += "No global scores yet.\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

# RPS game
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

# Guess number game
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

# Scramble game
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

# Premium info
async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    premium_text = (
        "🌟 *Premium Features* 🌟\n\n"
        "• Ad-free experience\n"
        "• Exclusive memes and GIFs\n"
        "• Advanced quizzes\n"
        "• Priority support\n"
        "• Custom themes\n"
        "• Early access to new features\n\n"
        "Contact @Admin for premium access!"
    )
    await update.message.reply_text(premium_text, parse_mode=ParseMode.MARKDOWN)

# Stats command
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = ensure_user_record(update.effective_user)
    doc = get_user(u["user_id"])
    await update.message.reply_text(
        f"👤 Profile\n• Name: {doc.get('first_name')}\n• Messages: {doc.get('messages',0)}\n• XP: {doc.get('xp',0)}\n• Premium: {'✅' if doc.get('is_premium') else '❌'}"
    )

# Admin commands
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Unauthorized.")
        return
    total = users_col.estimated_document_count() if use_mongo else len(_inmem_users)
    prem = users_col.count_documents({"is_premium": True}) if use_mongo else sum(1 for u in _inmem_users.values() if u.get("is_premium"))
    await update.message.reply_text(f"🛠 Admin Panel\n• Total users: {total}\n• Premium users: {prem}")

# Error handler
async def err_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("Error:", context.error)

# ================== Bot Setup ==================
def main():
    # Create the Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    # Core commands
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Content commands
    application.add_handler(CommandHandler("joke", cmd_joke))
    application.add_handler(CommandHandler("meme", cmd_meme))
    application.add_handler(CommandHandler("gif", cmd_gif))
    application.add_handler(CommandHandler("premium", cmd_premium))
    
    # Game commands
    application.add_handler(CommandHandler("quiz", cmd_quiz))
    application.add_handler(CommandHandler("rps", cmd_rps))
    application.add_handler(CommandHandler("guess", cmd_guess))
    application.add_handler(CommandHandler("scramble", cmd_scramble))
    application.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    application.add_handler(CallbackQueryHandler(quiz_answer_handler, pattern="^quiz_answer:"))
    
    # Other commands
    application.add_handler(CommandHandler("lang", cmd_lang))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_logger))
    
    # Error handler
    application.add_error_handler(err_handler)

    print("Bot polling started.")
    application.run_polling()

if __name__ == "__main__":
    # Start Flask server for Railway
    port = int(os.getenv("PORT", 5000))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False), daemon=True).start()
    
    # Start the bot
    main()