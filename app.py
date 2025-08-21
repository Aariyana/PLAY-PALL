# app.py
# PlayPal v2 - Secure Version with Admin System

import os
import random
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, List

import requests
from flask import Flask
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
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PlayPalu")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/+1mgUwZpfuJY0YjA1")
BOT_OWNER_AUTO_PREMIUM = os.getenv("BOT_OWNER_AUTO_PREMIUM", "").strip()
NEWS_API = os.getenv("NEWS_API", "").strip()
GIFY_API = os.getenv("GIFY_API", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

print(f"Admin IDs configured: {ADMIN_IDS}")

# ================== Flask keep-alive ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ PlayPal v2 Bot is running with secure admin system!"

# ================== Admin System ==================
def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    print(f"Checking admin status for user {user_id}. Admin IDs: {ADMIN_IDS}")
    return user_id in ADMIN_IDS

# ================== In-memory storage ==================
_users = {}
_active_quizzes = {}
_leaderboard = {}

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
            "language": "en",
            "joined_at": datetime.now(timezone.utc),
            "last_seen": datetime.now(timezone.utc),
        }
        print(f"New user registered: {user.id} (Admin: {is_admin(user.id)})")
    return _users[user.id]

# ================== UI Helpers ==================
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 Help", callback_data="help_menu")],
        [InlineKeyboardButton("🎮 Games", callback_data="games_menu")],
        [InlineKeyboardButton("😂 Get Joke", callback_data="get_joke")],
        [InlineKeyboardButton("📞 Contact Admin", callback_data="contact_admin")]
    ])

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
    ])

# ================== Premium Management Commands ==================
async def cmd_setpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set premium status for a user"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
        
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setpremium <user_id> <on/off>")
        return
        
    try:
        target_user_id = int(context.args[0])
        status = context.args[1].lower()
        
        if status not in ["on", "off"]:
            await update.message.reply_text("Usage: /setpremium <user_id> <on/off>")
            return
            
        is_premium = (status == "on")
        
        # Update premium status
        if target_user_id in _users:
            _users[target_user_id]["is_premium"] = is_premium
        else:
            # Create a basic user record if it doesn't exist
            _users[target_user_id] = {
                "user_id": target_user_id,
                "is_premium": is_premium,
                "is_admin": False,
                "messages": 0,
                "xp": 0,
            }
        
        # Try to notify the user
        try:
            status_text = "activated" if is_premium else "deactivated"
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 Your premium status has been {status_text} by an admin!"
            )
        except Exception as e:
            print(f"Could not notify user {target_user_id}: {e}")
            
        await update.message.reply_text(f"✅ Premium for user {target_user_id} set to {status}")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please provide a numeric user ID.")

async def cmd_premiumusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all premium users"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
    
    premium_users = [u for u in _users.values() if u.get("is_premium")]
    
    if not premium_users:
        await update.message.reply_text("❌ No premium users found.")
        return
    
    premium_list = "🌟 *Premium Users:*\n\n"
    for i, user_data in enumerate(premium_users, 1):
        username = f"@{user_data.get('username', 'N/A')}" if user_data.get('username') else "No username"
        premium_list += f"{i}. {user_data.get('first_name', 'User')} ({username}) - ID: `{user_data['user_id']}`\n"
    
    await update.message.reply_text(premium_list, parse_mode=ParseMode.MARKDOWN)

async def cmd_givepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give premium to a user by username"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /givepremium <username>")
        return
        
    target_username = context.args[0].replace("@", "")  # Remove @ if present
    
    # Find user by username
    target_user = None
    for user_id, user_data in _users.items():
        if user_data.get("username") == target_username:
            target_user = user_data
            break
    
    if not target_user:
        await update.message.reply_text(f"❌ User @{target_username} not found in database.")
        return
    
    # Give premium
    target_user["is_premium"] = True
    
    # Try to notify the user
    try:
        await context.bot.send_message(
            chat_id=target_user["user_id"],
            text="🎉 You've been granted premium status by an admin! Enjoy the exclusive features!"
        )
    except Exception as e:
        print(f"Could not notify user {target_user['user_id']}: {e}")
    
    await update.message.reply_text(
        f"✅ Premium status granted to @{target_username} (ID: {target_user['user_id']})"
    )


# ================== Command Handlers ==================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    name = user.first_name or "friend"
    admin_status = " (Admin)" if user_record["is_admin"] else ""
    
    text = (
        f"👋 *Welcome, {name}!*{admin_status}\n\n"
        "I'm 🤖 *PlayPal* — your fun Telegram bot!\n\n"
        "✨ I can:\n"
        "• Tell you jokes 😄\n"
        "• Play games 🎮\n"
        "• Share news 📰\n"
        "• Chat with you 💬\n\n"
    )
    
    if user_record["is_admin"]:
        text += "⚙️ *Admin commands available:* /admin\n\n"
    
    text += "Use the menu below to get started!"
    
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode=ParseMode.MARKDOWN)

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel command"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
    
    admin_text = (
        "🛠️ *Admin Panel*\n\n"
        f"• Total users: `{len(_users)}`\n"
        f"• Admin users: `{len([u for u in _users.values() if u.get('is_admin')])}`\n"
        f"• Premium users: `{len([u for u in _users.values() if u.get('is_premium')])}`\n\n"
        "*Admin Commands:*\n"
        "/stats - View user statistics\n"
        "/broadcast - Broadcast message to all users\n"
        "/userinfo <id> - Get user information"
    )
    
    await update.message.reply_text(admin_text, reply_markup=admin_kb(), parse_mode=ParseMode.MARKDOWN)

async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get detailed user information"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
        
    try:
        target_user_id = int(context.args[0])
        
        if target_user_id not in _users:
            await update.message.reply_text("❌ User not found.")
            return
            
        target_user = _users[target_user_id]
        
        user_info = (
            f"👤 *User Information:*\n\n"
            f"• User ID: `{target_user_id}`\n"
            f"• Name: {target_user.get('first_name', 'N/A')}\n"
            f"• Username: @{target_user.get('username', 'N/A')}\n"
            f"• Admin: {'✅ Yes' if target_user.get('is_admin') else '❌ No'}\n"
            f"• Premium: {'✅ Yes' if target_user.get('is_premium') else '❌ No'}\n"
            f"• Messages: {target_user.get('messages', 0)}\n"
            f"• XP: {target_user.get('xp', 0)}\n"
            f"• Language: {target_user.get('language', 'en')}\n"
            f"• Joined: {target_user.get('joined_at', 'N/A')}\n\n"
            f"*Quick Actions:*\n"
            f"/setpremium {target_user_id} {'off' if target_user.get('is_premium') else 'on'}\n"
        )
        
        await update.message.reply_text(user_info, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please provide a numeric user ID.")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
        
    message = " ".join(context.args)
    broadcast_text = f"📢 *Broadcast from Admin:*\n\n{message}"
    
    sent_count = 0
    failed_count = 0
    
    for user_id, user_data in _users.items():
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=broadcast_text,
                parse_mode=ParseMode.MARKDOWN
            )
            sent_count += 1
            # Avoid rate limiting
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Failed to send to {user_id}: {e}")
            failed_count += 1
    
    await update.message.reply_text(
        f"📊 Broadcast completed:\n"
        f"• Sent: {sent_count}\n"
        f"• Failed: {failed_count}"
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user statistics"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not user_record["is_admin"]:
        await update.message.reply_text("❌ Unauthorized. Admin access required.")
        return
        
    if context.args:
        # Get specific user stats
        try:
            user_id = int(context.args[0])
            if user_id in _users:
                user_data = _users[user_id]
                stats_text = (
                    f"📊 *User Statistics for {user_id}*\n\n"
                    f"• Username: @{user_data.get('username', 'N/A')}\n"
                    f"• Name: {user_data.get('first_name', 'N/A')}\n"
                    f"• Admin: {'✅ Yes' if user_data.get('is_admin') else '❌ No'}\n"
                    f"• Premium: {'✅ Yes' if user_data.get('is_premium') else '❌ No'}\n"
                    f"• Messages: {user_data.get('messages', 0)}\n"
                    f"• XP: {user_data.get('xp', 0)}\n"
                    f"• Joined: {user_data.get('joined_at', 'N/A')}"
                )
                await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text("❌ User not found.")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
    else:
        # Get overall stats
        total_messages = sum(user.get('messages', 0) for user in _users.values())
        total_xp = sum(user.get('xp', 0) for user in _users.values())
        
        stats_text = (
            "📊 *Bot Statistics*\n\n"
            f"• Total users: `{len(_users)}`\n"
            f"• Admin users: `{len([u for u in _users.values() if u.get('is_admin')])}`\n"
            f"• Premium users: `{len([u for u in _users.values() if u.get('is_premium')])}`\n"
            f"• Total messages: `{total_messages}`\n"
            f"• Total XP: `{total_xp}`\n\n"
            "Use `/stats <user_id>` for specific user info"
        )
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

def check_premium(user_id: int) -> bool:
    """Check if user has premium access"""
    if user_id in _users:
        return _users[user_id].get("is_premium", False)
    return False

# Example usage in your meme command:
async def cmd_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a random meme (Premium feature)"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if not check_premium(user.id):
        await update.message.reply_text(
            "🔒 This is a premium feature!\n\n"
            "Upgrade to premium to access exclusive memes, GIFs, and more!\n"
            "Contact @admin for premium access.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📞 Contact Admin", callback_data="contact_admin")]
            ])
        )
        return
        
    # Premium user logic here
    await update.message.reply_text("Here's your premium meme! 🎉")

async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Contact admin command"""
    if not context.args:
        await update.message.reply_text(
            "Please provide a message for the admin.\n\n"
            "Usage: /contact <your message>"
        )
        return
        
    user = update.effective_user
    message = " ".join(context.args)
    
    contact_text = (
        f"📩 *New Contact Message*\n\n"
        f"• From: {user.first_name} (@{user.username})\n"
        f"• User ID: `{user.id}`\n"
        f"• Message: {message}"
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
        except Exception as e:
            print(f"Failed to send to admin {admin_id}: {e}")
    
    if sent_count > 0:
        await update.message.reply_text(
            "✅ Your message has been sent to the admin team. "
            "They will get back to you soon!"
        )
    else:
        await update.message.reply_text(
            "❌ Sorry, we couldn't reach any admins at the moment. "
            "Please try again later."
        )

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user ID"""
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    admin_status = "✅ Admin" if user_record["is_admin"] else "❌ Not Admin"
    
    await update.message.reply_text(
        f"👤 *Your User Info:*\n\n"
        f"• User ID: `{user.id}`\n"
        f"• Name: {user.first_name}\n"
        f"• Username: @{user.username or 'N/A'}\n"
        f"• Status: {admin_status}\n\n"
        "Give your ID to the bot owner if you need admin access.",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jokes = [
        "Why don't scientists trust atoms? Because they make up everything!",
        "Why did the scarecrow win an award? Because he was outstanding in his field!",
        "I told my computer I needed a break. It said, 'No problem, I'll go to sleep.'",
        "Why don't eggs tell jokes? They'd crack each other up!",
        "What do you call a fake noodle? An impasta!",
    ]
    joke = random.choice(jokes)
    await update.message.reply_text(f"😂 {joke}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_record = ensure_user_record(user)
    
    if query.data == "help_menu":
        await cmd_help(update, context)
    elif query.data == "games_menu":
        await query.edit_message_text(
            "🎮 Available Games:\n\n"
            "• /joke - Get a random joke\n"
            "• More games coming soon! 🚀"
        )
    elif query.data == "get_joke":
        await cmd_joke(update, context)
    elif query.data == "contact_admin":
        await query.edit_message_text(
            "To contact admin:\n\n"
            "1. Use /contact <your message>\n"
            "2. Or join our group: https://t.me/PlayPalGroup\n\n"
            "We'll help you with any questions!"
        )
    elif query.data == "admin_stats" and user_record["is_admin"]:
        await cmd_stats(update, context)
    elif query.data == "admin_broadcast" and user_record["is_admin"]:
        await query.edit_message_text("Use /broadcast <message> to send a message to all users")
    elif query.data == "back_main":
        await query.edit_message_text("Back to main menu", reply_markup=main_menu_kb())
    else:
        await query.edit_message_text("I'm not sure what you want to do. Try /help for options.")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *PlayPal Bot Commands* 🤖\n\n"
        "*/start* - Start the bot\n"
        "*/help* - Show this help\n"
        "*/joke* - Get a random joke\n"
        "*/id* - Get your user ID\n"
        "*/contact* - Contact admin\n\n"
    )
    
    user = update.effective_user
    user_record = ensure_user_record(user)
    
    if user_record["is_admin"]:
        help_text += (
            "⚙️ *Admin Commands:*\n"
            "*/admin* - Admin panel\n"
            "*/stats* - User statistics\n"
            "*/broadcast* - Broadcast message\n\n"
        )
    
    help_text += "Try me out! I'm here to have fun with you! 🎉"
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        user = update.effective_user
        user_record = ensure_user_record(user)
        user_record["messages"] += 1
        user_record["xp"] += random.randint(1, 3)
        
        user_message = update.message.text.lower()
        
        if any(word in user_message for word in ["hello", "hi", "hey"]):
            await update.message.reply_text(f"👋 Hello {user.first_name}! How can I help you today?")
        elif any(word in user_message for word in ["how are you", "how you doing"]):
            await update.message.reply_text("I'm doing great! Ready to have some fun! 🎉")
        elif any(word in user_message for word in ["thank", "thanks"]):
            await update.message.reply_text("You're welcome! 😊")
        else:
            await update.message.reply_text("I heard you! Try /help to see what I can do!")
            
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
    if update and hasattr(update, 'effective_chat'):
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Sorry, I encountered an error. Please try again later."
            )
        except:
            pass

# ================== Bot Setup ==================
def main():
    # Create the Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("contact", cmd_contact))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("joke", cmd_joke))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(CommandHandler("setpremium", cmd_setpremium))
    application.add_handler(CommandHandler("premiumusers", cmd_premiumusers))
    application.add_handler(CommandHandler("givepremium", cmd_givepremium))
    application.add_error_handler(error_handler)

    print("🤖 Starting PlayPal bot...")
    print(f"✅ Admin IDs: {ADMIN_IDS}")
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