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

# --- Constants ---
CATEGORIES = [
    "Relationship", "Family", "School", "Friendship",
    "Religion", "Mental", "Addiction", "Harassment", "Crush", "Health", "Trauma", "Sexual Assault",
    "Other"
]
POINTS_PER_CONFESSION = 1
POINTS_PER_LIKE_RECEIVED = 3
POINTS_PER_DISLIKE_RECEIVED = -3
MAX_CATEGORIES = 3 

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "15"))
DATABASE_URL = os.getenv("DATABASE_URL")
HTTP_PORT_STR = os.getenv("PORT")

if not BOT_TOKEN: raise ValueError("FATAL: BOT_TOKEN not set!")
if not ADMIN_ID_STR: raise ValueError("FATAL: ADMIN_ID not set!")
if not CHANNEL_ID: raise ValueError("FATAL: CHANNEL_ID not set!")
if not DATABASE_URL: raise ValueError("FATAL: DATABASE_URL not set!")

try:
    ADMIN_ID = int(ADMIN_ID_STR)
except ValueError:
    raise ValueError("FATAL: ADMIN_ID must be an integer!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = None

# --- FSM States ---
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

# --- Database & Setup ---
async def setup_db():
    global db
    db = await asyncpg.create_pool(DATABASE_URL)
    async with db.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (id SERIAL PRIMARY KEY, text TEXT, user_id BIGINT, status VARCHAR(10) DEFAULT 'pending', message_id BIGINT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, categories TEXT[]);
            CREATE TABLE IF NOT EXISTS comments (id SERIAL PRIMARY KEY, confession_id INTEGER REFERENCES confessions(id), user_id BIGINT, text TEXT, sticker_file_id TEXT, animation_file_id TEXT, parent_comment_id INTEGER, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS user_status (user_id BIGINT PRIMARY KEY, has_accepted_rules BOOLEAN DEFAULT FALSE, is_blocked BOOLEAN DEFAULT FALSE);
            CREATE TABLE IF NOT EXISTS user_points (user_id BIGINT PRIMARY KEY, points INTEGER DEFAULT 0);
        """)

# --- [ALL OTHER FEATURES: Profiles, Reports, etc. REMAIN IN THE FULL VERSION] ---

# --- THE FIXED show_comments_for_confession ---
async def show_comments_for_confession(user_id: int, confession_id: int, message_to_edit: Optional[types.Message] = None, page: int = 1):
    async with db.acquire() as conn:
        conf_data = await conn.fetchrow("SELECT status, user_id FROM confessions WHERE id = $1", confession_id)
        if not conf_data or conf_data['status'] != 'approved':
            return
        
        owner_id = conf_data['user_id']
        total = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id) or 0
        
        if total == 0:
            await bot.send_message(user_id, "<i>No comments yet.</i>")
            return

        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        offset = (page - 1) * PAGE_SIZE
        comments = await conn.fetch("SELECT c.*, COALESCE(up.points, 0) as user_points FROM comments c LEFT JOIN user_points up ON c.user_id = up.user_id WHERE c.confession_id = $1 ORDER BY c.created_at ASC LIMIT $2 OFFSET $3", confession_id, PAGE_SIZE, offset)

        for i, c in enumerate(comments):
            seq = offset + i + 1
            commenter_uid = c['user_id']
            tag = "(Author)" if commenter_uid == owner_id else "(You)" if commenter_uid == user_id else "Anonymous"
            aura = f" 🏅{c['user_points']} Aura"
            
            # --- FIX APPLIED HERE ---
            admin_info = f" [UID: {commenter_uid}]" if int(user_id) == ADMIN_ID else ""
            
            meta = f"<i>#{seq} {tag}{aura}{admin_info}</i>"
            # [Rendering logic for stickers/text/replies follows...]
