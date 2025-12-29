import logging
import asyncpg
import os
import asyncio
from aiogram import Bot, Dispatcher, types, F, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, ReplyKeyboardRemove, ForceReply
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from typing import Optional, Tuple, Dict, Any, List
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiohttp import web

import logging
import asyncpg
import os
import asyncio
from aiogram import Bot, Dispatcher, types, F, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, ReplyKeyboardRemove, ForceReply
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from typing import Optional, Tuple, Dict, Any, List
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiohttp import web

# ==========================================
# MODULE 1: CONFIGURATION & CONSTANTS
# ==========================================
CATEGORIES = [
    "Relationship", "Family", "School", "Friendship",
    "Religion", "Mental", "Addiction", "Harassment", "Crush", "Health", "Trauma", "Sexual Assault",
    "Other"
]
POINTS_PER_CONFESSION = 1
POINTS_PER_LIKE_RECEIVED = 3
POINTS_PER_DISLIKE_RECEIVED = -3
MAX_CATEGORIES = 3 
PAGE_SIZE = 15
BANNED_WORDS = ["scam", "nude", "hack", "t.me/", "telegram.me"]

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID", "")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DATABASE_URL = os.getenv("DATABASE_URL")
HTTP_PORT_STR = os.getenv("PORT", "8080")

if not BOT_TOKEN or not ADMIN_ID_STR or not CHANNEL_ID or not DATABASE_URL:
    raise ValueError("FATAL: Missing Environment Variables!")

# --- MULTI-ADMIN CONFIGURATION ---
# This converts "123,456" into a list [123, 456]
ADMIN_IDS = [int(i.strip()) for i in ADMIN_ID_STR.split(",") if i.strip()]

# Defines the 'Super Admin' (the first ID in your Render list)
PRIMARY_ADMIN = ADMIN_IDS[0] if ADMIN_IDS else None

# Keep this for any older modules still using the singular variable
ADMIN_ID = PRIMARY_ADMIN 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = None
bot_info = None

# Helper function required by Module 10
def is_admin(user_id: int) -> bool:
    """Check if a user is in the authorized admin list."""
    return user_id in ADMIN_IDS
# ==========================================
# MODULE 2: REPUTATION & AURA TITLES
# ==========================================
def get_reputation_title(points: int) -> str:
    """Returns the title string based on points."""
    if points >= 500: return "Legend 🏆"
    if points >= 201: return "Wise Elder 🧙‍♂️"
    if points >= 51: return "Truth Teller 🗣️"
    if points >= 0: return "Newbie 🌱"
    return "Troublemaker 💀"
# ==========================================
# MODULE 3: FSM STATES
# ==========================================
class ConfessionForm(StatesGroup):
    selecting_categories = State()
    waiting_for_text = State()

class CommentForm(StatesGroup):
    waiting_for_comment = State()
    waiting_for_reply = State()

class ContactAdminForm(StatesGroup):
    waiting_for_message = State()

class AdminActions(StatesGroup):
    waiting_for_rejection_reason = State()

# ==========================================
# MODULE 4: DATABASE SETUP & MIDDLEWARE
# ==========================================
async def setup_db():
    global db, bot_info
    db = await asyncpg.create_pool(DATABASE_URL)
    bot_info = await bot.get_me()
    
    async with db.acquire() as conn:
        # 1. Initializing all core tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (
                id SERIAL PRIMARY KEY, 
                text TEXT, 
                user_id BIGINT, 
                status VARCHAR(10) DEFAULT 'pending', 
                message_id BIGINT, 
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
                categories TEXT[]
            );
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY, 
                confession_id INTEGER REFERENCES confessions(id) ON DELETE CASCADE, 
                user_id BIGINT, 
                text TEXT, 
                sticker_file_id TEXT, 
                animation_file_id TEXT, 
                parent_comment_id INTEGER, 
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_status (
                user_id BIGINT PRIMARY KEY, 
                has_accepted_rules BOOLEAN DEFAULT FALSE, 
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
            CREATE TABLE IF NOT EXISTS authorized_admins (
                user_id BIGINT PRIMARY KEY, 
                added_by BIGINT, 
                added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Syncing Admins (This MUST be inside the 'async with' block)
        rows = await conn.fetch("SELECT user_id FROM authorized_admins")
        for r in rows:
            if r['user_id'] not in ADMIN_IDS:
                ADMIN_IDS.append(r['user_id'])
    
    print(f"✅ DB Ready. Total Admins in memory: {len(ADMIN_IDS)}")

class BlockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            async with db.acquire() as conn:
                status = await conn.fetchrow(
                    "SELECT is_blocked, blocked_until FROM user_status WHERE user_id = $1", 
                    user.id
                )
                if status and status['is_blocked']:
                    if status['blocked_until'] and datetime.now(status['blocked_until'].tzinfo) > status['blocked_until']:
                        await conn.execute("UPDATE user_status SET is_blocked = False WHERE user_id = $1", user.id)
                    else:
                        if isinstance(event, types.CallbackQuery):
                            await event.answer("🚫 You are currently blocked.", show_alert=True)
                        else:
                            await event.answer("🚫 You are currently blocked from using this bot.")
                        return
        return await handler(event, data)

# Registering the middleware
dp.message.outer_middleware(BlockMiddleware())
dp.callback_query.outer_middleware(BlockMiddleware())
# ==========================================
# MODULE 5: CONFESSION SUBMISSION LOGIC
# ==========================================

@dp.message(Command("confess"))
async def start_confess(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with db.acquire() as conn:
        # Check if user exists and has accepted rules
        status = await conn.fetchrow("SELECT has_accepted_rules FROM user_status WHERE user_id = $1", user_id)
        
        if not status or not status['has_accepted_rules']:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📜 Read Rules", callback_data="view_rules")]
            ])
            return await message.answer("⚠️ You must accept the rules before you can post a confession.", reply_markup=kb)

    # Initialize category selection
    builder = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        builder.button(text=cat, callback_data=f"sel_cat_{cat}")
    builder.button(text="✅ Done Selecting", callback_data="cats_complete")
    builder.adjust(2)
    
    await state.set_state(ConfessionForm.selecting_categories)
    await state.update_data(chosen_cats=[])
    await message.answer(
        "<b>Step 1:</b> Select up to 3 categories that fit your confession:", 
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("sel_cat_"), ConfessionForm.selecting_categories)
async def process_category_toggle(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chosen = data.get("chosen_cats", [])
    category = cb.data.split("_")[2]
    
    if category in chosen:
        chosen.remove(category)
        await cb.answer(f"Removed {category}")
    elif len(chosen) < MAX_CATEGORIES:
        chosen.append(category)
        await cb.answer(f"Added {category}")
    else:
        return await cb.answer("You can only choose up to 3 categories!", show_alert=True)
    
    await state.update_data(chosen_cats=chosen)
    # Note: We don't edit the message here to avoid "Message is not modified" errors, 
    # but we track the list in the state.

@dp.callback_query(F.data == "cats_complete", ConfessionForm.selecting_categories)
async def categories_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("chosen_cats"):
        return await cb.answer("Please select at least one category!", show_alert=True)
    
    await state.set_state(ConfessionForm.waiting_for_text)
    await cb.message.edit_text(
        "<b>Step 2:</b> Now, please type your confession below.\n\n"
        "<i>Your post will be completely anonymous. Avoid sharing personal names or phone numbers.</i>"
    )

@dp.message(ConfessionForm.waiting_for_text)
async def handle_confession_submission(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 10:
        return await message.answer("❌ Your confession is too short. Please add more detail (min 10 characters).")
    
    # Word Filtering Logic
    text_low = message.text.lower()
    if any(word in text_low for word in BANNED_WORDS):
        return await message.answer("❌ Your post was flagged for containing prohibited links or banned words.")

    data = await state.get_data()
    cats = data.get("chosen_cats")
    
    async with db.acquire() as conn:
        # Save to DB as pending
        conf_id = await conn.fetchval(
            "INSERT INTO confessions (text, user_id, categories, status) VALUES ($1, $2, $3, 'pending') RETURNING id",
            message.text, message.from_user.id, cats
        )
    
    await state.clear()
    await message.answer(
        f"✅ <b>Confession #{conf_id} submitted!</b>\n"
        "It has been sent to the moderation team. You will be notified once it is approved and posted."
    )
    
    # Notify the Admin (Module 7 will handle the buttons for this)
    admin_kb = InlineKeyboardBuilder()
    admin_kb.button(text="✅ Approve", callback_data=f"adm_approve_{conf_id}")
    admin_kb.button(text="❌ Reject", callback_data=f"adm_reject_{conf_id}")
    
    await bot.send_message(
        ADMIN_ID, 
        f"🆕 <b>New Submission #{conf_id}</b>\n"
        f"📂 Categories: {', '.join(cats)}\n"
        f"👤 User UID: <code>{message.from_user.id}</code>\n\n"
        f"{html.quote(message.text)}",
        reply_markup=admin_kb.as_markup()
    )
    # ==========================================
# MODULE 6: COMMENTING & VIEWING SYSTEM
# ==========================================

async def get_comment_reactions(comment_id: int) -> Tuple[int, int]:
    """Helper to fetch reaction counts for a specific comment."""
    async with db.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE reaction_type = 'like') as likes,
                COUNT(*) FILTER (WHERE reaction_type = 'dislike') as dislikes
            FROM reactions WHERE comment_id = $1
        """, comment_id)
        return row['likes'], row['dislikes']

async def build_comment_keyboard(comment_id: int, commenter_uid: int, viewer_uid: int, owner_uid: int):
    """Generates the buttons for each comment (Like, Dislike, Reply, Admin Tools)."""
    likes, dislikes = await get_comment_reactions(comment_id)
    builder = InlineKeyboardBuilder()
    
    # Interaction Buttons
    builder.button(text=f"👍 {likes}", callback_data=f"re_like_{comment_id}")
    builder.button(text=f"👎 {dislikes}", callback_data=f"re_dis_{comment_id}")
    builder.button(text="↪️ Reply", callback_data=f"com_reply_{comment_id}")
    
    # Contact request (Only confession owner can request contact with commenter)
    if viewer_uid == owner_uid and viewer_uid != commenter_uid:
        builder.button(text="🤝 Request Contact", callback_data=f"contact_req_{comment_id}")
    
    # Admin deletion tool
    if viewer_uid == ADMIN_ID:
        builder.button(text="🗑️ Delete (Admin)", callback_data=f"adm_del_com_{comment_id}")
    
    builder.adjust(3, 1)
    return builder.as_markup()

async def show_comments_for_confession(user_id: int, confession_id: int, page: int = 1):
    """The main engine that displays comments to the user."""
    async with db.acquire() as conn:
        # Check if confession is approved
        conf = await conn.fetchrow("SELECT user_id, status FROM confessions WHERE id = $1", confession_id)
        if not conf or conf['status'] != 'approved':
            return await bot.send_message(user_id, "❌ This confession is no longer available.")
        
        owner_id = conf['user_id']
        offset = (page - 1) * PAGE_SIZE
        
        # Optimized JOIN query to get comment data and User Aura at once
        comments = await conn.fetch("""
            SELECT c.*, COALESCE(up.points, 0) as pts 
            FROM comments c 
            LEFT JOIN user_points up ON c.user_id = up.user_id 
            WHERE c.confession_id = $1 
            ORDER BY c.created_at ASC 
            LIMIT $2 OFFSET $3
        """, confession_id, PAGE_SIZE, offset)

        if not comments and page == 1:
            return await bot.send_message(user_id, "💬 <i>No comments yet. Be the first to start the conversation!</i>")

        for i, c in enumerate(comments):
            seq = offset + i + 1
            pts = c['pts']
            title = get_reputation_title(pts)
            
            # Identify the commenter
            if c['user_id'] == owner_id:
                tag = "📝 Author"
            elif c['user_id'] == user_id:
                tag = "👤 You"
            else:
                tag = "👥 Anonymous"
            
            # Fixed Metadata: Admin gets UID for moderation, others don't
            admin_info = f" | ID: {c['user_id']}" if user_id == ADMIN_ID else ""
            meta = f"<i>#{seq} {tag} | {pts} {title}{admin_info}</i>"
            
            kb = await build_comment_keyboard(c['id'], c['user_id'], user_id, owner_id)
            
            try:
                if c['text']:
                    await bot.send_message(user_id, f"💬 {html.quote(c['text'])}\n\n{meta}", reply_markup=kb)
                elif c['sticker_file_id']:
                    await bot.send_sticker(user_id, c['sticker_file_id'])
                    await bot.send_message(user_id, meta, reply_markup=kb)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                # Re-try sending once after delay
                await bot.send_message(user_id, f"💬 {html.quote(c['text'])}\n\n{meta}", reply_markup=kb)
            except Exception as e:
                logging.error(f"Error sending comment #{c['id']}: {e}")

        # Add Pagination "Next Page" button if there are more comments
        total_comments = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id)
        if total_comments > offset + PAGE_SIZE:
            nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➡️ Load More Comments", callback_data=f"page_{confession_id}_{page+1}")
            ]])
            await bot.send_message(user_id, "There are more comments below:", reply_markup=nav_kb)

@dp.callback_query(F.data.startswith("page_"))
async def handle_pagination(cb: types.CallbackQuery):
    _, conf_id, next_page = cb.data.split("_")
    await cb.message.delete()
    await show_comments_for_confession(cb.from_user.id, int(conf_id), int(next_page))
# ==========================================
# MODULE 7: ADMIN ACTIONS & HOT LIST
# ==========================================
# ==========================================
# MODULE 7.5: ADVANCED MODERATION
# ==========================================

@dp.message(Command("warn"))
async def cmd_warn(message: types.Message, command: CommandObject):
    if message.chat.id != ADMIN_ID and message.from_user.id not in ADMIN_IDS: return
    if not command.args: return await message.answer("Usage: /warn [user_id] [reason]")
    
    try:
        args = command.args.split(maxsplit=1)
        target_id = int(args[0])
        reason = args[1] if len(args) > 1 else "No reason provided."
        
        async with db.acquire() as conn:
            # Penalize Aura points
            await conn.execute("UPDATE user_points SET points = points - 50 WHERE user_id = $1", target_id)
            
        await message.answer(f"⚠️ User <code>{target_id}</code> has been warned. -50 Aura.")
        await safe_send_message(target_id, f"⚠️ <b>Official Warning:</b>\nYou have been warned by an admin.\nReason: {reason}\n<i>Continued violations will lead to a block.</i>")
    except ValueError:
        await message.answer("Invalid User ID.")

@dp.message(Command("block"))
async def cmd_block(message: types.Message, command: CommandObject):
    if message.chat.id != ADMIN_ID and message.from_user.id not in ADMIN_IDS: return
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

@dp.message(Command("pblock"))
async def cmd_pblock(message: types.Message, command: CommandObject):
    if message.chat.id != ADMIN_ID and message.from_user.id not in ADMIN_IDS: return
    if not command.args: return await message.answer("Usage: /pblock [user_id]")
    
    target_id = int(command.args)
    async with db.acquire() as conn:
        await conn.execute("UPDATE user_status SET is_blocked = True, blocked_until = NULL WHERE user_id = $1", target_id)
        
    await message.answer(f"💀 User <code>{target_id}</code> permanently banned.")
    await safe_send_message(target_id, "❌ <b>Permanent Ban:</b>\nYou have been permanently banned from this bot.")

@dp.message(Command("unblock"))
async def cmd_unblock(message: types.Message, command: CommandObject):
    if message.chat.id != ADMIN_ID and message.from_user.id not in ADMIN_IDS: return
    if not command.args: return await message.answer("Usage: /unblock [user_id]")
    
    target_id = int(command.args)
    async with db.acquire() as conn:
        await conn.execute("UPDATE user_status SET is_blocked = False WHERE user_id = $1", target_id)
        
    await message.answer(f"✅ User <code>{target_id}</code> unblocked.")
    await safe_send_message(target_id, "✅ Your block has been lifted. Please follow the rules.")

@dp.callback_query(F.data.startswith("adm_approve_"))
async def approve_submission(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    conf_id = int(cb.data.split("_")[2])
    async with db.acquire() as conn:
        data = await conn.fetchrow(
            "UPDATE confessions SET status = 'approved' WHERE id = $1 RETURNING text, user_id, categories", 
            conf_id
        )
    
    if data:
        # Generate the Channel Post
        post_text = (
            f"<b>📝 Confession #{conf_id}</b>\n"
            f"📂 Categories: <i>{', '.join(data['categories'])}</i>\n\n"
            f"{html.quote(data['text'])}"
        )
        
        # Keyboard for the Channel
        channel_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="💬 Read & Reply to Comments", 
                url=f"https://t.me/{bot_info.username}?start=view_{conf_id}"
            )
        ]])
        
        # Post to the main channel
        sent_msg = await bot.send_message(CHANNEL_ID, post_text, reply_markup=channel_kb)
        
        # Save the message ID and reward the user +1 Aura
        async with db.acquire() as conn:
            await conn.execute("UPDATE confessions SET message_id = $1 WHERE id = $2", sent_msg.message_id, conf_id)
            await conn.execute("UPDATE user_points SET points = points + $1 WHERE user_id = $2", POINTS_PER_CONFESSION, data['user_id'])
        
        await cb.message.edit_text(f"✅ <b>Approved Confession #{conf_id}</b>\nPosted to channel.")
        await safe_send_message(data['user_id'], f"🎉 <b>Great news!</b> Your confession #{conf_id} was approved and posted to the channel.")

@dp.callback_query(F.data.startswith("adm_reject_"))
async def reject_submission(cb: types.CallbackQuery, state: FSMContext):
    if cb.from_user.id != ADMIN_ID: return
    
    conf_id = int(cb.data.split("_")[2])
    await state.set_state(AdminActions.waiting_for_rejection_reason)
    await state.update_data(reject_id=conf_id)
    
    await cb.message.answer(f"Please type the reason for rejecting #{conf_id}:", reply_markup=ForceReply())
    await cb.answer()

@dp.message(AdminActions.waiting_for_rejection_reason)
async def process_rejection(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    
    data = await state.get_data()
    conf_id = data['reject_id']
    reason = message.text
    
    async with db.acquire() as conn:
        user_id = await conn.fetchval("UPDATE confessions SET status = 'rejected', rejection_reason = $1 WHERE id = $2 RETURNING user_id", reason, conf_id)
    
    await state.clear()
    await message.answer(f"❌ Confession #{conf_id} has been rejected.")
    await safe_send_message(user_id, f"😔 <b>Submission Update:</b>\nYour confession #{conf_id} was not approved.\n\n<b>Reason:</b> {reason}")

# --- HOT LIST LOGIC ---
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

# --- PROFILE LOGIC ---
@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    async with db.acquire() as conn:
        points = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", user_id) or 0
        conf_count = await conn.fetchval("SELECT COUNT(*) FROM confessions WHERE user_id = $1 AND status = 'approved'", user_id)
    
    title = get_reputation_title(points)
    await message.answer(
        f"👤 <b>Your Profile</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏅 <b>Aura Points:</b> {points}\n"
        f"🏷️ <b>Title:</b> {title}\n"
        f"✉️ <b>Approved Confessions:</b> {conf_count}\n\n"
        f"<i>Tip: Be helpful in comments and post quality confessions to gain more Aura!</i>"
    )
    # ==========================================
# MODULE 8: REACTIONS, CONTACTS & COMMENTING
# ==========================================

@dp.callback_query(F.data.startswith("re_"))
async def handle_reactions(cb: types.CallbackQuery):
    """Handles logic for 👍 Likes and 👎 Dislikes."""
    _, r_type, c_id = cb.data.split("_")
    c_id = int(c_id)
    r_type = "like" if r_type == "like" else "dislike"
    
    async with db.acquire() as conn:
        # Get existing reaction
        existing = await conn.fetchval(
            "SELECT reaction_type FROM reactions WHERE comment_id = $1 AND user_id = $2", 
            c_id, cb.from_user.id
        )
        
        # Determine the aura change for the commenter
        commenter_id = await conn.fetchval("SELECT user_id FROM comments WHERE id = $1", c_id)
        points_to_add = POINTS_PER_LIKE_RECEIVED if r_type == "like" else POINTS_PER_DISLIKE_RECEIVED

        if existing == r_type:
            # Remove reaction if clicked twice
            await conn.execute("DELETE FROM reactions WHERE comment_id = $1 AND user_id = $2", c_id, cb.from_user.id)
            await conn.execute("UPDATE user_points SET points = points - $1 WHERE user_id = $2", points_to_add, commenter_id)
            await cb.answer("Reaction removed")
        else:
            # Update or Insert reaction
            await conn.execute("""
                INSERT INTO reactions (comment_id, user_id, reaction_type) 
                VALUES ($1, $2, $3) 
                ON CONFLICT (comment_id, user_id) DO UPDATE SET reaction_type = $3
            """, c_id, cb.from_user.id, r_type)
            await conn.execute("UPDATE user_points SET points = points + $1 WHERE user_id = $2", points_to_add, commenter_id)
            await cb.answer(f"You {r_type}d this")

    # Refresh the specific comment's keyboard to show updated counts
    # (Optional logic here to edit the specific message keyboard)

@dp.callback_query(F.data.startswith("contact_req_"))
async def handle_contact_request(cb: types.CallbackQuery):
    """Allows confession owners to request the username of a commenter."""
    c_id = int(cb.data.split("_")[2])
    
    async with db.acquire() as conn:
        commenter = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", c_id)
        conf_id = await conn.fetchval("SELECT confession_id FROM comments WHERE id = $1", c_id)

    if commenter:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Share Username", callback_data=f"share_yes_{cb.from_user.id}_{conf_id}")
        kb.button(text="❌ Decline", callback_data="share_no")
        
        await safe_send_message(
            commenter['user_id'], 
            f"🤝 <b>Contact Request!</b>\nSomeone who posted confession #{conf_id} would like to talk to you privately. "
            "Do you want to share your username with them?", 
            reply_markup=kb.as_markup()
        )
        await cb.answer("Request sent to the commenter!", show_alert=True)

@dp.callback_query(F.data.startswith("com_reply_"))
async def start_reply(cb: types.CallbackQuery, state: FSMContext):
    """Sets the state to wait for a reply text."""
    c_id = int(cb.data.split("_")[2])
    await state.set_state(CommentForm.waiting_for_reply)
    await state.update_data(reply_to_cid=c_id)
    await cb.message.answer("💬 Type your reply to this comment:", reply_markup=ForceReply())

@dp.message(CommentForm.waiting_for_reply)
async def process_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    parent_cid = data['reply_to_cid']
    
    async with db.acquire() as conn:
        conf_id = await conn.fetchval("SELECT confession_id FROM comments WHERE id = $1", parent_cid)
        await conn.execute(
            "INSERT INTO comments (confession_id, user_id, text, parent_comment_id) VALUES ($1, $2, $3, $4)",
            conf_id, message.from_user.id, message.text, parent_cid
        )
    
    await state.clear()
    await message.answer("✅ Reply posted!")

@dp.callback_query(F.data.startswith("adm_del_com_"))
async def admin_delete_comment(cb: types.CallbackQuery):
    """Admin tool to delete a comment and penalize the user."""
    if cb.from_user.id != ADMIN_ID: return
    c_id = int(cb.data.split("_")[3])
    
    async with db.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", c_id)
        if user:
            await conn.execute("DELETE FROM comments WHERE id = $1", c_id)
            await conn.execute("UPDATE user_points SET points = points - 20 WHERE user_id = $1", user['user_id'])
            await safe_send_message(user['user_id'], "⚠️ <b>Warning:</b> Your comment was deleted for violating rules. -20 Aura.")
    
    await cb.message.delete()
    await cb.answer("Comment deleted and penalty applied.", show_alert=True)
# ==========================================
# MODULE 8.5: NOTIFICATION (BROADCAST) SYSTEM
# ==========================================

class BroadcastState(StatesGroup):
    waiting_for_broadcast_message = State()

@dp.message(Command("notify"))
async def cmd_notify(message: types.Message, state: FSMContext):
    """Admin command to start a broadcast."""
    if message.chat.id != ADMIN_ID and message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(BroadcastState.waiting_for_broadcast_message)
    await message.answer(
        "📢 <b>Broadcast Mode Active</b>\n\n"
        "Please send the message (text, photo, or video) you want to send to ALL users.\n"
        "Type /cancel to abort.",
        reply_markup=ForceReply()
    )

@dp.message(BroadcastState.waiting_for_broadcast_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    """Sends the received message to every user in the database."""
    if message.text == "/cancel":
        await state.clear()
        return await message.answer("Broadcast cancelled.")

    # 1. Get all unique users from your various tables
    async with db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id FROM user_points
            UNION
            SELECT user_id FROM user_status
        """)
        user_ids = [r['user_id'] for r in rows]

    await state.clear()
    status_msg = await message.answer(f"🚀 Starting broadcast to {len(user_ids)} users...")

    success = 0
    failed = 0

    for uid in user_ids:
        try:
            # This copies whatever you sent (text, image, etc.) and forwards it
            await message.copy_to(chat_id=uid)
            success += 1
            # Small delay to avoid Telegram flood limits
            await asyncio.sleep(0.05) 
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await message.copy_to(chat_id=uid)
            success += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"📊 Stats:\n"
        f"• Success: {success}\n"
        f"• Failed/Blocked: {failed}"
    )

# --- BONUS: /cancel handler ---
@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Current action cancelled.", reply_markup=ReplyKeyboardRemove())
# ==========================================
# MODULE 10: DYNAMIC ADMIN MANAGEMENT + DEBUG
# ==========================================

@dp.message(Command("check_me"))
async def cmd_check_me(message: types.Message):
    """Debug command to verify Admin IDs."""
    user_id = message.from_user.id
    debug_info = (
        f"🔍 <b>DEBUG REPORT</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 <b>Your ID:</b> <code>{user_id}</code>\n"
        f"👑 <b>Primary Admin:</b> <code>{PRIMARY_ADMIN}</code>\n"
        f"👥 <b>Admin List:</b> <code>{ADMIN_IDS}</code>\n"
        f"✅ <b>Match?:</b> {'YES' if user_id == PRIMARY_ADMIN else 'NO'}"
    )
    await message.answer(debug_info)

@dp.message(Command("addadmin"))
async def cmd_add_admin(message: types.Message, command: CommandObject):
    if message.from_user.id != PRIMARY_ADMIN:
        return await message.answer("❌ Only the Creator can promote others.")
    
    if not command.args:
        return await message.answer("Usage: /addadmin [user_id]")
    
    try:
        new_id = int(command.args)
        async with db.acquire() as conn:
            await conn.execute(
                "INSERT INTO authorized_admins (user_id, added_by) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                new_id, message.from_user.id
            )
            if new_id not in ADMIN_IDS:
                ADMIN_IDS.append(new_id)
        await message.answer(f"✅ User {new_id} added as Admin.")
    except ValueError:
        await message.answer("❌ Invalid User ID.")
# ... (End of Module 10: addadmin and check_me) ...

# ==========================================
# INSERT THE CODE HERE (Right before Module 9)
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # This is where you put your new welcome message
    welcome_text = "👋 Hello! Welcome to the bot."
    await message.answer(welcome_text)

# ==========================================
# MODULE 9: MAIN ENTRY & STARTUP
# ==========================================

async def handle_health_check(request):
    return web.Response(text="Bot is online.", status=200)

async def main():
    await setup_db()
    
    # Clean list: No duplicates, correct commas, one set of brackets
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Main menu"),
        types.BotCommand(command="confess", description="Post a confession"),
        types.BotCommand(command="hot", description="Trending posts"),
        types.BotCommand(command="profile", description="Check your Aura"),
        types.BotCommand(command="rules", description="Read rules"),
        types.BotCommand(command="check_me", description="DEBUG: Check Admin Status"),
        types.BotCommand(command="addadmin", description="CREATOR: Add admin"),
        types.BotCommand(command="adminlist", description="ADMIN: View staff"),
        types.BotCommand(command="cancel", description="Cancel current action")
    ])

    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logging.info(f"Bot starting on Port {port}...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot successfully stopped.")

