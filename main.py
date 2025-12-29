import logging
import asyncpg
import os
import asyncio
import html
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, ReplyKeyboardRemove, ForceReply
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiohttp import web
from dotenv import load_dotenv

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# ==========================================
# MODULE 1: CONFIGURATION & PERMISSIONS
# ==========================================

load_dotenv()

# Community Settings
CATEGORIES = ["Relationship", "Family", "School", "Friendship", "Religion", "Mental", "Addiction", "Harassment", "Crush", "Health", "Other"]
BANNED_WORDS = ["scam", "nude", "hack", "t.me/", "telegram.me"]
MAX_CATEGORIES = 3 

# Point System Settings
POINTS_PER_CONFESSION = 5
POINTS_PER_LIKE_RECEIVED = 2
POINTS_PER_DISLIKE_RECEIVED = -2

# API & Database Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_ID_STR = os.getenv("ADMIN_ID", "")

# Multi-Admin Parsing
ADMIN_IDS = [int(i.strip()) for i in ADMIN_ID_STR.split(",") if i.strip()]
PRIMARY_ADMIN = ADMIN_IDS[0] if ADMIN_IDS else None

# Initialization
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = None
bot_info = None

# Helper: Admin Check
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Helper: Aura Title Logic
def get_reputation_title(points: int) -> str:
    if points >= 500: return "Legend 🏆"
    if points >= 200: return "Wise Elder 🧙‍♂️"
    if points >= 50: return "Truth Teller 🗣️"
    if points >= 0: return "Newbie 🌱"
    return "Troublemaker 💀"

# Helper: Safe Message Delivery
async def safe_send_message(user_id: int, text: str, reply_markup=None):
    try:
        return await bot.send_message(user_id, text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Failed to send message to {user_id}: {e}")
        return None
# ==========================================
# MODULE 2: DATABASE & SECURITY MIDDLEWARE
# ==========================================

async def setup_db():
    global db, bot_info
    db = await asyncpg.create_pool(DATABASE_URL)
    bot_info = await bot.get_me()
    async with db.acquire() as conn:
        # Create tables if they don't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (
                id SERIAL PRIMARY KEY, 
                text TEXT, 
                user_id BIGINT, 
                status TEXT DEFAULT 'pending', 
                message_id BIGINT, 
                categories TEXT[], 
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
                rejection_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY, 
                confession_id INTEGER REFERENCES confessions(id) ON DELETE CASCADE, 
                user_id BIGINT, 
                text TEXT, 
                parent_comment_id INTEGER, 
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_status (
                user_id BIGINT PRIMARY KEY, 
                is_blocked BOOLEAN DEFAULT FALSE, 
                blocked_until TIMESTAMP WITH TIME ZONE, 
                block_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS user_points (
                user_id BIGINT PRIMARY KEY, 
                points INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reactions (
                id SERIAL PRIMARY KEY, 
                comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE, 
                user_id BIGINT, 
                reaction_type VARCHAR(10), 
                UNIQUE(comment_id, user_id)
            );
        """)

class BlockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            async with db.acquire() as conn:
                status = await conn.fetchrow("SELECT is_blocked, blocked_until FROM user_status WHERE user_id = $1", user.id)
                if status and status['is_blocked']:
                    # Check if temporary block has expired
                    if status['blocked_until'] and datetime.now(status['blocked_until'].tzinfo) > status['blocked_until']:
                        await conn.execute("UPDATE user_status SET is_blocked = False WHERE user_id = $1", user.id)
                    else:
                        return # Ignore messages from blocked users
        return await handler(event, data)

# Register the middleware
dp.message.outer_middleware(BlockMiddleware())
# ==========================================
# MODULE 3: FSM STATES & START LOGIC
# ==========================================

class ConfessionForm(StatesGroup):
    selecting_categories = State()
    waiting_for_text = State()

class CommentForm(StatesGroup):
    waiting_for_comment = State()
    waiting_for_reply = State()

class AdminActions(StatesGroup):
    waiting_for_rejection_reason = State()

class BroadcastState(StatesGroup):
    waiting_for_broadcast_message = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    user_id = message.from_user.id
    
    # Check for Deep Linking (e.g., /start view_123)
    if command.args and command.args.startswith("view_"):
        try:
            conf_id = int(command.args.split("_")[1])
            return await show_comments_for_confession(message, conf_id)
        except (ValueError, IndexError):
            pass

    # Initialize user in Database
    async with db.acquire() as conn:
        await conn.execute("INSERT INTO user_points (user_id, points) VALUES ($1, 0) ON CONFLICT DO NOTHING", user_id)
        await conn.execute("INSERT INTO user_status (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)

    welcome_text = (
        f"👋 <b>Welcome to MWU CONFESSION!</b>\n\n"
        f"This is your anonymous space to share thoughts, secrets, and stories within the MWU community.\n\n"
        f"📜 <b>Quick Guide:</b>\n"
        f"• Your identity is 100% hidden.\n"
        f"• Earn <b>Aura Points</b> by being active.\n"
        f"• Follow the rules to avoid being blocked.\n\n"
        f"🚀 <b>Commands:</b>\n"
        f"🔹 /confess - Post a new secret\n"
        f"🔹 /hot - See trending posts\n"
        f"🔹 /profile - Check your stats"
    )
    
    await message.answer(welcome_text, reply_markup=ReplyKeyboardRemove())

@dp.message(Command("rules"))
async def cmd_rules(message: types.Message):
    rules_text = (
        "📜 <b>MWU CONFESSION Rules:</b>\n\n"
        "1. No hate speech or harassment.\n"
        "2. No leaking personal phone numbers or IDs.\n"
        "3. No spam or commercial advertisements.\n"
        "4. Be respectful in the comments.\n\n"
        "<i>Violations will result in Aura loss or a permanent ban.</i>"
    )
    await message.answer(rules_text)
# ==========================================
# MODULE 4: CONFESSION SUBMISSION (STABLE)
# ==========================================

@dp.message(Command("confess"))
async def start_confess(message: types.Message, state: FSMContext):
    """Starts the multi-step confession process."""
    builder = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        builder.button(text=cat, callback_data=f"sel_cat_{cat}")
    builder.button(text="✅ Done Selecting", callback_data="cats_complete")
    builder.adjust(2)
    
    await state.set_state(ConfessionForm.selecting_categories)
    await state.update_data(chosen_cats=[])
    
    await message.answer(
        "<b>Step 1: Choose Categories</b>\nSelect up to 3 categories that fit your confession:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("sel_cat_"), ConfessionForm.selecting_categories)
async def process_category_toggle(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chosen = data.get("chosen_cats", [])
    cat = cb.data.split("_")[2]

    if cat in chosen:
        chosen.remove(cat)
        await cb.answer(f"Removed {cat}")
    else:
        if len(chosen) >= MAX_CATEGORIES:
            return await cb.answer(f"You can only pick {MAX_CATEGORIES} categories!", show_alert=True)
        chosen.append(cat)
        await cb.answer(f"Added {cat}")

    await state.update_data(chosen_cats=chosen)
    cats_str = ", ".join(chosen) if chosen else "None"
    
    try:
        await cb.message.edit_text(
            f"<b>Step 1: Choose Categories</b>\nSelected: <i>{cats_str}</i>\n\nSelect up to 3 categories:",
            reply_markup=cb.message.reply_markup
        )
    except:
        pass # Ignore if text hasn't changed

@dp.callback_query(F.data == "cats_complete", ConfessionForm.selecting_categories)
async def categories_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("chosen_cats"):
        return await cb.answer("Please select at least one category!", show_alert=True)
    
    await state.set_state(ConfessionForm.waiting_for_text)
    await cb.message.edit_text(
        "<b>Step 2: Write your confession</b>\n"
        "Please type your confession below. (Min 10 characters)"
    )

@dp.message(ConfessionForm.waiting_for_text)
async def handle_confession_text(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 10:
        return await message.answer("❌ Your confession is too short.")

    data = await state.get_data()
    chosen_cats = data.get("chosen_cats", ["General"])
    
    async with db.acquire() as conn:
        conf_id = await conn.fetchval(
            "INSERT INTO confessions (text, user_id, categories, status) VALUES ($1, $2, $3, 'pending') RETURNING id",
            message.text, message.from_user.id, chosen_cats
        )

    await state.clear()
    await message.answer(f"✅ <b>Success!</b>\nYour confession #{conf_id} is now with admins.")

    # Prepare Admin UI
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"adm_app_{conf_id}")
    builder.button(text="❌ Reject", callback_data=f"adm_rej_{conf_id}")
    
    report_text = (
        f"🆕 <b>New Submission #{conf_id}</b>\n"
        f"📂 Categories: {', '.join(chosen_cats)}\n\n"
        f"{html.quote(message.text)}"
    )

    # LOOP: Send to every admin in the list
    print(f"DEBUG: Starting notification loop for {len(ADMIN_IDS)} admins.")
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, report_text, reply_markup=builder.as_markup())
            print(f"DEBUG: Successfully sent to admin {admin}")
        except Exception as e:
            print(f"DEBUG: Failed to send to admin {admin}. Error: {e}")
# ==========================================
# MODULE 5: ADMIN MODERATION & POSTING
# ==========================================

@dp.callback_query(F.data.startswith("adm_app_"))
async def approve_confession(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Unauthorized", show_alert=True)

    conf_id = int(cb.data.split("_")[2])
    
    async with db.acquire() as conn:
        data = await conn.fetchrow(
            "UPDATE confessions SET status = 'approved' WHERE id = $1 RETURNING text, user_id, categories",
            conf_id
        )
    
    if data:
        # 1. Format the Post
        post_text = (
            f"<b>📝 MWU CONFESSION #{conf_id}</b>\n"
            f"📂 Categories: <i>{', '.join(data['categories'])}</i>\n\n"
            f"{html.quote(data['text'])}"
        )
        
        # 2. Create Comment Button
        channel_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="💬 Read & Reply to Comments", 
                url=f"https://t.me/{bot_info.username}?start=view_{conf_id}"
            )
        ]])
        
        # 3. Post to Channel
        try:
            sent_msg = await bot.send_message(CHANNEL_ID, post_text, reply_markup=channel_kb)
            
            # 4. Reward User & Save Message ID
            async with db.acquire() as conn:
                await conn.execute("UPDATE confessions SET message_id = $1 WHERE id = $2", sent_msg.message_id, conf_id)
                await conn.execute("UPDATE user_points SET points = points + $1 WHERE user_id = $2", POINTS_PER_CONFESSION, data['user_id'])
            
            await cb.message.edit_text(f"✅ <b>Approved #{conf_id}</b>\nPosted to channel and user rewarded.")
            await safe_send_message(data['user_id'], f"🎉 <b>Great news!</b> Your confession #{conf_id} was approved and posted!")
            
        except Exception as e:
            await cb.message.answer(f"❌ Error posting to channel: {e}")
    else:
        await cb.answer("Confession not found.")

@dp.callback_query(F.data.startswith("adm_rej_"))
async def reject_init(cb: types.CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    
    conf_id = int(cb.data.split("_")[2])
    await state.set_state(AdminActions.waiting_for_rejection_reason)
    await state.update_data(reject_id=conf_id)
    
    await cb.message.answer(f"Please type the reason for rejecting #{conf_id}:", reply_markup=ForceReply())
    await cb.answer()

@dp.message(AdminActions.waiting_for_rejection_reason)
async def process_rejection(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    
    data = await state.get_data()
    conf_id = data['reject_id']
    reason = message.text
    
    async with db.acquire() as conn:
        user_id = await conn.fetchval(
            "UPDATE confessions SET status = 'rejected', rejection_reason = $1 WHERE id = $2 RETURNING user_id", 
            reason, conf_id
        )
    
    await state.clear()
    await message.answer(f"❌ Confession #{conf_id} has been rejected.")
    await safe_send_message(user_id, f"😔 <b>Submission Update:</b>\nYour confession #{conf_id} was not approved.\n\n<b>Reason:</b> {reason}")
 # ==========================================
# MODULE 6: COMMENTS & REACTIONS
# ==========================================

async def show_comments_for_confession(message: types.Message, confession_id: int):
    """Fetches and displays all comments for a specific post."""
    async with db.acquire() as conn:
        confession = await conn.fetchrow("SELECT text FROM confessions WHERE id = $1", confession_id)
        if not confession:
            return await message.answer("❌ Confession not found.")
        
        comments = await conn.fetch(
            "SELECT * FROM comments WHERE confession_id = $1 ORDER BY created_at ASC", 
            confession_id
        )

    text = f"<b>📝 Discussion on #{confession_id}</b>\n\n<i>{html.quote(confession['text'][:100])}...</i>\n"
    text += "━━━━━━━━━━━━━━\n"
    
    if not comments:
        text += "💬 No comments yet. Be the first to reply!"
    else:
        for c in comments:
            text += f"\n• {html.quote(c['text'])}\n"

    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Add Comment", callback_data=f"com_add_{confession_id}")
    kb.button(text="🔄 Refresh", callback_data=f"com_refresh_{confession_id}")
    kb.adjust(1)

    # For existing comments, show reaction buttons for the last 5
    for c in comments[-5:]:
        kb.button(text=f"👍 {c['id']}", callback_data=f"re_like_{c['id']}")
        kb.button(text=f"👎 {c['id']}", callback_data=f"re_dis_{c['id']}")
    
    kb.adjust(1, 1, 2)
    await message.answer(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("com_add_"))
async def init_comment(cb: types.CallbackQuery, state: FSMContext):
    conf_id = int(cb.data.split("_")[2])
    await state.set_state(CommentForm.waiting_for_comment)
    await state.update_data(target_conf_id=conf_id)
    await cb.message.answer(f"💬 Write your comment for #{conf_id}:", reply_markup=ForceReply())
    await cb.answer()

@dp.message(CommentForm.waiting_for_comment)
async def process_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    conf_id = data['target_conf_id']
    
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO comments (confession_id, user_id, text) VALUES ($1, $2, $3)",
            conf_id, message.from_user.id, message.text
        )
    
    await state.clear()
    await message.answer(f"✅ Comment added to #{conf_id}!")

@dp.callback_query(F.data.startswith("re_"))
async def handle_reactions(cb: types.CallbackQuery):
    _, r_type, c_id = cb.data.split("_")
    c_id = int(c_id)
    r_type = "like" if r_type == "like" else "dislike"
    
    async with db.acquire() as conn:
        # Check for existing reaction
        existing = await conn.fetchval(
            "SELECT reaction_type FROM reactions WHERE comment_id = $1 AND user_id = $2",
            c_id, cb.from_user.id
        )
        
        if existing == r_type:
            return await cb.answer("You already reacted this way!", show_alert=False)

        # Get commenter info for point rewarding
        comment_info = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", c_id)
        
        if existing: # Toggle reaction
            await conn.execute(
                "UPDATE reactions SET reaction_type = $1 WHERE comment_id = $2 AND user_id = $3",
                r_type, c_id, cb.from_user.id
            )
        else: # New reaction
            await conn.execute(
                "INSERT INTO reactions (comment_id, user_id, reaction_type) VALUES ($1, $2, $3)",
                c_id, cb.from_user.id, r_type
            )

        # Update Aura Points
        points = POINTS_PER_LIKE_RECEIVED if r_type == "like" else POINTS_PER_DISLIKE_RECEIVED
        await conn.execute("UPDATE user_points SET points = points + $1 WHERE user_id = $2", points, comment_info['user_id'])

    await cb.answer(f"You {'liked' if r_type == 'like' else 'disliked'} this comment!")
# ==========================================
# MODULE 7: TRENDING, PROFILE & ADMIN MGMT
# ==========================================

@dp.message(Command("hot"))
async def show_trending(message: types.Message):
    """Algorithm: Most comments in the last 7 days."""
    async with db.acquire() as conn:
        hot_posts = await conn.fetch("""
            SELECT c.id, c.text, COUNT(com.id) as comment_count 
            FROM confessions c 
            JOIN comments com ON c.id = com.confession_id 
            WHERE c.status = 'approved' AND c.created_at > NOW() - INTERVAL '7 days'
            GROUP BY c.id 
            ORDER BY comment_count DESC 
            LIMIT 5
        """)
    
    if not hot_posts:
        return await message.answer("🔥 No hot topics yet. Start a discussion!")

    text = "<b>🔥 Trending Discussions (Last 7 Days)</b>\n\n"
    for row in hot_posts:
        preview = html.quote(row['text'][:60]) + "..."
        text += f"<b>#{row['id']}</b> ({row['comment_count']} 💬)\n{preview}\n/start view_{row['id']}\n\n"
    
    await message.answer(text)

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    async with db.acquire() as conn:
        points = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", user_id) or 0
        conf_count = await conn.fetchval("SELECT COUNT(*) FROM confessions WHERE user_id = $1 AND status = 'approved'", user_id)
    
    title = get_reputation_title(points)
    await message.answer(
        f"👤 <b>Your MWU Profile</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏅 <b>Aura Points:</b> {points}\n"
        f"🏷️ <b>Title:</b> {title}\n"
        f"✉️ <b>Approved Confessions:</b> {conf_count}\n\n"
        f"<i>Tip: Be helpful in comments to gain more Aura!</i>"
    )

@dp.message(Command("addadmin"))
async def cmd_add_admin(message: types.Message, command: CommandObject):
    """Allows the Primary Admin to promote others."""
    if message.from_user.id != PRIMARY_ADMIN:
        return await message.answer("❌ Only the Bot Creator can promote admins.")
    
    if not command.args:
        return await message.answer("Usage: /addadmin [user_id]")
    
    try:
        new_id = int(command.args)
        if new_id not in ADMIN_IDS:
            ADMIN_IDS.append(new_id)
            await message.answer(f"✅ User {new_id} added to the active Admin list.")
        else:
            await message.answer("User is already an admin.")
    except ValueError:
        await message.answer("❌ Invalid User ID.")

@dp.message(Command("check_me"))
async def cmd_check_me(message: types.Message):
    """Debug command to check current user ID and admin status."""
    user_id = message.from_user.id
    status = "Admin ✅" if is_admin(user_id) else "User 👤"
    await message.answer(f"🔍 <b>Debug Info:</b>\nYour ID: <code>{user_id}</code>\nStatus: {status}")
# ==========================================
# MODULE 8: MODERATION TOOLS & BROADCASTS
# ==========================================

@dp.message(Command("warn"))
async def cmd_warn(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id): return
    if not command.args: return await message.answer("Usage: /warn [user_id] [reason]")
    
    try:
        args = command.args.split(maxsplit=1)
        target_id = int(args[0])
        reason = args[1] if len(args) > 1 else "No reason provided."
        
        async with db.acquire() as conn:
            # Penalize Aura points for bad behavior
            await conn.execute("UPDATE user_points SET points = points - 50 WHERE user_id = $1", target_id)
            
        await message.answer(f"⚠️ User <code>{target_id}</code> warned. -50 Aura.")
        await safe_send_message(target_id, f"⚠️ <b>Official Warning:</b>\nReason: {reason}\n<i>Continued violations will lead to a block.</i>")
    except ValueError:
        await message.answer("Invalid User ID.")

@dp.message(Command("block"))
async def cmd_block(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id): return
    if not command.args: return await message.answer("Usage: /block [user_id] [days] [reason]")
    
    try:
        args = command.args.split(maxsplit=2)
        target_id = int(args[0])
        days = int(args[1])
        reason = args[2] if len(args) > 2 else "Violation of rules."
        until = datetime.now() + timedelta(days=days)
        
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_status (user_id, is_blocked, blocked_until, block_reason)
                VALUES ($1, True, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET is_blocked = True, blocked_until = $2, block_reason = $3
            """, target_id, until, reason)
            
        await message.answer(f"🚫 User <code>{target_id}</code> blocked for {days} days.")
        await safe_send_message(target_id, f"🚫 <b>You have been blocked:</b>\nDuration: {days} days\nReason: {reason}")
    except Exception as e:
        await message.answer(f"Error: {e}")

@dp.message(Command("unblock"))
async def cmd_unblock(message: types.Message, command: CommandObject):
    if not is_admin(message.from_user.id): return
    if not command.args: return await message.answer("Usage: /unblock [user_id]")
    
    try:
        target_id = int(command.args)
        async with db.acquire() as conn:
            await conn.execute("UPDATE user_status SET is_blocked = False WHERE user_id = $1", target_id)
        await message.answer(f"✅ User <code>{target_id}</code> unblocked.")
        await safe_send_message(target_id, "✅ Your block has been lifted. Please follow the rules.")
    except:
        await message.answer("Invalid ID.")

@dp.message(Command("notify"))
async def cmd_notify(message: types.Message, state: FSMContext):
    """Starts the global broadcast process."""
    if not is_admin(message.from_user.id): return
    
    await state.set_state(BroadcastState.waiting_for_broadcast_message)
    await message.answer("📢 <b>Broadcast Mode</b>\nSend the message you want to broadcast to ALL users (text/photo/video).", reply_markup=ForceReply())

@dp.message(BroadcastState.waiting_for_broadcast_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("Broadcast cancelled.")

    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM user_points")
        user_ids = [r['user_id'] for r in rows]

    await state.clear()
    status_msg = await message.answer(f"🚀 Broadcasting to {len(user_ids)} users...")

    success, failed = 0, 0
    for uid in user_ids:
        try:
            await message.copy_to(chat_id=uid)
            success += 1
            await asyncio.sleep(0.05) # Prevent flood limits
        except:
            failed += 1

    await status_msg.edit_text(f"✅ <b>Broadcast Complete</b>\n\nSuccess: {success}\nFailed: {failed}")
# ==========================================
# ==========================================
# MODULE 9: SERVER & MAIN ENTRY POINT (FIXED MENU)
# ==========================================

async def handle_health_check(request):
    return web.Response(text="MWU CONFESSION Bot is running!", status=200)

async def set_bot_commands():
    """Sets different menus for Admins and Regular Users."""
    
    # 1. Commands for EVERYONE
    user_commands = [
        types.BotCommand(command="start", description="Main Menu"),
        types.BotCommand(command="confess", description="Submit a Secret"),
        types.BotCommand(command="hot", description="Trending Posts"),
        types.BotCommand(command="profile", description="Your Stats"),
        types.BotCommand(command="rules", description="Read Rules")
    ]
    await bot.set_my_commands(user_commands, scope=types.BotCommandScopeDefault())

    # 2. Commands for ADMINS ONLY
    admin_commands = user_commands + [
        types.BotCommand(command="notify", description="Admin: Broadcast"),
        types.BotCommand(command="check_me", description="Admin: My Status"),
        types.BotCommand(command="addadmin", description="Admin: Promote User")
    ]
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(
                admin_commands, 
                scope=types.BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception:
            # Skip if the admin hasn't started the bot yet
            continue

async def main():
    await setup_db()
    
    # Update the menus
    await set_bot_commands()

    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")


