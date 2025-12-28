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

# --- NEW: Word Filter ---
BANNED_WORDS = ["scam", "nude", "hack", "t.me/", "telegram.me"]

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
DATABASE_URL = os.getenv("DATABASE_URL")
HTTP_PORT_STR = os.getenv("PORT")

if not BOT_TOKEN or not ADMIN_ID_STR or not CHANNEL_ID or not DATABASE_URL:
    raise ValueError("FATAL: Missing essential environment variables!")

ADMIN_ID = int(ADMIN_ID_STR)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = None
bot_info = None

# ==========================================
# MODULE 2: REPUTATION & AURA TITLES
# ==========================================
def get_reputation_title(points: int) -> str:
    """Returns a title based on user aura points."""
    if points >= 500: return "Legend 🏆"
    if points >= 201: return "Wise Elder 🧙‍♂️"
    if points >= 51: return "Truth Teller 🗣️"
    if points >= 0: return "Newbie 🌱"
    return "Troublemaker 💀"

# ==========================================
# MODULE 3: FSM STATES & DATABASE SETUP
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

async def create_db_pool():
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return pool
    except Exception as e:
        logging.error(f"Failed to create database pool: {e}")
        raise

async def setup():
    global db, bot_info
    db = await create_db_pool()
    bot_info = await bot.get_me()
    async with db.acquire() as conn:
        # Create core tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (
                id SERIAL PRIMARY KEY, text TEXT NOT NULL, user_id BIGINT NOT NULL,
                status VARCHAR(10) DEFAULT 'pending', message_id BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                rejection_reason TEXT NULL, categories TEXT[] NULL
            );
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY, confession_id INTEGER REFERENCES confessions(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL, text TEXT NULL, sticker_file_id TEXT NULL,
                animation_file_id TEXT NULL, parent_comment_id INTEGER REFERENCES comments(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_points (
                user_id BIGINT PRIMARY KEY, points INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_status (
                user_id BIGINT PRIMARY KEY, has_accepted_rules BOOLEAN NOT NULL DEFAULT FALSE,
                is_blocked BOOLEAN NOT NULL DEFAULT FALSE, blocked_until TIMESTAMP WITH TIME ZONE NULL,
                block_reason TEXT NULL
            );
            CREATE TABLE IF NOT EXISTS reactions (
                id SERIAL PRIMARY KEY, comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL, reaction_type VARCHAR(10) NOT NULL,
                UNIQUE(comment_id, user_id)
            );
        """)
    logging.info("Database modules initialized.")

# ==========================================
# MODULE 4: CORE HELPER FUNCTIONS
# ==========================================
async def get_user_points(user_id: int) -> int:
    async with db.acquire() as conn:
        return await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", user_id) or 0

async def get_comment_reactions(comment_id: int) -> Tuple[int, int]:
    async with db.acquire() as conn:
        counts = await conn.fetchrow(
            "SELECT COALESCE(SUM(CASE WHEN reaction_type = 'like' THEN 1 ELSE 0 END), 0) AS likes, "
            "COALESCE(SUM(CASE WHEN reaction_type = 'dislike' THEN 1 ELSE 0 END), 0) AS dislikes "
            "FROM reactions WHERE comment_id = $1", comment_id)
        return counts['likes'], counts['dislikes']

async def build_comment_keyboard(comment_id: int, commenter_user_id: int, viewer_user_id: int, confession_owner_id: int):
    likes, dislikes = await get_comment_reactions(comment_id)
    builder = InlineKeyboardBuilder()
    builder.button(text=f"👍 {likes}", callback_data=f"react_like_{comment_id}")
    builder.button(text=f"👎 {dislikes}", callback_data=f"react_dislike_{comment_id}")
    builder.button(text="↪️ Reply", callback_data=f"reply_{comment_id}")
    if viewer_user_id == ADMIN_ID:
        builder.button(text="🗑️ Delete/Warn", callback_data=f"admin_warn_delete_{comment_id}")
    builder.adjust(3)
    return builder.as_markup()

async def safe_send_message(user_id: int, text: str, **kwargs) -> Optional[types.Message]:
    try:
        return await bot.send_message(user_id, text, **kwargs)
    except Exception as e:
        logging.warning(f"Could not send message to {user_id}: {e}")
        return None

# ==========================================
# MODULE 5: FEATURE: COMMENT VIEWER (FIXED)
# ==========================================
async def show_comments_for_confession(user_id: int, confession_id: int, page: int = 1):
    async with db.acquire() as conn:
        conf = await conn.fetchrow("SELECT user_id, status FROM confessions WHERE id = $1", confession_id)
        if not conf or conf['status'] != 'approved': return

        owner_id = conf['user_id']
        total = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id) or 0
        offset = (page - 1) * PAGE_SIZE
        
        comments = await conn.fetch("""
            SELECT c.*, COALESCE(up.points, 0) as pts 
            FROM comments c 
            LEFT JOIN user_points up ON c.user_id = up.user_id 
            WHERE c.confession_id = $1 ORDER BY c.created_at ASC LIMIT $2 OFFSET $3
        """, confession_id, PAGE_SIZE, offset)

        for i, c in enumerate(comments):
            seq = offset + i + 1
            pts = c['pts']
            title = get_reputation_title(pts)
            tag = "(Author)" if c['user_id'] == owner_id else "(You)" if c['user_id'] == user_id else "Anonymous"
            
            # FIXED: Removed code tags from UID to prevent parsing crashes
            admin_tag = f" [UID: {c['user_id']}]" if user_id == ADMIN_ID else ""
            meta = f"<i>#{seq} {tag} | {pts} {title}{admin_tag}</i>"
            
            kb = await build_comment_keyboard(c['id'], c['user_id'], user_id, owner_id)
            if c['text']:
                await safe_send_message(user_id, f"💬 {html.quote(c['text'])}\n\n{meta}", reply_markup=kb)
            elif c['sticker_file_id']:
                await bot.send_sticker(user_id, c['sticker_file_id'])
                await safe_send_message(user_id, meta, reply_markup=kb)

# ==========================================
# MODULE 6: FEATURE: HOT CONFESSIONS
# ==========================================
@dp.message(Command("hot"))
async def show_hot_confessions(message: types.Message):
    async with db.acquire() as conn:
        hot_list = await conn.fetch("""
            SELECT c.id, c.text, COUNT(com.id) as count 
            FROM confessions c 
            JOIN comments com ON c.id = com.confession_id 
            WHERE c.status = 'approved' AND c.created_at > NOW() - INTERVAL '7 days'
            GROUP BY c.id ORDER BY count DESC LIMIT 5
        """)
    if not hot_list: return await message.answer("No hot topics this week!")
    text = "<b>🔥 Hot Confessions This Week</b>\n\n"
    for row in hot_list:
        text += f"#{row['id']} ({row['count']} 💬)\n<i>{html.quote(row['text'][:50])}...</i>\n/start view_{row['id']}\n\n"
    await message.answer(text)

# ==========================================
# MODULE 7: ADMIN POWER TOOLS
# ==========================================
@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_replies(message: types.Message):
    if message.text and message.text.lower().strip() == "id":
        try:
            target_id = int(message.reply_to_message.text.split("UID: ")[1].split("]")[0])
            points = await get_user_points(target_id)
            await message.answer(f"🔎 <b>User:</b> <code>{target_id}</code>\n🏅 <b>Aura:</b> {points}\n/id {target_id}")
        except:
            pass

@dp.callback_query(F.data.startswith("admin_warn_delete_"))
async def admin_delete(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    comment_id = int(cb.data.split("_")[3])
    async with db.acquire() as conn:
        target = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", comment_id)
        if target:
            await conn.execute("DELETE FROM comments WHERE id = $1", comment_id)
            await conn.execute("UPDATE user_points SET points = points - 10 WHERE user_id = $1", target['user_id'])
            await safe_send_message(target['user_id'], "⚠️ <b>Warning:</b> Your comment was deleted by admin. -10 Aura.")
            await cb.answer("Comment deleted. Penalty applied.", show_alert=True)
            await cb.message.delete()

# ==========================================
# MODULE 8: MAIN BOT HANDLERS & STARTUP
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    async with db.acquire() as conn:
        await conn.execute("INSERT INTO user_points (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
    
    if command.args and command.args.startswith("view_"):
        conf_id = int(command.args.split("_")[1])
        await show_comments_for_confession(user_id, conf_id)
    else:
        await message.answer("Welcome to AAU Confessions! Use /confess to share or /hot to see trends.")

# [Additional 600+ lines of your original logic for Submission, Moderation, etc. follow here]

async def main():
    await setup()
    # Start polling...
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
