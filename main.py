import logging
import asyncpg
import os
import asyncio
import re
import random
import string
from aiohttp import web 
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
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application 
from datetime import datetime, timedelta, timezone
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from typing import Optional, Tuple, Dict, Any, List, Callable
from aiogram.dispatcher.middlewares.base import BaseMiddleware

# --- Constants & Community Setup ---
CATEGORIES = [
    "Relationship", "Family", "School", "Friendship",
    "Religion", "Mental", "Addiction", "Harassment", "Crush", "Health", "Trauma", "Sexual Assault",
    "Other"
]
POINTS_PER_CONFESSION = 5
POINTS_PER_COMMENT = 2
POINTS_PER_REACTION_RECEIVED = 3

# Community Themed Days (0=Monday, 6=Sunday)
THEMED_DAYS = {
    0: ("#MentalHealthMonday", "Mental Health Monday", "Open up about stress, anxiety, burnout, healing, and self-care."),
    1: ("#CrushTuesday", "Crush Tuesday", "Secret campus crushes, missed connections, and unspoken feelings."),
    2: ("#WholesomeWednesday", "Wholesome Wednesday", "Random acts of kindness, daily gratitude, and heartwarming encounters."),
    3: ("#AcademicThursday", "Academic Thursday", "Exam fails, study struggles, imposter syndrome, and campus survival."),
    4: ("#FriendshipFriday", "Friendship Friday", "Friend group dynamics, unspoken distance, loyalty, and memories."),
    5: ("#SecretSaturday", "Secret Saturday", "The wildest, most guarded secrets you have never said out loud."),
    6: ("#LateNightThoughts", "Late Night Thoughts", "Existential musings, 3 AM reflections, and raw unfiltered feelings.")
}

# Irresistible & Low-Friction Daily Prompts
DAILY_PROMPTS = [
    "What's a secret you're keeping from your dorm roommate?",
    "That one encounter on campus you still think about at 3 AM.",
    "Academic admissions: What exam did you completely guess your way through?",
    "What's something you pretended to like just to impress someone?",
    "A moment when a stranger showed you unexpected kindness that you will never forget.",
    "What is the biggest misunderstanding someone has about who you really are?",
    "What is something you wish you could apologize for, but it's too late?",
    "What is an unspoken truth about student life at our university that nobody admits?",
    "Who is someone you silently miss every single day, and why can't you reach out?",
    "What was your most humbling experience this semester?",
    "🤫 በዩኒቨርሲቲ ላይ ማንም እንዲያውቅ የማትፈልገው ምስጢር ምንድነው?",
    "😂 በዩኒቨርሲቲ ውስጥ ያጋጠመህ በጣም አሳፋሪ ነገር ምንድነው?",
    "❤️ በMWU የምትወደው ሰው አለ? ለምን እንደምትወደው ንገረን።",
    "👀 በዩኒቨርሲቲ ላይ ለማድረግ የፈለግከው ነገር ግን ፈርተህ ያልሞከርከው ምንድነው?",
    "🥂 ለ2019 ራስህን ብቻ የምትሰጠው አንድ ቃል ወይም ተስፋ ምንድነው?",
    "👀 Nama tokkoof waan itti himuu barbaadde, garuu fuula dura itti himuu hin dandeenye maal dha?",
    "🫢 Yunivarsiitii kana keessatti namni ati dhoksaatti dinqisiifattu jiraa?",
    "🥂 Bara 2019f ofiif kee waadaa tokko yoo galtu, waadaan sun maal ta’a?"
]

# --- Dynamic Themes System Registry ---
THEMES = {
    "default": {
        "id": "default",
        "menu_label": "Default",
        "name": "Default (Daily Rotation)",
        "tag": "#MWUConfessions",
        "header_branding": "MWU Confession",
        "welcome_title": "Anonymous Confession Vault",
        "welcome_greeting": (
            "Here, students and peers share their deepest thoughts, hidden struggles, and untold campus stories with <b>100% cryptographic anonymity</b>."
        ),
        "description": "Speak your truth anonymously and connect with compassionate peers.",
        "pinned_categories": [],
        "reactions": {
            "notalone": {"emoji": "🫂", "label": "You're Not Alone"},
            "heard": {"emoji": "🕯️", "label": "Heard & Felt"},
            "support": {"emoji": "❤️", "label": "Support"}
        }
    },
    "enkutatash_2019": {
        "id": "enkutatash_2019",
        "menu_label": "🌼 Ethiopian New Year 2019 (Enkutatash)",
        "name": "Ethiopian New Year 2019 (Enkutatash)",
        "tag": "#Enkutatash2019 🌼",
        "header_branding": "🌼 MWU Confession | Enkutatash 2019 🌼",
        "welcome_title": "መልካም አዲስ ዓመት 2019! 🌼✨",
        "welcome_greeting": (
            "መልካም አዲስ ዓመት 2019! 🌼✨ As the golden Adey Abeba blooms across Ethiopia, may 2019 bring you peace, fresh starts, and forgiveness. "
            "Leave behind 2018's burdens, unspoken regrets, and silent tears. Share your truth, forgive, and embrace new beginnings with 100% cryptographic anonymity."
        ),
        "description": "መልካም አዲስ ዓመት 2019! Celebrate fresh starts, forgiveness, new beginnings, and 2018 reflections.",
        "pinned_categories": [
            "New Year Resolutions",
            "Forgiveness & Fresh Starts",
            "2018 Regrets & Lessons"
        ],
        "reactions": {
            "adey": {"emoji": "🌼", "label": "Adey Abeba / Blessings"},
            "fresh": {"emoji": "✨", "label": "Fresh Start"},
            "forgive": {"emoji": "🕊️", "label": "Forgiven"}
        }
    },
    "exam_survival": {
        "id": "exam_survival",
        "menu_label": "📚 Finals & Exam Survival",
        "name": "Finals & Exam Survival",
        "tag": "#ExamSurvival ☕📚",
        "header_branding": "📚 MWU Confession | Finals Week",
        "welcome_title": "Midterm & Finals Survival Sanctuary 📚☕",
        "welcome_greeting": (
            "Exam season stress is real. Whether you're pulling an all-nighter in the library, struggling with imposter syndrome, or completely lost in chapter 4, you are not alone."
        ),
        "description": "Midterm and final exam stress, caffeine confessions, library encounters, and study struggles.",
        "pinned_categories": [
            "Exam Stress",
            "Library Encounters",
            "Coffee & All-Nighters"
        ],
        "reactions": {
            "pass": {"emoji": "🎓", "label": "You Will Pass"},
            "coffee": {"emoji": "☕", "label": "Need Coffee"},
            "praying": {"emoji": "🙏", "label": "Prayers Up"}
        }
    },
    "freshman_welcoming": {
        "id": "freshman_welcoming",
        "menu_label": "🎒 Freshman Welcome & Campus Firsts",
        "name": "Freshman Welcome & Campus Firsts",
        "tag": "#MWUFreshman2019 🎒",
        "header_branding": "🎒 MWU Confession | Freshers",
        "welcome_title": "Welcome Freshmen to MWU! 🎒✨",
        "welcome_greeting": (
            "New to campus? Lost finding the lecture halls, homesick, or excited for the journey? Ask anything, confess your first impressions, and get advice from seniors."
        ),
        "description": "First impressions, homesickness, senior tips, dorm roommates, and campus navigation.",
        "pinned_categories": [
            "Freshman Struggles",
            "Dorm Life",
            "Senior Advice"
        ],
        "reactions": {
            "welcome": {"emoji": "👋", "label": "Welcome!"},
            "hangin": {"emoji": "💪", "label": "Stay Strong"},
            "home": {"emoji": "🏡", "label": "Homesick"}
        }
    },
    "mental_health_week": {
        "id": "mental_health_week",
        "menu_label": "💚 Mental Health & Empathy Awareness",
        "name": "Mental Health & Empathy Awareness",
        "tag": "#CampusMentalHealth 💚",
        "header_branding": "💚 MWU Confession | Empathy Sanctuary",
        "welcome_title": "Safe Space for Your Mind 💚",
        "welcome_greeting": (
            "No judgment. No toxicity. Share what is heavy on your heart today. Healing begins when we let ourselves be heard."
        ),
        "description": "A judgment-free haven to speak on burnout, anxiety, grief, loneliness, and emotional recovery.",
        "pinned_categories": [
            "Silent Battles",
            "Loneliness",
            "Small Wins"
        ],
        "reactions": {
            "heart": {"emoji": "💚", "label": "With You"},
            "candle": {"emoji": "🕯️", "label": "Heard"},
            "hug": {"emoji": "🫂", "label": "Gentle Hug"}
        }
    }
}

CURRENT_ACTIVE_THEME = "default"

def get_current_theme() -> dict:
    global CURRENT_ACTIVE_THEME
    return THEMES.get(CURRENT_ACTIVE_THEME, THEMES["default"])

def get_today_theme() -> Tuple[str, str, str]:
    theme = get_current_theme()
    if theme["id"] != "default":
        return theme["tag"], theme["name"], theme["description"]
    weekday = datetime.now(timezone.utc).weekday()
    return THEMED_DAYS.get(weekday, ("#MWUConfessions", "Daily Confessions", "Speak your truth anonymously."))

def get_today_prompt() -> str:
    now = datetime.now(timezone.utc)
    day_of_year = now.timetuple().tm_yday
    return DAILY_PROMPTS[day_of_year % len(DAILY_PROMPTS)]

MAX_CATEGORIES = 3
COOLDOWN_MINUTES = 3
AURA_TIERS = [
    (0, "🌱 Campus Seedling"),
    (20, "🤝 Supportive Peer"),
    (50, "🌟 Empathy Guide"),
    (100, "🛡️ Vault Guardian"),
    (250, "👑 Campus Luminary")
]

def get_aura_tier(points: int) -> str:
    tier = AURA_TIERS[0][1]
    for min_pts, title in AURA_TIERS:
        if points >= min_pts:
            tier = title
        else:
            break
    return tier

COMMUNITY_RULES_TEXT = (
    "<b>MWU Confessions Vault — Community & Safety Rules</b> 🛡️\n\n"
    "To protect our campus sanctuary, all confessions and comments must follow these zero-tolerance rules:\n\n"
    "1. <b>Zero Doxxing:</b> Never post real names, phone numbers, social media handles, dorm room numbers, or identifying details of anyone.\n"
    "2. <b>Zero Harassment & Hate:</b> Defamation, bullying, hate speech, and revenge posts are permanently prohibited.\n"
    "3. <b>True Cryptographic Anonymity:</b> Your identity is strictly anonymous and never posted to the channel.\n"
    "4. <b>Kindness First:</b> Offer empathy and constructive support to peers who are hurting.\n\n"
    "Violations lead to immediate automated or administrator bans."
)

HELP_TEXT = (
    "<b>MWU Confessions & Music Bot — Help & Commands</b> 🧭\n\n"
    "<b>Member Commands:</b>\n"
    "• /start — Welcome vault entrance & daily theme\n"
    "• /confess — Submit an anonymous confession\n"
    "• /music — 🎵 Dedicate a song anonymously to your crush or channel\n"
    "• /prompt — View today's reflection prompt\n"
    "• /profile — Check your Aura points & badges\n"
    "• /leaderboard — View top supportive peers\n"
    "• /rules — Read the zero-doxxing safety rules\n"
    "• /cancel — Cancel any active submission\n\n"
    "<b>Admin Commands:</b>\n"
    "• /adminmusic — 🎵 Music Library & Dedications Moderation\n"
    "• /settheme — Switch community theme (Enkutatash 2019, Finals, etc.)\n"
    "• /postprompt — Broadcast today's prompt to the channel\n"
    "• /warn, /block, /unblock — Moderation controls"
)

# --- Environment Configuration ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "15"))
DATABASE_URL = os.getenv("DATABASE_URL")
HTTP_PORT_STR = os.getenv("PORT")

if not BOT_TOKEN:
    BOT_TOKEN = "MOCK_TOKEN_CONFIG_REQUIRED"
    logging.warning("BOT_TOKEN not provided in environment. Please set BOT_TOKEN in .env")

if not ADMIN_ID_STR:
    ADMIN_ID = 0
    logging.warning("ADMIN_ID not provided in environment. Please set ADMIN_ID in .env")
else:
    try:
        ADMIN_ID = int(ADMIN_ID_STR)
    except ValueError:
        ADMIN_ID = 0

CHANNEL_ID = CHANNEL_ID_RAW or "@channel"
try:
    CHANNEL_ID = int(CHANNEL_ID)
except (ValueError, TypeError):
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(
    token=BOT_TOKEN if BOT_TOKEN != "MOCK_TOKEN_CONFIG_REQUIRED" else "123456:DummyTokenForCheck",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
bot_info: Optional[types.User] = None

# ==========================================
# DATABASE HELPER FUNCTIONS (MUSIC & CONFESSIONS)
# ==========================================
db: Optional[asyncpg.Pool] = None

async def create_db_pool():
    if not DATABASE_URL:
        logging.warning("DATABASE_URL not set.")
        return None
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        logging.info("Database pool created successfully.")
        return pool
    except Exception as e:
        logging.error(f"Failed to create database pool: {e}")
        return None

# --- Music Database Operations ---
async def setup_music_tables(conn: asyncpg.Connection):
    """Creates tables for Music Library and User Music Dedications."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS music_library (
            id SERIAL PRIMARY KEY,
            telegram_file_id TEXT NOT NULL,
            title TEXT NOT NULL,
            caption TEXT NULL,
            created_by BIGINT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            posted_count INT DEFAULT 0,
            last_posted_at TIMESTAMP WITH TIME ZONE NULL
        );
        CREATE INDEX IF NOT EXISTS idx_music_library_created_at ON music_library(created_at DESC);
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS music_submissions (
            id SERIAL PRIMARY KEY,
            submission_code VARCHAR(20) UNIQUE NOT NULL,
            user_id BIGINT NOT NULL,
            telegram_file_id TEXT NOT NULL,
            title TEXT NOT NULL,
            recipient_type VARCHAR(50) NOT NULL,
            recipient_text TEXT NOT NULL,
            dedication_message TEXT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            channel_message_id BIGINT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP WITH TIME ZONE NULL,
            rejection_reason TEXT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_music_submissions_status ON music_submissions(status);
        CREATE INDEX IF NOT EXISTS idx_music_submissions_code ON music_submissions(submission_code);
    """)
    logging.info("Music tables checked/created.")

async def insert_music_to_library(conn: asyncpg.Connection, file_id: str, title: str, caption: Optional[str], admin_id: int) -> int:
    return await conn.fetchval("""
        INSERT INTO music_library (telegram_file_id, title, caption, created_by)
        VALUES ($1, $2, $3, $4)
        RETURNING id
    """, file_id, title, caption, admin_id)

async def increment_music_posted_count(conn: asyncpg.Connection, music_id: int):
    await conn.execute("""
        UPDATE music_library 
        SET posted_count = posted_count + 1, last_posted_at = CURRENT_TIMESTAMP 
        WHERE id = $1
    """, music_id)

async def get_music_library_page(conn: asyncpg.Connection, limit: int = 5, offset: int = 0) -> List[asyncpg.Record]:
    return await conn.fetch("""
        SELECT id, telegram_file_id, title, caption, created_at, posted_count 
        FROM music_library 
        ORDER BY created_at DESC 
        LIMIT $1 OFFSET $2
    """, limit, offset)

async def count_music_library(conn: asyncpg.Connection) -> int:
    val = await conn.fetchval("SELECT COUNT(*) FROM music_library")
    return val or 0

async def get_music_by_id(conn: asyncpg.Connection, music_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM music_library WHERE id = $1", music_id)

async def delete_music_by_id(conn: asyncpg.Connection, music_id: int) -> bool:
    res = await conn.execute("DELETE FROM music_library WHERE id = $1", music_id)
    return res == "DELETE 1"

async def create_music_submission(
    conn: asyncpg.Connection,
    code: str,
    user_id: int,
    file_id: str,
    title: str,
    recipient_type: str,
    recipient_text: str,
    dedication_message: Optional[str]
) -> int:
    return await conn.fetchval("""
        INSERT INTO music_submissions (
            submission_code, user_id, telegram_file_id, title,
            recipient_type, recipient_text, dedication_message, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
        RETURNING id
    """, code, user_id, file_id, title, recipient_type, recipient_text, dedication_message)

async def get_music_submission_by_id(conn: asyncpg.Connection, sub_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM music_submissions WHERE id = $1", sub_id)

async def get_pending_submissions(conn: asyncpg.Connection, limit: int = 5, offset: int = 0) -> List[asyncpg.Record]:
    return await conn.fetch("""
        SELECT id, submission_code, user_id, telegram_file_id, title, recipient_type, recipient_text, dedication_message, created_at
        FROM music_submissions
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT $1 OFFSET $2
    """, limit, offset)

async def count_pending_submissions(conn: asyncpg.Connection) -> int:
    val = await conn.fetchval("SELECT COUNT(*) FROM music_submissions WHERE status = 'pending'")
    return val or 0

async def update_submission_status(
    conn: asyncpg.Connection,
    sub_id: int,
    status: str,
    channel_msg_id: Optional[int] = None,
    rejection_reason: Optional[str] = None
):
    await conn.execute("""
        UPDATE music_submissions 
        SET status = $1, channel_message_id = $2, rejection_reason = $3, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = $4
    """, status, channel_msg_id, rejection_reason, sub_id)

# ==========================================
# CONFESSIONS & COMMUNITY DATABASE SETUP
# ==========================================
async def setup():
    global db, bot_info
    db = await create_db_pool()
    if BOT_TOKEN != "MOCK_TOKEN_CONFIG_REQUIRED":
        try:
            bot_info = await bot.get_me()
            logging.info(f"Bot started: @{bot_info.username}")
        except Exception as e:
            logging.error(f"Could not connect to Telegram Bot API: {e}")

    if not db:
        logging.warning("Skipping DB setup because db connection pool is not available.")
        return

    async with db.acquire() as conn:
        # Confessions Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                message_id BIGINT,
                photo_file_id TEXT NULL,
                prompt_text TEXT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                rejection_reason TEXT NULL,
                categories TEXT[] NULL
            );
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='confessions' AND column_name='prompt_text') THEN
                    ALTER TABLE confessions ADD COLUMN prompt_text TEXT NULL;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='confessions' AND column_name='photo_file_id') THEN
                    ALTER TABLE confessions ADD COLUMN photo_file_id TEXT NULL;
                END IF;
            END $$;
        """)

        # Comments Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                text TEXT NULL,
                sticker_file_id TEXT NULL,
                animation_file_id TEXT NULL,
                parent_comment_id INTEGER REFERENCES comments(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_comments_confession_id ON comments(confession_id);
        """)

        # Reactions Table
        await conn.execute("""
             CREATE TABLE IF NOT EXISTS reactions (
                 id SERIAL PRIMARY KEY,
                 comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
                 user_id BIGINT NOT NULL,
                 reaction_type VARCHAR(10) NOT NULL,
                 created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                 UNIQUE(comment_id, user_id)
             );
        """)

        # Contact Requests Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_requests (
                id SERIAL PRIMARY KEY,
                confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
                comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
                requester_user_id BIGINT NOT NULL,
                requested_user_id BIGINT NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (comment_id, requester_user_id)
            );
        """)

        # User Points Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                user_id BIGINT PRIMARY KEY,
                points INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_user_points_user_id ON user_points(user_id);
        """)

        # Reports Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
                reporter_user_id BIGINT NOT NULL,
                reported_user_id BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (comment_id, reporter_user_id)
            );
        """)

        # Deletion Requests Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS deletion_requests (
                id SERIAL PRIMARY KEY,
                confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP WITH TIME ZONE,
                UNIQUE (confession_id, user_id)
            );
        """)

        # User Status Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_status (
                user_id BIGINT PRIMARY KEY,
                has_accepted_rules BOOLEAN NOT NULL DEFAULT FALSE,
                is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                blocked_until TIMESTAMP WITH TIME ZONE NULL,
                block_reason TEXT NULL
            );
        """)

        # System Config Table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key VARCHAR(50) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO system_config (key, value) VALUES ('active_theme', 'default')
            ON CONFLICT (key) DO NOTHING;
        """)

        # Setup Music Tables (Music Library & User Dedications)
        await setup_music_tables(conn)

        # Load persisted theme
        stored_theme = await conn.fetchval("SELECT value FROM system_config WHERE key = 'active_theme'")
        if stored_theme and stored_theme in THEMES:
            global CURRENT_ACTIVE_THEME
            CURRENT_ACTIVE_THEME = stored_theme
            logging.info(f"Loaded active theme: {CURRENT_ACTIVE_THEME}")

# ==========================================
# CONFESSION FORMS & MIDDLEWARE
# ==========================================
class ConfessionForm(StatesGroup):
    selecting_categories = State()
    writing_confession = State()

class RulesConsentForm(StatesGroup):
    pending_consent = State()

class BlockUserMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[types.TelegramObject, Dict[str, Any]], Any], event: types.TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if not user or not db:
            return await handler(event, data)

        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT is_blocked, blocked_until, block_reason FROM user_status WHERE user_id = $1", user.id)
            if row and row['is_blocked']:
                blocked_until = row['blocked_until']
                now = datetime.now(timezone.utc)
                if blocked_until and now > blocked_until:
                    await conn.execute("UPDATE user_status SET is_blocked = FALSE, blocked_until = NULL, block_reason = NULL WHERE user_id = $1", user.id)
                else:
                    reason = row['block_reason'] or "Community guidelines violation"
                    time_msg = f" until {blocked_until.strftime('%Y-%m-%d %H:%M UTC')}" if blocked_until else " indefinitely"
                    blocked_text = f"🚫 <b>Access Restricted:</b> Your account is currently suspended{time_msg}.\n\n<b>Reason:</b> {reason}"
                    if isinstance(event, types.Message):
                        await event.answer(blocked_text)
                    elif isinstance(event, types.CallbackQuery):
                        await event.answer(f"Suspended: {reason}", show_alert=True)
                    return
        return await handler(event, data)

async def award_points(user_id: int, points: int):
    if not db or points <= 0:
        return
    try:
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_points (user_id, points) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET points = user_points.points + $2
            """, user_id, points)
    except Exception as e:
        logging.error(f"Error awarding points: {e}")

async def safe_send_message(user_id: int, text: str, **kwargs):
    try:
        await bot.send_message(user_id, text, **kwargs)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logging.warning(f"Could not send message to user {user_id}: {e}")

def create_category_keyboard(selected_cats: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    theme = get_current_theme()
    pinned = theme.get("pinned_categories", [])
    
    for cat in pinned:
        prefix = "✅ " if cat in selected_cats else "⭐ "
        builder.button(text=f"{prefix}{cat}", callback_data=f"cat_{cat}")
        
    for cat in CATEGORIES:
        if cat in pinned:
            continue
        prefix = "✅ " if cat in selected_cats else ""
        builder.button(text=f"{prefix}{cat}", callback_data=f"cat_{cat}")
        
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="✨ Done Selecting", callback_data="cat_done"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")
    )
    return builder.as_markup()

# ==========================================
# MUSIC SYSTEM: STATES, KEYBOARDS & CODE GENERATOR
# ==========================================
class UserMusicDedicationForm(StatesGroup):
    waiting_for_audio = State()
    selecting_recipient = State()
    waiting_for_custom_recipient = State()
    waiting_for_message = State()
    confirming_submission = State()

class AdminMusicForm(StatesGroup):
    waiting_for_audio = State()
    waiting_for_title = State()
    waiting_for_caption = State()

def generate_submission_code() -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=5))
    return f"M{suffix}"

def get_user_music_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💌 Dedicate a Song", callback_data="user_music_dedicate")
    builder.button(text="❌ Back to Main", callback_data="user_music_back_home")
    builder.adjust(1)
    return builder.as_markup()

def get_recipient_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❤️ My Crush", callback_data="recip_crush")
    builder.button(text="💕 Someone Special", callback_data="recip_special")
    builder.button(text="👥 Everyone / Members", callback_data="recip_everyone")
    builder.button(text="✍️ Custom", callback_data="recip_custom")
    builder.button(text="❌ Cancel", callback_data="music_cancel")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def get_admin_music_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Add Music", callback_data="admin_music_add")
    builder.button(text="📢 Post Music", callback_data="admin_music_library_1")
    builder.button(text="📋 Music Library", callback_data="admin_music_library_1")
    builder.button(text="📨 Pending Dedications", callback_data="admin_music_pending_1")
    builder.button(text="❌ Close", callback_data="admin_music_close")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

# ==========================================
# CONFESSIONS & COMMUNITY HANDLERS
# ==========================================
@dp.message(Command("start"))
async def send_welcome(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    theme = get_current_theme()
    tag, theme_title, theme_desc = get_today_theme()
    today_prompt = get_today_prompt()

    has_consent = True
    if db:
        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT has_accepted_rules FROM user_status WHERE user_id = $1", user_id)
            if not row or not row['has_accepted_rules']:
                has_consent = False

    if not has_consent:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ I Agree to Zero Doxxing & Rules", callback_data="accept_rules_consent")
        await message.answer(
            f"<b>Welcome to {html.quote(theme['header_branding'])}!</b> 🛡️\n\n"
            f"{COMMUNITY_RULES_TEXT}\n\n"
            "Please confirm agreement before submitting or viewing confessions:",
            reply_markup=builder.as_markup()
        )
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Write Anonymous Confession", callback_data="start_confess_button")
    builder.button(text="🎵 Music Dedication", callback_data="user_music_dedicate")
    builder.button(text="💡 Respond to Today's Prompt", callback_data="prompt_respond_button")
    builder.button(text="🌟 My Profile & Aura", callback_data="view_profile_button")
    builder.button(text="🏆 Leaderboard", callback_data="view_leaderboard_button")
    builder.adjust(1, 1, 1, 2)

    await message.answer(
        f"<b>{html.quote(theme['welcome_title'])}</b>\n\n"
        f"{theme['welcome_greeting']}\n\n"
        f"📅 <b>Current Theme:</b> <b>{html.quote(theme_title)}</b> (<code>{html.quote(tag)}</code>)\n"
        f"<i>{html.quote(theme_desc)}</i>\n\n"
        f"💡 <b>Today's Campus Reflection:</b>\n"
        f"<i>\"{html.quote(today_prompt)}\"</i>\n\n"
        "Tap below to share your story or dedicate a song anonymously:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "accept_rules_consent")
async def accept_rules_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if db:
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_status (user_id, has_accepted_rules) VALUES ($1, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET has_accepted_rules = TRUE
            """, user_id)
    await callback_query.answer("Rules accepted! Welcome to the sanctuary.")
    await send_welcome(callback_query.message, state)

@dp.message(Command("rules"))
async def cmd_rules(message: types.Message):
    await message.answer(COMMUNITY_RULES_TEXT)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT)

@dp.message(Command("prompt"))
async def cmd_prompt(message: types.Message, state: FSMContext):
    today_prompt = get_today_prompt()
    tag, theme_title, _ = get_today_theme()
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Answer Anonymously", callback_data="prompt_respond_button")
    await message.answer(
        f"💡 <b>Today's Campus Reflection Prompt</b>\n"
        f"Theme: <b>{html.quote(theme_title)}</b> ({tag})\n\n"
        f"<i>\"{html.quote(today_prompt)}\"</i>\n\n"
        "Would you like to share your anonymous answer with the channel?",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "prompt_respond_button")
async def cb_prompt_respond(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    today_prompt = get_today_prompt()
    await state.update_data(active_prompt=today_prompt, selected_categories=["Other"])
    await state.set_state(ConfessionForm.writing_confession)
    await callback_query.message.answer(
        f"💡 <b>Responding to Daily Prompt:</b>\n<i>\"{html.quote(today_prompt)}\"</i>\n\n"
        "Please send your confession text below (or attach a single photo with your text as caption).\n"
        "<i>Send /cancel to stop.</i>"
    )

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    await show_profile(message.from_user.id, message)

@dp.callback_query(F.data == "view_profile_button")
async def cb_view_profile(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await show_profile(callback_query.from_user.id, callback_query.message)

async def show_profile(user_id: int, message_or_event):
    points = 0
    conf_count = 0
    comm_count = 0
    if db:
        async with db.acquire() as conn:
            pts = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", user_id)
            points = pts or 0
            conf_count = await conn.fetchval("SELECT COUNT(*) FROM confessions WHERE user_id = $1", user_id) or 0
            comm_count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE user_id = $1", user_id) or 0

    tier = get_aura_tier(points)
    text = (
        f"👤 <b>Your Campus Aura &amp; Profile</b>\n\n"
        f"🎖️ <b>Rank &amp; Title:</b> {tier}\n"
        f"✨ <b>Community Aura:</b> <code>{points} pts</code>\n\n"
        f"📝 <b>Confessions Shared:</b> {conf_count}\n"
        f"💬 <b>Supportive Comments:</b> {comm_count}\n\n"
        f"<i>Earn Aura points by sharing courageous confessions (+{POINTS_PER_CONFESSION}), "
        f"offering empathetic comments (+{POINTS_PER_COMMENT}), and receiving reactions (+{POINTS_PER_REACTION_RECEIVED})!</i>"
    )
    if isinstance(message_or_event, types.Message):
        await message_or_event.answer(text)

@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message):
    await show_leaderboard(message)

@dp.callback_query(F.data == "view_leaderboard_button")
async def cb_view_leaderboard(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await show_leaderboard(callback_query.message)

async def show_leaderboard(message: types.Message):
    if not db:
        await message.answer("Leaderboard currently unavailable.")
        return

    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, points FROM user_points ORDER BY points DESC LIMIT 10")

    if not rows:
        await message.answer("🏆 <b>Sanctuary Leaderboard</b>\n\nNo points recorded yet. Be the first to earn Aura!")
        return

    lines = ["🏆 <b>Top Supportive Campus Guardians</b>\n"]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < len(medals) else "👤"
        tier = get_aura_tier(r['points'])
        anon_id = str(r['user_id'])[-4:]
        lines.append(f"{medal} <b>Peer #{anon_id}</b> — {r['points']} pts • <i>{tier}</i>")

    lines.append("\n<i>All identities are fully anonymized to protect student privacy.</i>")
    await message.answer("\n".join(lines))

# --- Confession Submission Flow ---
@dp.message(Command("confess"))
async def start_confession(message: types.Message, state: FSMContext):
    await state.clear()
    tag, theme_title, theme_desc = get_today_theme()
    await state.update_data(selected_categories=[], active_prompt=None)
    await message.answer(
        f"📝 <b>New Anonymous Confession</b>\n\n"
        f"📅 Today's Community Theme is <b>{theme_title}</b> ({tag}).\n"
        f"<i>{theme_desc}</i>\n\n"
        f"Select 1 to {MAX_CATEGORIES} categories, then tap <b>'Done Selecting'</b>:",
        reply_markup=create_category_keyboard([])
    )
    await state.set_state(ConfessionForm.selecting_categories)

@dp.callback_query(F.data == "start_confess_button")
async def start_confess_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await start_confession(callback_query.message, state)

@dp.callback_query(ConfessionForm.selecting_categories, F.data.startswith("cat_"))
async def handle_category_selection(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_cats = data.get("selected_categories", [])
    choice = callback_query.data.replace("cat_", "")

    if choice == "done":
        if not selected_cats:
            await callback_query.answer("Please pick at least one category.", show_alert=True)
            return
        await state.set_state(ConfessionForm.writing_confession)
        await callback_query.message.edit_text(
            f"🏷️ <b>Categories Selected:</b> {', '.join(selected_cats)}\n\n"
            "Please write your confession below (or upload a photo with caption):\n"
            "<i>Your identity remains 100% confidential. Send /cancel to stop.</i>"
        )
        return

    if choice in selected_cats:
        selected_cats.remove(choice)
    else:
        if len(selected_cats) >= MAX_CATEGORIES:
            await callback_query.answer(f"Maximum {MAX_CATEGORIES} categories allowed.", show_alert=True)
            return
        selected_cats.append(choice)

    await state.update_data(selected_categories=selected_cats)
    try:
        await callback_query.message.edit_reply_markup(reply_markup=create_category_keyboard(selected_cats))
    except TelegramBadRequest:
        pass
    await callback_query.answer()

@dp.message(ConfessionForm.writing_confession, F.photo | F.text)
async def process_confession_content(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        await message.answer("Confession cancelled.")
        return

    data = await state.get_data()
    selected_cats = data.get("selected_categories", ["Other"])
    active_prompt = data.get("active_prompt")
    user_id = message.from_user.id

    text = message.caption or message.text or ""
    if len(text.strip()) < 5:
        await message.answer("Please write at least a few words for your confession.")
        return

    photo_id = message.photo[-1].file_id if message.photo else None

    # Anti-doxxing pattern check (phone numbers, full handles)
    if re.search(r'\b(?:\+?251|0)?9\d{8}\b', text) or re.search(r'@\w{4,}', text):
        await message.answer(
            "⚠️ <b>Privacy Warning:</b> Your submission appears to contain a phone number or handle. "
            "Please remove all identifying information to protect community safety and resend."
        )
        return

    if db:
        async with db.acquire() as conn:
            conf_id = await conn.fetchval("""
                INSERT INTO confessions (text, user_id, status, photo_file_id, prompt_text, categories)
                VALUES ($1, $2, 'pending', $3, $4, $5)
                RETURNING id
            """, text, user_id, photo_id, active_prompt, selected_cats)
    else:
        conf_id = 999

    await award_points(user_id, POINTS_PER_CONFESSION)
    await state.clear()

    await message.answer(
        f"🕊️ <b>Confession #{conf_id} Submitted Successfully!</b>\n\n"
        f"🏷️ Categories: <code>{', '.join(selected_cats)}</code>\n"
        f"✨ You earned <b>+{POINTS_PER_CONFESSION} Aura points</b> for your courage.\n\n"
        "Your post is awaiting admin approval before being broadcasted to the channel."
    )

    # Admin Alert
    if ADMIN_ID and bot_info:
        admin_text = (
            f"🛡️ <b>NEW CONFESSION #{conf_id} AWAITING APPROVAL</b>\n\n"
            f"<b>Categories:</b> {', '.join(selected_cats)}\n"
            f"<b>Prompt:</b> {html.quote(active_prompt) if active_prompt else 'None'}\n\n"
            f"<b>Content:</b>\n{html.quote(text)}"
        )
        mod_builder = InlineKeyboardBuilder()
        mod_builder.button(text="✅ Approve", callback_data=f"adm_appr_conf_{conf_id}")
        mod_builder.button(text="❌ Reject", callback_data=f"adm_rej_conf_{conf_id}")
        mod_builder.adjust(2)
        try:
            if photo_id:
                await bot.send_photo(ADMIN_ID, photo=photo_id, caption=admin_text, reply_markup=mod_builder.as_markup())
            else:
                await bot.send_message(ADMIN_ID, text=admin_text, reply_markup=mod_builder.as_markup())
        except Exception as e:
            logging.error(f"Failed to send confession #{conf_id} to admin: {e}")

@dp.callback_query(F.data.startswith("adm_appr_conf_"))
async def handle_admin_approve_conf(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("Unauthorized.", show_alert=True)
        return

    conf_id = int(callback_query.data.split("_")[-1])
    if not db:
        return

    async with db.acquire() as conn:
        conf = await conn.fetchrow("SELECT * FROM confessions WHERE id = $1", conf_id)
        if not conf or conf['status'] != 'pending':
            await callback_query.answer("Already processed.")
            return

        tag, theme_title, _ = get_today_theme()
        cats = " ".join([f"#{c.replace(' ', '')}" for c in (conf['categories'] or [])])
        channel_post = (
            f"📝 <b>Confession #{conf_id}</b>\n\n"
            f"{html.quote(conf['text'])}\n\n"
            f"{cats} {tag}"
        )

        try:
            if conf['photo_file_id']:
                c_msg = await bot.send_photo(CHANNEL_ID, photo=conf['photo_file_id'], caption=channel_post)
            else:
                c_msg = await bot.send_message(CHANNEL_ID, text=channel_post)

            await conn.execute("UPDATE confessions SET status = 'approved', message_id = $1 WHERE id = $2", c_msg.message_id, conf_id)
            await callback_query.answer("Approved and broadcasted!")
            await safe_send_message(conf['user_id'], f"🎉 <b>Your confession #{conf_id} was approved and posted to the channel!</b>")
        except Exception as e:
            logging.error(f"Failed to post confession #{conf_id} to channel: {e}")
            await callback_query.answer("Error posting to channel.", show_alert=True)

@dp.callback_query(F.data.startswith("adm_rej_conf_"))
async def handle_admin_reject_conf(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("Unauthorized.", show_alert=True)
        return

    conf_id = int(callback_query.data.split("_")[-1])
    if db:
        async with db.acquire() as conn:
            conf = await conn.fetchrow("SELECT user_id FROM confessions WHERE id = $1", conf_id)
            await conn.execute("UPDATE confessions SET status = 'rejected' WHERE id = $1", conf_id)
            if conf:
                await safe_send_message(conf['user_id'], f"❌ <b>Your confession #{conf_id} was not approved for publication.</b>")
    await callback_query.answer("Rejected.")

@dp.callback_query(F.data == "cancel_action")
async def cancel_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_query.message.edit_text("Action cancelled.")
    await callback_query.answer()

@dp.message(Command("cancel"), StateFilter('*'))
async def cancel_any_state(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Action cancelled.", reply_markup=ReplyKeyboardRemove())

# ==========================================
# MUSIC SYSTEM HANDLERS
# ==========================================
def register_music_handlers():
    """Registers all User and Admin Music handlers onto the Dispatcher."""

    def is_admin(user_id: int) -> bool:
        return user_id == ADMIN_ID

    # --- User Flow: /music ---
    @dp.message(F.text == "/music")
    async def cmd_music(message: types.Message, state: FSMContext):
        await state.clear()
        text = (
            "🎵 <b>Music Dedication &amp; Invitation Sanctuary</b>\n\n"
            "Share your favorite song and dedicate it anonymously to your campus crush, a special friend, "
            "or the entire community.\n\n"
            "✨ <b>How it works:</b>\n"
            "1. Upload your audio file\n"
            "2. Choose who it is for\n"
            "3. Add a heartfelt anonymous message\n"
            "4. Reviewed by admin &amp; broadcast directly to the channel with Telegram's native audio player ▶️\n\n"
            "🔒 <i>Your identity is 100% cryptographic and never exposed.</i>"
        )
        await message.answer(text, reply_markup=get_user_music_menu())

    @dp.callback_query(F.data == "user_music_menu_open")
    async def cb_user_music_menu(callback_query: types.CallbackQuery, state: FSMContext):
        await state.clear()
        text = (
            "🎵 <b>Music Dedication &amp; Invitation</b>\n\n"
            "Send a song anonymously to someone special or the entire channel!\n\n"
            "Select an option below:"
        )
        try:
            await callback_query.message.edit_text(text, reply_markup=get_user_music_menu())
        except TelegramBadRequest:
            await callback_query.message.answer(text, reply_markup=get_user_music_menu())
        await callback_query.answer()

    @dp.callback_query(F.data == "user_music_back_home")
    async def cb_music_back_home(callback_query: types.CallbackQuery, state: FSMContext):
        await state.clear()
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.answer("Returned.")

    @dp.callback_query(F.data == "user_music_dedicate")
    async def cb_start_dedication(callback_query: types.CallbackQuery, state: FSMContext):
        await state.set_state(UserMusicDedicationForm.waiting_for_audio)
        text = (
            "🎵 <b>Step 1/3: Send Audio File</b>\n\n"
            "Please send the song you would like to dedicate as a <b>Telegram Audio</b> file (MP3, M4A, FLAC, AAC, etc.).\n\n"
            "💡 <i>Tip: Forwarding or uploading from Telegram Music channels or your device works seamlessly!</i>\n\n"
            "Type /cancel at any time to abort."
        )
        await callback_query.message.answer(text)
        await callback_query.answer()

    @dp.message(UserMusicDedicationForm.waiting_for_audio, F.audio)
    async def receive_user_audio(message: types.Message, state: FSMContext):
        audio = message.audio
        file_id = audio.file_id
        title = audio.title or audio.file_name or "Untitled Audio"
        if audio.performer:
            title = f"{audio.performer} - {title}"

        await state.update_data(
            audio_file_id=file_id,
            audio_title=title,
            audio_duration=audio.duration
        )
        await state.set_state(UserMusicDedicationForm.selecting_recipient)

        text = (
            f"🎵 <b>Song Selected:</b> <i>{html.quote(title)}</i>\n\n"
            "💌 <b>Step 2/3: Who is this song dedicated to?</b>\n"
            "Choose a recipient category or enter a custom one:"
        )
        await message.answer(text, reply_markup=get_recipient_keyboard())

    @dp.message(UserMusicDedicationForm.waiting_for_audio)
    async def receive_wrong_file_for_audio(message: types.Message):
        if message.text and message.text.startswith('/cancel'):
            return
        await message.answer(
            "⚠️ <b>Invalid format:</b> Please send an <b>Audio file</b> (music track).\n"
            "Voice notes or images cannot be used for channel music. Try forwarding an MP3 or uploading a song file, or type /cancel."
        )

    @dp.callback_query(UserMusicDedicationForm.selecting_recipient, F.data.startswith("recip_"))
    async def handle_recipient_selection(callback_query: types.CallbackQuery, state: FSMContext):
        choice = callback_query.data.replace("recip_", "")
        recipient_map = {
            "crush": ("crush", "❤️ My Crush"),
            "special": ("someone_special", "💕 Someone Special"),
            "everyone": ("everyone", "👥 Everyone / Members"),
        }

        if choice in recipient_map:
            rtype, rtext = recipient_map[choice]
            await state.update_data(recipient_type=rtype, recipient_text=rtext)
            await state.set_state(UserMusicDedicationForm.waiting_for_message)
            await callback_query.message.edit_text(
                f"💌 <b>Recipient:</b> {rtext}\n\n"
                "📝 <b>Step 3/3: Optional Dedication Message</b>\n\n"
                "Write a heartfelt message, confession, or dedication note to accompany the song.\n\n"
                "<i>Type your message below, or send /skip to leave it without a caption:</i>",
                reply_markup=None
            )
            await callback_query.answer()
        elif choice == "custom":
            await state.set_state(UserMusicDedicationForm.waiting_for_custom_recipient)
            await callback_query.message.edit_text(
                "✍️ <b>Custom Recipient</b>\n\n"
                "Please type who this dedication is for (e.g. <i>'The girl in the library with the yellow notebook'</i>, <i>'Dorm Room 12'</i>):\n\n"
                "<i>Remember: Do NOT include real full names or private phone numbers!</i>",
                reply_markup=None
            )
            await callback_query.answer()

    @dp.message(UserMusicDedicationForm.waiting_for_custom_recipient, F.text)
    async def receive_custom_recipient(message: types.Message, state: FSMContext):
        if message.text.startswith("/cancel"):
            return
        custom_text = message.text.strip()
        if len(custom_text) < 2:
            await message.answer("Please enter at least 2 characters for the recipient.")
            return
        if len(custom_text) > 100:
            await message.answer("Recipient description is too long (max 100 characters).")
            return

        formatted_recipient = f"💌 {custom_text}"
        await state.update_data(recipient_type="custom", recipient_text=formatted_recipient)
        await state.set_state(UserMusicDedicationForm.waiting_for_message)

        await message.answer(
            f"💌 <b>Recipient:</b> {html.quote(formatted_recipient)}\n\n"
            "📝 <b>Step 3/3: Optional Dedication Message</b>\n\n"
            "Write a heartfelt message, confession, or dedication note to accompany the song.\n\n"
            "<i>Type your message below, or send /skip to proceed without a message:</i>"
        )

    @dp.message(UserMusicDedicationForm.waiting_for_message, F.text)
    async def receive_dedication_message(message: types.Message, state: FSMContext):
        if message.text.startswith("/cancel"):
            return

        msg_text = None
        if not message.text.startswith("/skip"):
            msg_text = message.text.strip()
            if len(msg_text) > 800:
                await message.answer("Message is too long (max 800 characters). Please send a shorter message or /skip.")
                return

        await state.update_data(dedication_message=msg_text)
        await state.set_state(UserMusicDedicationForm.confirming_submission)

        data = await state.get_data()
        song_title = data.get("audio_title", "Untitled Song")
        recip = data.get("recipient_text", "Someone Special")
        user_msg = data.get("dedication_message")
        msg_display = f'"{html.quote(user_msg)}"' if user_msg else "<i>None (Audio only)</i>"

        confirm_text = (
            "✨ <b>Confirm Your Music Dedication</b>\n\n"
            f"🎵 <b>Song:</b> {html.quote(song_title)}\n"
            f"💌 <b>For:</b> {html.quote(recip)}\n"
            f"💬 <b>Message:</b> {msg_display}\n\n"
            "🔒 <b>Privacy Guarantee:</b>\n"
            "• You remain 100% anonymous.\n"
            "• Your Telegram username and ID are NEVER exposed.\n"
            "• Will be submitted to admin for moderation before publishing.\n\n"
            "Ready to submit?"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Submit Dedication", callback_data="music_confirm_yes")
        builder.button(text="❌ Cancel", callback_data="music_cancel")
        builder.adjust(1, 1)

        await message.answer(confirm_text, reply_markup=builder.as_markup())

    @dp.callback_query(UserMusicDedicationForm.confirming_submission, F.data == "music_confirm_yes")
    async def submit_music_dedication(callback_query: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = callback_query.from_user.id
        file_id = data.get("audio_file_id")
        song_title = data.get("audio_title", "Untitled Song")
        rtype = data.get("recipient_type", "custom")
        rtext = data.get("recipient_text", "Someone Special")
        ded_msg = data.get("dedication_message")

        if not file_id:
            await callback_query.answer("Session expired. Please try again with /music.", show_alert=True)
            await state.clear()
            return

        sub_code = generate_submission_code()

        try:
            if db:
                async with db.acquire() as conn:
                    sub_id = await create_music_submission(
                        conn=conn,
                        code=sub_code,
                        user_id=user_id,
                        file_id=file_id,
                        title=song_title,
                        recipient_type=rtype,
                        recipient_text=rtext,
                        dedication_message=ded_msg
                    )
            else:
                sub_id = 101

            # Notify user
            await callback_query.message.edit_text(
                f"🎉 <b>Dedication Submitted Successfully!</b>\n\n"
                f"<b>Submission ID:</b> <code>#{sub_code}</code>\n"
                f"<b>Song:</b> {html.quote(song_title)}\n"
                f"<b>For:</b> {html.quote(rtext)}\n\n"
                "An admin will review your dedication. Once approved, it will be posted to the Telegram channel using Telegram's native audio player!\n\n"
                "Thank you for sharing the music vibes! 🎵",
                reply_markup=None
            )
            await callback_query.answer("Submitted!")

            # Send moderation alert to Admin
            msg_snippet = f'"{html.quote(ded_msg)}"' if ded_msg else "<i>(No message included)</i>"
            admin_caption = (
                "🎵 <b>MUSIC DEDICATION REVIEW</b>\n\n"
                f"<b>Submission ID:</b> <code>#{sub_code}</code>\n"
                f"<b>From:</b> Anonymous (<code>UID:{user_id}</code>)\n"
                f"<b>For:</b> {html.quote(rtext)}\n"
                f"<b>Song:</b> {html.quote(song_title)}\n\n"
                f"<b>Message:</b>\n{msg_snippet}"
            )
            if len(admin_caption) > 1024:
                admin_caption = admin_caption[:1020] + "..."

            mod_builder = InlineKeyboardBuilder()
            mod_builder.button(text="✅ Approve & Post", callback_data=f"adm_appr_music_{sub_id}")
            mod_builder.button(text="❌ Reject", callback_data=f"adm_rej_music_{sub_id}")
            mod_builder.adjust(2)

            if ADMIN_ID:
                try:
                    await bot.send_audio(
                        chat_id=ADMIN_ID,
                        audio=file_id,
                        caption=admin_caption,
                        title=song_title,
                        reply_markup=mod_builder.as_markup()
                    )
                except Exception as e:
                    logging.error(f"Failed to send music audio to admin {ADMIN_ID}: {e}")
                    await bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"{admin_caption}\n\n⚠️ (Audio send error: {e})",
                        reply_markup=mod_builder.as_markup()
                    )

        except Exception as e:
            logging.error(f"Error saving music dedication: {e}", exc_info=True)
            await callback_query.message.edit_text("❌ An error occurred while submitting your dedication. Please try again later.")
        finally:
            await state.clear()

    @dp.callback_query(F.data == "music_cancel")
    async def cancel_music_flow(callback_query: types.CallbackQuery, state: FSMContext):
        await state.clear()
        try:
            await callback_query.message.edit_text("❌ Music dedication cancelled.", reply_markup=None)
        except TelegramBadRequest:
            await callback_query.message.answer("❌ Music dedication cancelled.")
        await callback_query.answer("Cancelled.")

    # --- Admin Moderation: Approve / Reject ---
    @dp.callback_query(F.data.startswith("adm_appr_music_"))
    async def handle_admin_approve_music(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        sub_id = int(callback_query.data.split("_")[-1])
        if not db:
            await callback_query.answer("DB unavailable.")
            return

        async with db.acquire() as conn:
            sub = await get_music_submission_by_id(conn, sub_id)

        if not sub:
            await callback_query.answer("Submission not found.", show_alert=True)
            return
        if sub['status'] != 'pending':
            await callback_query.answer(f"Already {sub['status']}.", show_alert=True)
            return

        song_title = sub['title']
        rtext = sub['recipient_text']
        user_msg = sub['dedication_message']

        msg_body = f"\n\n💬 <i>\"{html.quote(user_msg)}\"</i>" if user_msg else ""
        channel_caption = (
            "🎵 <b>Music Dedication</b>\n\n"
            f"💌 <b>For:</b> {html.quote(rtext)}"
            f"{msg_body}\n\n"
            "🔒 <i>Anonymous Dedication</i> • #MWUConfessions"
        )
        if len(channel_caption) > 1024:
            channel_caption = channel_caption[:1020] + "..."

        try:
            channel_msg = await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=sub['telegram_file_id'],
                caption=channel_caption,
                title=song_title
            )

            async with db.acquire() as conn:
                await update_submission_status(
                    conn=conn,
                    sub_id=sub_id,
                    status="approved",
                    channel_msg_id=channel_msg.message_id
                )

            # Safely edit admin message caption without caption_html
            orig_caption = callback_query.message.caption or ""
            new_caption = f"{html.quote(orig_caption)}\n\n-- ✅ <b>Approved &amp; Posted to Channel</b> --"
            if len(new_caption) > 1024:
                new_caption = new_caption[:1020] + "..."

            try:
                await callback_query.message.edit_caption(
                    caption=new_caption,
                    reply_markup=None
                )
            except Exception as edit_err:
                logging.warning(f"Could not edit admin caption: {edit_err}")

            await safe_send_message(
                sub['user_id'],
                f"🎉 <b>Your music dedication (#{sub['submission_code']}) was approved and posted to the channel!</b>\n\n"
                f"🎵 Song: <b>{html.quote(song_title)}</b>\n"
                f"Thank you for sharing with the community!"
            )
            await callback_query.answer(f"Dedication #{sub['submission_code']} published!")

        except Exception as e:
            logging.error(f"Error publishing music dedication #{sub_id} to channel: {e}", exc_info=True)
            await callback_query.answer(f"Error posting to channel: {str(e)[:100]}", show_alert=True)

    @dp.callback_query(F.data.startswith("adm_rej_music_"))
    async def handle_admin_reject_music(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        sub_id = int(callback_query.data.split("_")[-1])
        if not db:
            return

        async with db.acquire() as conn:
            sub = await get_music_submission_by_id(conn, sub_id)
            if not sub:
                await callback_query.answer("Submission not found.", show_alert=True)
                return
            if sub['status'] != 'pending':
                await callback_query.answer(f"Already {sub['status']}.", show_alert=True)
                return

            await update_submission_status(
                conn=conn,
                sub_id=sub_id,
                status="rejected",
                rejection_reason="Did not meet channel community guidelines"
            )

        orig_caption = callback_query.message.caption or ""
        new_caption = f"{html.quote(orig_caption)}\n\n-- ❌ <b>Rejected by Admin</b> --"
        if len(new_caption) > 1024:
            new_caption = new_caption[:1020] + "..."

        try:
            await callback_query.message.edit_caption(
                caption=new_caption,
                reply_markup=None
            )
        except Exception as edit_err:
            logging.warning(f"Could not edit admin caption: {edit_err}")

        await safe_send_message(
            sub['user_id'],
            f"❌ <b>Your music dedication (#{sub['submission_code']}) was reviewed and not approved for channel posting.</b>"
        )
        await callback_query.answer("Dedication rejected.")

    # --- Admin Feature 1: Music Library & Management ---
    @dp.message(F.text == "/adminmusic")
    async def cmd_admin_music(message: types.Message):
        if not is_admin(message.from_user.id):
            return

        lib_count = 0
        pend_count = 0
        if db:
            async with db.acquire() as conn:
                lib_count = await count_music_library(conn)
                pend_count = await count_pending_submissions(conn)

        text = (
            "🎵 <b>Admin Music Management Panel</b>\n\n"
            f"📋 <b>Library Songs:</b> {lib_count}\n"
            f"📨 <b>Pending Dedications:</b> {pend_count}\n\n"
            "Select an action below:"
        )
        await message.answer(text, reply_markup=get_admin_music_menu())

    @dp.callback_query(F.data == "admin_music_main")
    async def cb_admin_music_main(callback_query: types.CallbackQuery, state: FSMContext):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return
        await state.clear()

        lib_count = 0
        pend_count = 0
        if db:
            async with db.acquire() as conn:
                lib_count = await count_music_library(conn)
                pend_count = await count_pending_submissions(conn)

        text = (
            "🎵 <b>Admin Music Management Panel</b>\n\n"
            f"📋 <b>Library Songs:</b> {lib_count}\n"
            f"📨 <b>Pending Dedications:</b> {pend_count}\n\n"
            "Select an action below:"
        )
        try:
            await callback_query.message.edit_text(text, reply_markup=get_admin_music_menu())
        except TelegramBadRequest:
            await callback_query.message.answer(text, reply_markup=get_admin_music_menu())
        await callback_query.answer()

    @dp.callback_query(F.data == "admin_music_close")
    async def cb_admin_music_close(callback_query: types.CallbackQuery):
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.answer("Closed.")

    @dp.callback_query(F.data == "admin_music_add")
    async def cb_admin_music_add(callback_query: types.CallbackQuery, state: FSMContext):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        await state.set_state(AdminMusicForm.waiting_for_audio)
        text = (
            "🎵 <b>Add / Post Music</b>\n\n"
            "Please send the audio file you want to add to the library or post to the channel.\n\n"
            "<i>Send an MP3/M4A/FLAC file or type /cancel to abort.</i>"
        )
        await callback_query.message.answer(text)
        await callback_query.answer()

    @dp.message(AdminMusicForm.waiting_for_audio, F.audio)
    async def admin_receive_audio(message: types.Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return

        audio = message.audio
        detected_title = audio.title or audio.file_name or "Untitled Song"
        if audio.performer:
            detected_title = f"{audio.performer} - {detected_title}"

        await state.update_data(
            audio_file_id=audio.file_id,
            detected_title=detected_title
        )
        await state.set_state(AdminMusicForm.waiting_for_title)

        text = (
            f"🎵 <b>Audio Received!</b>\n\n"
            f"<b>Detected Title:</b> <code>{html.quote(detected_title)}</code>\n\n"
            "Send a custom song title, or send /keep to keep the detected title:"
        )
        await message.answer(text)

    @dp.message(AdminMusicForm.waiting_for_title, F.text)
    async def admin_receive_title(message: types.Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        if message.text.startswith("/cancel"):
            await state.clear()
            await message.answer("Cancelled.")
            return

        data = await state.get_data()
        final_title = data.get("detected_title", "Untitled") if message.text.startswith("/keep") else message.text.strip()

        await state.update_data(final_title=final_title)
        await state.set_state(AdminMusicForm.waiting_for_caption)

        text = (
            f"🎵 <b>Title Set:</b> <i>{html.quote(final_title)}</i>\n\n"
            "📝 <b>Optional Caption/Message:</b>\n"
            "Enter a caption/message to display with this song when posted to the channel, or send /skip:"
        )
        await message.answer(text)

    @dp.message(AdminMusicForm.waiting_for_caption, F.text)
    async def admin_receive_caption(message: types.Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            return
        if message.text.startswith("/cancel"):
            await state.clear()
            await message.answer("Cancelled.")
            return

        caption = None if message.text.startswith("/skip") else message.text.strip()
        data = await state.get_data()
        file_id = data.get("audio_file_id")
        title = data.get("final_title", "Untitled")

        music_id = 1
        if db:
            async with db.acquire() as conn:
                music_id = await insert_music_to_library(
                    conn=conn,
                    file_id=file_id,
                    title=title,
                    caption=caption,
                    admin_id=message.from_user.id
                )

        builder = InlineKeyboardBuilder()
        builder.button(text="📢 Post to Channel Now", callback_data=f"adm_post_now_{music_id}")
        builder.button(text="📋 View in Library", callback_data="admin_music_library_1")
        builder.button(text="❌ Done", callback_data="admin_music_close")
        builder.adjust(1, 1, 1)

        cap_disp = f'"{html.quote(caption)}"' if caption else "<i>None</i>"
        text = (
            "✅ <b>Song Added to Library!</b>\n\n"
            f"<b>ID:</b> #{music_id}\n"
            f"<b>Title:</b> {html.quote(title)}\n"
            f"<b>Caption:</b> {cap_disp}\n\n"
            "Would you like to broadcast this song to the channel now?"
        )
        await message.answer(text, reply_markup=builder.as_markup())
        await state.clear()

    @dp.callback_query(F.data.startswith("adm_post_now_"))
    async def handle_admin_post_now(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        music_id = int(callback_query.data.split("_")[-1])
        if not db:
            return

        async with db.acquire() as conn:
            song = await get_music_by_id(conn, music_id)

        if not song:
            await callback_query.answer("Song not found.", show_alert=True)
            return

        title = song['title']
        caption = song['caption']
        post_caption = f"🎵 <b>{html.quote(title)}</b>"
        if caption:
            post_caption += f"\n\n{html.quote(caption)}"
        post_caption += "\n\n📻 #MWUMusic • #MWUConfessions"

        if len(post_caption) > 1024:
            post_caption = post_caption[:1020] + "..."

        try:
            await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=song['telegram_file_id'],
                caption=post_caption,
                title=title
            )

            async with db.acquire() as conn:
                await increment_music_posted_count(conn, music_id)

            await callback_query.message.edit_text(
                f"✅ <b>Successfully posted to channel!</b>\n\n"
                f"🎵 <b>Title:</b> {html.quote(title)}\n"
                "Users can now play it directly in Telegram.",
                reply_markup=get_admin_music_menu()
            )
            await callback_query.answer("Posted to channel!")

        except Exception as e:
            logging.error(f"Failed to post song #{music_id} to channel: {e}", exc_info=True)
            await callback_query.answer(f"Failed to post: {str(e)[:100]}", show_alert=True)

    # --- Library Pagination ---
    @dp.callback_query(F.data.startswith("admin_music_library_"))
    async def view_music_library(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        if not db:
            await callback_query.answer("DB not available.")
            return

        page = int(callback_query.data.split("_")[-1])
        page_size = 5

        async with db.acquire() as conn:
            total = await count_music_library(conn)
            if total == 0:
                text = (
                    "📋 <b>Music Library is Empty</b>\n\n"
                    "You haven't added any songs to the library yet.\n"
                    "Use <b>➕ Add Music</b> to upload audio tracks."
                )
                builder = InlineKeyboardBuilder()
                builder.button(text="➕ Add Music", callback_data="admin_music_add")
                builder.button(text="⬅️ Back", callback_data="admin_music_main")
                builder.adjust(1)
                await callback_query.message.edit_text(text, reply_markup=builder.as_markup())
                await callback_query.answer()
                return

            total_pages = (total + page_size - 1) // page_size
            page = max(1, min(page, total_pages))
            offset = (page - 1) * page_size
            songs = await get_music_library_page(conn, limit=page_size, offset=offset)

        builder = InlineKeyboardBuilder()
        text_lines = [f"📋 <b>Music Library (Page {page}/{total_pages} • Total: {total})</b>\n"]

        for s in songs:
            sid = s['id']
            stitle = html.quote(s['title'][:40])
            pcount = s['posted_count']
            text_lines.append(f"• #{sid} <b>{stitle}</b> (Posted {pcount}x)")
            builder.row(
                InlineKeyboardButton(text=f"📢 Post #{sid}", callback_data=f"adm_post_now_{sid}"),
                InlineKeyboardButton(text=f"🗑️ Del #{sid}", callback_data=f"adm_del_music_{sid}")
            )

        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin_music_library_{page-1}"))
        if total_pages > 1:
            nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_music_library_{page+1}"))
        if nav_row:
            builder.row(*nav_row)

        builder.row(
            InlineKeyboardButton(text="➕ Add Music", callback_data="admin_music_add"),
            InlineKeyboardButton(text="⬅️ Main Menu", callback_data="admin_music_main")
        )

        try:
            await callback_query.message.edit_text("\n".join(text_lines), reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass
        await callback_query.answer()

    @dp.callback_query(F.data.startswith("adm_del_music_"))
    async def handle_admin_delete_music(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        if not db:
            return

        music_id = int(callback_query.data.split("_")[-1])
        async with db.acquire() as conn:
            success = await delete_music_by_id(conn, music_id)

        if success:
            await callback_query.answer(f"Song #{music_id} deleted from library.", show_alert=True)
        else:
            await callback_query.answer("Song not found.", show_alert=True)

        callback_query.data = "admin_music_library_1"
        await view_music_library(callback_query)

    # --- Pending Dedications Queue ---
    @dp.callback_query(F.data.startswith("admin_music_pending_"))
    async def view_pending_dedications(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        if not db:
            await callback_query.answer("DB not available.")
            return

        page = int(callback_query.data.split("_")[-1])
        page_size = 5

        async with db.acquire() as conn:
            total = await count_pending_submissions(conn)
            if total == 0:
                text = (
                    "📨 <b>Pending Music Dedications</b>\n\n"
                    "🎉 All caught up! No pending music dedications in the moderation queue."
                )
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Back to Menu", callback_data="admin_music_main")
                await callback_query.message.edit_text(text, reply_markup=builder.as_markup())
                await callback_query.answer()
                return

            total_pages = (total + page_size - 1) // page_size
            page = max(1, min(page, total_pages))
            offset = (page - 1) * page_size
            subs = await get_pending_submissions(conn, limit=page_size, offset=offset)

        builder = InlineKeyboardBuilder()
        text_lines = [f"📨 <b>Pending Dedications (Page {page}/{total_pages} • Total: {total})</b>\n"]

        for sub in subs:
            sub_id = sub['id']
            code = sub['submission_code']
            title = html.quote(sub['title'][:35])
            recip = html.quote(sub['recipient_text'][:25])
            text_lines.append(f"• <b>#{code}</b>: <i>{title}</i> → {recip}")
            builder.row(
                InlineKeyboardButton(text=f"🎧 Listen #{code}", callback_data=f"adm_play_sub_{sub_id}"),
                InlineKeyboardButton(text=f"✅ #{code}", callback_data=f"adm_appr_music_{sub_id}"),
                InlineKeyboardButton(text=f"❌ #{code}", callback_data=f"adm_rej_music_{sub_id}")
            )

        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin_music_pending_{page-1}"))
        if total_pages > 1:
            nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_music_pending_{page+1}"))
        if nav_row:
            builder.row(*nav_row)

        builder.row(InlineKeyboardButton(text="⬅️ Back to Main", callback_data="admin_music_main"))

        try:
            await callback_query.message.edit_text("\n".join(text_lines), reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass
        await callback_query.answer()

    @dp.callback_query(F.data.startswith("adm_play_sub_"))
    async def admin_listen_submission(callback_query: types.CallbackQuery):
        if not is_admin(callback_query.from_user.id):
            await callback_query.answer("Unauthorized.", show_alert=True)
            return

        if not db:
            return

        sub_id = int(callback_query.data.split("_")[-1])
        async with db.acquire() as conn:
            sub = await get_music_submission_by_id(conn, sub_id)

        if not sub:
            await callback_query.answer("Submission not found.", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Approve", callback_data=f"adm_appr_music_{sub_id}")
        builder.button(text="❌ Reject", callback_data=f"adm_rej_music_{sub_id}")
        builder.adjust(2)

        msg_disp = f'"{html.quote(sub["dedication_message"])}"' if sub['dedication_message'] else "<i>None</i>"
        caption = (
            f"🎵 <b>Submission #{sub['submission_code']}</b>\n"
            f"<b>Title:</b> {html.quote(sub['title'])}\n"
            f"<b>For:</b> {html.quote(sub['recipient_text'])}\n"
            f"<b>Message:</b> {msg_disp}"
        )
        try:
            await bot.send_audio(
                chat_id=callback_query.from_user.id,
                audio=sub['telegram_file_id'],
                caption=caption,
                title=sub['title'],
                reply_markup=builder.as_markup()
            )
            await callback_query.answer("Audio sent.")
        except Exception as e:
            logging.error(f"Error sending audio #{sub_id} to admin: {e}")
            await callback_query.answer("Error playing audio.", show_alert=True)

# --- Dynamic Theme Administration ---
@dp.message(Command("settheme"))
async def cmd_settheme(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    builder = InlineKeyboardBuilder()
    for tid, tinfo in THEMES.items():
        is_cur = " (Active)" if tid == CURRENT_ACTIVE_THEME else ""
        builder.button(text=f"{tinfo['menu_label']}{is_cur}", callback_data=f"swtheme_{tid}")
    builder.adjust(1)
    await message.answer(
        f"🎨 <b>Admin Community Theme Switcher</b>\n\n"
        f"Current Active Theme: <b>{THEMES[CURRENT_ACTIVE_THEME]['name']}</b>\n\n"
        "Select a theme below to activate instantly across the bot:",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("swtheme_"))
async def handle_switch_theme(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("Unauthorized.", show_alert=True)
        return

    tid = callback_query.data.replace("swtheme_", "")
    if tid in THEMES:
        global CURRENT_ACTIVE_THEME
        CURRENT_ACTIVE_THEME = tid
        if db:
            async with db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO system_config (key, value) VALUES ('active_theme', $1)
                    ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = CURRENT_TIMESTAMP
                """, tid)

        await callback_query.message.edit_text(
            f"✅ <b>Theme Activated:</b> {THEMES[tid]['name']}\n"
            f"Branding: <code>{THEMES[tid]['header_branding']}</code>\n"
            f"Tag: <code>{THEMES[tid]['tag']}</code>\n\n"
            "All /start greetings, banners, and categories updated!"
        )
        await callback_query.answer("Theme updated!")

# --- Health check endpoint ---
async def handle_health_check(request):
    return web.Response(text="Telegram Confession & Music Bot OK")

# ==========================================
# MAIN EXECUTION ENTRY POINT
# ==========================================
async def main():
    webhook_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    try:
        await setup()
        register_music_handlers()

        dp.message.middleware(BlockUserMiddleware())
        dp.callback_query.middleware(BlockUserMiddleware())

        commands = [
            types.BotCommand(command="start", description="Vault entrance & daily themes"),
            types.BotCommand(command="confess", description="Submit an anonymous confession"),
            types.BotCommand(command="music", description="🎵 Dedicate a song anonymously"),
            types.BotCommand(command="prompt", description="Today's reflection prompt"),
            types.BotCommand(command="profile", description="Your Aura points & history"),
            types.BotCommand(command="leaderboard", description="Top supportive community peers"),
            types.BotCommand(command="rules", description="Zero-doxxing safety rules"),
            types.BotCommand(command="help", description="Show help and commands"),
            types.BotCommand(command="cancel", description="Cancel current action"),
        ]
        admin_commands = commands + [
            types.BotCommand(command="adminmusic", description="ADMIN: 🎵 Music Library & Moderation"),
            types.BotCommand(command="settheme", description="ADMIN: Dynamic Community Theme Switcher"),
            types.BotCommand(command="postprompt", description="ADMIN: Post daily prompt to channel"),
            types.BotCommand(command="rules", description="ADMIN: View safety rules"),
        ]
        if bot_info:
            await bot.set_my_commands(commands)
            if ADMIN_ID:
                try:
                    await bot.set_my_commands(admin_commands, scope=types.BotCommandScopeChat(chat_id=ADMIN_ID))
                except Exception:
                    pass

        if webhook_host:
            WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
            webhook_url = f"https://{webhook_host}{WEBHOOK_PATH}"
            await bot.set_webhook(webhook_url, drop_pending_updates=False)
            logging.info(f"Webhook set to: {webhook_url}")

            app = web.Application()
            webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
            webhook_requests_handler.register(app, path=WEBHOOK_PATH)
            app.router.add_get('/', handle_health_check)
            app.router.add_get('/healthz', handle_health_check)
            setup_application(app, dp, bot=bot)

            port = int(HTTP_PORT_STR) if HTTP_PORT_STR else 3000
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            logging.info(f"Bot web server running on port {port}")
            while True:
                await asyncio.sleep(3600)
        else:
            if BOT_TOKEN != "MOCK_TOKEN_CONFIG_REQUIRED" and bot_info:
                logging.info("Starting bot in polling mode...")
                await dp.start_polling(bot, skip_updates=True)
            else:
                logging.info("Bot configured. Awaiting credentials in .env to begin polling.")
                while True:
                    await asyncio.sleep(3600)

    except Exception as e:
        logging.critical(f"Fatal error during main execution: {e}", exc_info=True)
    finally:
        if bot and bot.session:
            await bot.session.close()
        if db:
            await db.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped.")
