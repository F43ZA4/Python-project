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
    "• /profile — Check your Aura points, submitted confessions & reflections\n"
    "• /leaderboard — View top supportive peers\n"
    "• /privacy — Privacy information & cryptographic anonymity\n"
    "• /contact — Send a private inquiry to administrators\n"
    "• /rules — Read the zero-doxxing safety rules\n"
    "• /cancel — Cancel any active submission\n\n"
    "<b>Admin Commands:</b>\n"
    "• /adminmusic — 🎵 Music Library & Dedications Moderation\n"
    "• /settheme — Switch community theme (Enkutatash 2019, Finals, etc.)\n"
    "• /postprompt — Broadcast today's prompt to the channel\n"
    "• /id <user_id> — Inspect user profile & activity\n"
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

class CommentForm(StatesGroup):
    waiting_for_comment = State()
    waiting_for_reply = State()

class ContactAdminForm(StatesGroup):
    waiting_for_message = State()

class AdminActions(StatesGroup):
    waiting_for_rejection_reason = State()

class RulesConsentForm(StatesGroup):
    pending_consent = State()

# --- Helper Cryptographic / Identity & Reaction Utilities ---
def get_anonymized_alias(user_id: int) -> str:
    salt = (user_id * 31) % 900 + 100
    return f"Confidant #{salt}"

def get_reaction_meta(r_type: str) -> Dict[str, str]:
    theme = get_current_theme()
    if "reactions" in theme and r_type in theme["reactions"]:
        return theme["reactions"][r_type]
    for t in THEMES.values():
        if "reactions" in t and r_type in t["reactions"]:
            return t["reactions"][r_type]
    return {"emoji": "❤️", "label": "Support"}

async def get_comment_reactions_counts(comment_id: int) -> Dict[str, int]:
    theme = get_current_theme()
    counts = {k: 0 for k in theme.get("reactions", {}).keys()}
    if not counts:
        counts = {"notalone": 0, "heard": 0, "support": 0}
    if not db:
        return counts
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT reaction_type, COUNT(*) as cnt 
                FROM reactions 
                WHERE comment_id = $1 
                GROUP BY reaction_type
            """, comment_id)
            for r in rows:
                counts[r['reaction_type']] = int(r['cnt'])
    except Exception as e:
        logging.warning(f"Error fetching reaction counts for comment {comment_id}: {e}")
    return counts

async def build_comment_keyboard(comment_id: int, commenter_user_id: int, viewer_user_id: int, confession_owner_id: int):
    counts = await get_comment_reactions_counts(comment_id)
    theme = get_current_theme()
    builder = InlineKeyboardBuilder()
    reactions = theme.get("reactions", {
        "notalone": {"emoji": "🫂", "label": "Not Alone"},
        "heard": {"emoji": "🕯️", "label": "Heard"},
        "support": {"emoji": "❤️", "label": "Support"}
    })
    for r_type, r_meta in reactions.items():
        cnt = counts.get(r_type, 0)
        builder.button(text=f"{r_meta['emoji']} {cnt}", callback_data=f"react_{r_type}_{comment_id}")
    builder.button(text="↪️ Reply", callback_data=f"reply_{comment_id}")
    builder.button(text="⚠️ Report", callback_data=f"report_confirm_{comment_id}")

    if viewer_user_id == confession_owner_id and viewer_user_id != commenter_user_id:
        builder.button(text="🤝 Request Contact", callback_data=f"req_contact_{comment_id}")
        builder.adjust(3, 2, 1)
    else:
        builder.adjust(3, 2)
    return builder.as_markup()

async def get_comment_sequence_number(conn: asyncpg.Connection, comment_id: int, confession_id: int) -> Optional[int]:
    query = """
        WITH ranked_comments AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC) as rn
            FROM comments
            WHERE confession_id = $1
        )
        SELECT rn FROM ranked_comments WHERE id = $2;
    """
    try:
        return await conn.fetchval(query, confession_id, comment_id)
    except Exception as e:
        logging.error(f"Could not fetch sequence number for comment {comment_id}: {e}")
        return None

async def update_channel_post_button(confession_id: int):
    global bot_info
    if not bot_info:
        try:
            bot_info = await bot.get_me()
        except Exception:
            return
    if not db:
        return
    try:
        async with db.acquire() as conn:
            conf_data = await conn.fetchrow("SELECT message_id FROM confessions WHERE id = $1 AND status = 'approved'", confession_id)
            count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id) or 0
        if not conf_data or not conf_data['message_id']:
            return
        ch_msg_id = conf_data['message_id']
        link = f"https://t.me/{bot_info.username}?start=view_{confession_id}"
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"💬 Safe Room & Comments ({count})", url=link)
        ]])
        await bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=ch_msg_id, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass
        elif "message to edit not found" in str(e).lower():
            logging.warning(f"Channel msg {ch_msg_id} not found in {CHANNEL_ID} (conf {confession_id}).")
        else:
            logging.error(f"Failed edit channel post {ch_msg_id} for conf {confession_id}: {e}")
    except Exception as e:
        logging.error(f"Error updating button for conf {confession_id}: {e}")

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
async def display_confession_safe_room(user_id: int, conf_id: int, target_msg: types.Message):
    if not db:
        await target_msg.answer("Database temporarily unavailable.")
        return

    async with db.acquire() as conn:
        conf_data = await conn.fetchrow("""
            SELECT c.id, c.text, c.categories, c.status, c.user_id, c.photo_file_id, c.prompt_text, COUNT(com.id) as comment_count 
            FROM confessions c 
            LEFT JOIN comments com ON c.id = com.confession_id 
            WHERE c.id = $1 
            GROUP BY c.id
        """, conf_id)

    if not conf_data or conf_data['status'] != 'approved':
        await target_msg.answer(f"⚠️ Confession #{conf_id} was not found or is no longer available.")
        return

    comm_count = conf_data['comment_count']
    categories = conf_data['categories'] or []
    category_tags = " ".join([f"#{html.quote(cat.replace(' ', ''))}" for cat in categories]) if categories else "#Confession"
    prompt_section = f"💡 <b>Prompt / Question:</b>\n<i>\"{html.quote(conf_data['prompt_text'])}\"</i>\n\n💬 <b>Response:</b>\n" if conf_data.get('prompt_text') else ""

    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Add Support / Reflection", callback_data=f"add_{conf_id}")
    builder.button(text=f"📜 Browse Reflections ({comm_count})", callback_data=f"browse_{conf_id}")
    builder.adjust(1, 1)

    theme = get_current_theme()
    channel_header = theme.get("header_branding", "MWU Confession")
    header_text = f"<b>{html.quote(channel_header)} #{conf_id}</b>"

    if conf_data['photo_file_id']:
        caption = f"{header_text}\n\n{prompt_section}{html.quote(conf_data['text'])}\n\n{category_tags}"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."
        await bot.send_photo(
            chat_id=user_id,
            photo=conf_data['photo_file_id'],
            caption=caption,
            reply_markup=builder.as_markup()
        )
    else:
        txt = f"{header_text}\n\n{prompt_section}{html.quote(conf_data['text'])}\n\n{category_tags}"
        await target_msg.answer(txt, reply_markup=builder.as_markup())

async def show_comments_for_confession(user_id: int, confession_id: int, message_to_edit: Optional[types.Message] = None, page: int = 1):
    if not db:
        await safe_send_message(user_id, "Database temporarily unavailable.")
        return

    async with db.acquire() as conn:
        conf_data = await conn.fetchrow("SELECT status, user_id FROM confessions WHERE id = $1", confession_id)
        if not conf_data or conf_data['status'] != 'approved':
            err_txt = f"Confession #{confession_id} not found or not approved."
            if message_to_edit:
                try:
                    await message_to_edit.edit_text(err_txt, reply_markup=None)
                except Exception:
                    await safe_send_message(user_id, err_txt)
            else:
                await safe_send_message(user_id, err_txt)
            return

        confession_owner_id = conf_data['user_id']
        total_count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id) or 0
        if total_count == 0:
            msg_text = (
                f"💬 <b>Safe Room &amp; Reflections for Confession #{confession_id}</b>\n\n"
                "<i>No reflections or comments yet. Be the first to share support and kindness!</i>"
            )
            nav = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Reflection", callback_data=f"add_{confession_id}")],
                [InlineKeyboardButton(text="⬅️ Back to Confession", callback_data=f"browse_back_{confession_id}")]
            ])
            if message_to_edit:
                try:
                    await message_to_edit.edit_text(msg_text, reply_markup=nav)
                except Exception:
                    await safe_send_message(user_id, msg_text, reply_markup=nav)
            else:
                await safe_send_message(user_id, msg_text, reply_markup=nav)
            return

        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
        page = max(1, min(page, total_pages))
        offset = (page - 1) * PAGE_SIZE
        comments_raw = await conn.fetch("""
            SELECT c.id, c.user_id, c.text, c.sticker_file_id, c.animation_file_id, c.parent_comment_id, c.created_at, 
                   COALESCE(up.points, 0) as user_points 
            FROM comments c 
            LEFT JOIN user_points up ON c.user_id = up.user_id 
            WHERE c.confession_id = $1 
            ORDER BY c.created_at ASC 
            LIMIT $2 OFFSET $3
        """, confession_id, PAGE_SIZE, offset)

    db_id_to_message_id: Dict[int, int] = {}

    for i, c_data_row in enumerate(comments_raw):
        c_data = dict(c_data_row)
        seq_num = offset + i + 1
        db_id = c_data['id']
        commenter_uid = c_data['user_id']
        u_pts = c_data.get('user_points', 0)
        u_tier = get_aura_tier(u_pts)
        u_badge = u_tier.split()[0]
        alias = get_anonymized_alias(commenter_uid)
        tag = "🌟 Author" if commenter_uid == confession_owner_id else "👤 You" if commenter_uid == user_id else f"🌱 {alias}"
        admin_info = f" [<code>UID:{commenter_uid}</code>]" if user_id == ADMIN_ID else ""
        display_tag = f" {tag} (🏅{u_pts} {u_badge})"

        reply_to_msg_id = None
        text_reply_prefix = ""
        parent_db_id = c_data.get('parent_comment_id')
        if parent_db_id:
            if parent_db_id in db_id_to_message_id:
                reply_to_msg_id = db_id_to_message_id[parent_db_id]
            else:
                async with db.acquire() as conn_for_seq:
                    parent_seq = await get_comment_sequence_number(conn_for_seq, parent_db_id, confession_id)
                if parent_seq:
                    text_reply_prefix = f"↪️ <i>Replying to reflection #{parent_seq}...</i>\n"
                else:
                    text_reply_prefix = "↪️ <i>Replying to another reflection...</i>\n"

        metadata_text = f"<i>#{seq_num}{display_tag}{admin_info}</i>"
        keyboard = await build_comment_keyboard(db_id, commenter_uid, user_id, confession_owner_id)

        sent_msg = None
        try:
            if c_data['sticker_file_id']:
                sent_msg = await bot.send_sticker(user_id, sticker=c_data['sticker_file_id'], reply_to_message_id=reply_to_msg_id)
                await bot.send_message(user_id, f"{text_reply_prefix}{metadata_text}", reply_markup=keyboard)
            elif c_data['animation_file_id']:
                sent_msg = await bot.send_animation(user_id, animation=c_data['animation_file_id'], reply_to_message_id=reply_to_msg_id)
                await bot.send_message(user_id, f"{text_reply_prefix}{metadata_text}", reply_markup=keyboard)
            elif c_data['text']:
                full_text = f"{text_reply_prefix}💬 {html.quote(c_data['text'])}\n\n{metadata_text}"
                sent_msg = await bot.send_message(user_id, full_text, reply_markup=keyboard, disable_web_page_preview=True, reply_to_message_id=reply_to_msg_id)
            if sent_msg:
                db_id_to_message_id[db_id] = sent_msg.message_id
        except Exception as e:
            logging.warning(f"Could not send comment #{seq_num} to {user_id}: {e}")
        await asyncio.sleep(0.05)

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"comments_page_{confession_id}_{page-1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text=f"Page {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"comments_page_{confession_id}_{page+1}"))

    nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [InlineKeyboardButton(text="➕ Add Reflection", callback_data=f"add_{confession_id}")],
        [InlineKeyboardButton(text="⬅️ Back to Confession", callback_data=f"browse_back_{confession_id}")]
    ])
    end_txt = f"--- Showing reflections {offset+1} to {min(offset+PAGE_SIZE, total_count)} of {total_count} for Confession #{confession_id} ---"
    await safe_send_message(user_id, end_txt, reply_markup=nav_keyboard)

@dp.message(Command("start"))
async def send_welcome(message: types.Message, state: FSMContext, command: Optional[CommandObject] = None):
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

    # Deep-link support: e.g., t.me/bot?start=prompt or ?start=prompt_X or ?start=view_X
    if command and command.args:
        args = command.args.strip()
        if args == "prompt" or args.startswith("prompt_"):
            prompt_to_answer = today_prompt
            if args.startswith("prompt_"):
                try:
                    p_idx = int(args.split("_", 1)[1])
                    if 0 <= p_idx < len(DAILY_PROMPTS):
                        prompt_to_answer = DAILY_PROMPTS[p_idx]
                except Exception:
                    pass

            await state.update_data(active_prompt=prompt_to_answer, selected_categories=["Other"])
            await state.set_state(ConfessionForm.writing_confession)
            await message.answer(
                f"💡 <b>Responding to Daily Campus Reflection:</b>\n"
                f"Theme: <b>{html.quote(theme_title)}</b> (<code>{html.quote(tag)}</code>)\n\n"
                f"<i>\"{html.quote(prompt_to_answer)}\"</i>\n\n"
                "Please send your anonymous response below (or attach a photo with your text as caption):\n"
                "<i>Your identity remains 100% confidential. Send /cancel to stop.</i>"
            )
            return

        elif args.startswith("view_"):
            try:
                conf_id = int(args.split("_", 1)[1])
                await display_confession_safe_room(user_id, conf_id, message)
                return
            except Exception as e:
                logging.error(f"Error opening view deep link {args}: {e}")

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

@dp.message(Command("postprompt"))
async def cmd_postprompt(message: types.Message, command: Optional[CommandObject] = None):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⚠️ <b>Unauthorized:</b> Only bot administrators can broadcast reflection prompts.")
        return

    # Custom prompt text if provided via /postprompt <custom text>, otherwise today's prompt
    custom_text = command.args.strip() if (command and command.args) else None
    prompt_text = custom_text or get_today_prompt()
    tag, theme_title, _ = get_today_theme()

    channel_target = CHANNEL_ID
    if not channel_target or channel_target == "@channel":
        await message.answer(
            "⚠️ <b>Channel ID Not Configured:</b> <code>CHANNEL_ID</code> is missing or placeholder.\n"
            "Please configure your channel username or ID (e.g. <code>@MyChannel</code>) in your environment variables."
        )
        return

    # Determine bot username for direct-action deep link
    global bot_info
    if not bot_info:
        try:
            bot_info = await bot.get_me()
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    if bot_info and bot_info.username:
        builder.button(
            text="✍️ Answer Anonymously",
            url=f"https://t.me/{bot_info.username}?start=prompt"
        )
    builder.adjust(1)

    channel_post = (
        f"💡 <b>Daily Campus Reflection</b>\n"
        f"Theme: <b>{html.quote(theme_title)}</b> (<code>{html.quote(tag)}</code>)\n\n"
        f"<i>\"{html.quote(prompt_text)}\"</i>\n\n"
        f"🔒 <i>Tap below to share your anonymous response or confession!</i>"
    )

    try:
        sent_msg = await bot.send_message(
            chat_id=channel_target,
            text=channel_post,
            reply_markup=builder.as_markup() if (bot_info and bot_info.username) else None
        )
        await message.answer(
            f"✅ <b>Daily Prompt broadcasted successfully to channel!</b>\n\n"
            f"📢 <b>Target Channel:</b> <code>{html.quote(str(channel_target))}</code>\n"
            f"🆔 <b>Message ID:</b> <code>{sent_msg.message_id}</code>\n\n"
            f"💡 <b>Prompt:</b> <i>\"{html.quote(prompt_text)}\"</i>"
        )
    except Exception as e:
        logging.error(f"Failed to post prompt to channel {channel_target}: {e}", exc_info=True)
        await message.answer(
            f"❌ <b>Failed to post prompt to channel:</b>\n"
            f"<code>{html.quote(str(e))}</code>\n\n"
            f"💡 <b>Troubleshooting:</b>\n"
            f"1. Ensure the channel handle or ID is correct (e.g. <code>@MyChannel</code> or <code>-100...</code>).\n"
            f"2. Ensure your bot is added as an <b>Administrator</b> to the channel.\n"
            f"3. Ensure the bot has <b>'Post Messages'</b> permission enabled."
        )

@dp.message(Command("warn"))
async def cmd_warn(message: types.Message, command: Optional[CommandObject] = None):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⚠️ Unauthorized.")
        return

    if not command or not command.args:
        await message.answer("<b>Usage:</b> <code>/warn &lt;user_id&gt; [reason]</code>")
        return

    parts = command.args.strip().split(maxsplit=1)
    try:
        target_uid = int(parts[0])
    except ValueError:
        await message.answer("❌ Invalid User ID. Must be a numeric Telegram ID.")
        return

    reason = parts[1] if len(parts) > 1 else "Violation of campus community guidelines"
    warn_text = (
        f"⚠️ <b>Official Community Warning</b> 🛡️\n\n"
        f"Your recent activity violated the vault's zero-doxxing or safety guidelines.\n\n"
        f"<b>Reason:</b> {html.quote(reason)}\n\n"
        f"<i>Please review /rules. Repeated violations will result in an immediate temporary or permanent ban.</i>"
    )

    try:
        await bot.send_message(target_uid, warn_text)
        await message.answer(f"✅ Warning sent to user <code>{target_uid}</code>.")
    except Exception as e:
        await message.answer(f"❌ Could not deliver warning to <code>{target_uid}</code>: {e}")

@dp.message(Command("block"))
async def cmd_block(message: types.Message, command: Optional[CommandObject] = None):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⚠️ Unauthorized.")
        return

    if not command or not command.args:
        await message.answer(
            "<b>Usage:</b> <code>/block &lt;user_id&gt; [hours] [reason]</code>\n"
            "• Use 0 hours or omit hours for permanent ban.\n"
            "<i>Example: /block 12345678 24 Repeated doxxing</i>"
        )
        return

    parts = command.args.strip().split(maxsplit=2)
    try:
        target_uid = int(parts[0])
    except ValueError:
        await message.answer("❌ Invalid User ID. Must be numeric.")
        return

    hours = 0
    reason_idx = 1
    if len(parts) > 1 and parts[1].isdigit():
        hours = int(parts[1])
        reason_idx = 2

    reason = " ".join(parts[reason_idx:]) if len(parts) > reason_idx else "Violating community safety guidelines"
    blocked_until = datetime.now(timezone.utc) + timedelta(hours=hours) if hours > 0 else None

    if db:
        async with db.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_status (user_id, is_blocked, blocked_until, block_reason)
                VALUES ($1, TRUE, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET
                    is_blocked = TRUE,
                    blocked_until = $2,
                    block_reason = $3
            """, target_uid, blocked_until, reason)

    dur_str = f"{hours} hour(s)" if hours > 0 else "indefinitely"
    await message.answer(f"🚫 User <code>{target_uid}</code> has been suspended {dur_str}.\nReason: <i>{html.quote(reason)}</i>")

@dp.message(Command("unblock"))
async def cmd_unblock(message: types.Message, command: Optional[CommandObject] = None):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⚠️ Unauthorized.")
        return

    if not command or not command.args:
        await message.answer("<b>Usage:</b> <code>/unblock &lt;user_id&gt;</code>")
        return

    try:
        target_uid = int(command.args.strip().split()[0])
    except ValueError:
        await message.answer("❌ Invalid User ID.")
        return

    if db:
        async with db.acquire() as conn:
            await conn.execute("""
                UPDATE user_status
                SET is_blocked = FALSE, blocked_until = NULL, block_reason = NULL
                WHERE user_id = $1
            """, target_uid)

    await message.answer(f"✅ User <code>{target_uid}</code> has been unblocked.")
    try:
        await bot.send_message(
            target_uid,
            "🕊️ <b>Access Restored:</b> Your account restriction has been lifted by the administrator. Welcome back to the vault!"
        )
    except Exception:
        pass

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
        f"💬 <b>Supportive Reflections:</b> {comm_count}\n\n"
        f"<i>Earn Aura points by sharing courageous confessions (+{POINTS_PER_CONFESSION}), "
        f"offering empathetic comments (+{POINTS_PER_COMMENT}), and receiving reactions (+{POINTS_PER_REACTION_RECEIVED})!</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📜 My Confessions", callback_data="profile_menu_confessions_1"),
            InlineKeyboardButton(text="💬 My Reflections", callback_data="profile_menu_comments_1")
        ],
        [
            InlineKeyboardButton(text="🏆 View Leaderboard", callback_data="view_leaderboard_button")
        ]
    ])
    if isinstance(message_or_event, types.Message):
        await message_or_event.answer(text, reply_markup=keyboard)
    elif isinstance(message_or_event, types.CallbackQuery):
        await message_or_event.message.edit_text(text, reply_markup=keyboard)

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
        user_mention = f"@{message.from_user.username}" if (message.from_user and message.from_user.username) else "No @username"
        user_fullname = html.quote(message.from_user.full_name) if (message.from_user and message.from_user.full_name) else "Unknown"
        prompt_line = f"💡 <b>Prompt / Question:</b>\n<i>\"{html.quote(active_prompt)}\"</i>\n\n" if active_prompt else ""
        content_label = "💬 <b>Response / Answer:</b>" if active_prompt else "📝 <b>Content:</b>"

        admin_text = (
            f"🛡️ <b>NEW CONFESSION #{conf_id} AWAITING APPROVAL</b>\n\n"
            f"👤 <b>Poster ID:</b> <code>{user_id}</code>\n"
            f"👤 <b>User Info:</b> {user_mention} ({user_fullname})\n"
            f"🏷️ <b>Categories:</b> {', '.join(selected_cats)}\n\n"
            f"{prompt_line}"
            f"{content_label}\n{html.quote(text)}"
        )
        mod_builder = InlineKeyboardBuilder()
        mod_builder.button(text="✅ Approve", callback_data=f"adm_appr_conf_{conf_id}")
        mod_builder.button(text="❌ Reject", callback_data=f"adm_rej_conf_{conf_id}")
        mod_builder.adjust(2)
        try:
            if photo_id:
                caption = admin_text
                if len(caption) > 1024:
                    caption = caption[:1020] + "..."
                await bot.send_photo(ADMIN_ID, photo=photo_id, caption=caption, reply_markup=mod_builder.as_markup())
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
        
        prompt_section = ""
        if conf.get('prompt_text'):
            prompt_section = (
                f"💡 <b>Campus Reflection Prompt:</b>\n"
                f"<i>\"{html.quote(conf['prompt_text'])}\"</i>\n\n"
                f"💬 <b>Response:</b>\n"
            )

        channel_post = (
            f"📝 <b>Confession #{conf_id}</b>\n\n"
            f"{prompt_section}"
            f"{html.quote(conf['text'])}\n\n"
            f"{cats} {tag}"
        )

        link = f"https://t.me/{bot_info.username}?start=view_{conf_id}" if bot_info else ""
        channel_kbd = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Safe Room & Comments (0)", url=link)
        ]]) if link else None

        try:
            if conf['photo_file_id']:
                caption = channel_post
                if len(caption) > 1024:
                    caption = caption[:1020] + "..."
                c_msg = await bot.send_photo(CHANNEL_ID, photo=conf['photo_file_id'], caption=caption, reply_markup=channel_kbd)
            else:
                c_msg = await bot.send_message(CHANNEL_ID, text=channel_post, reply_markup=channel_kbd)

            await conn.execute("UPDATE confessions SET status = 'approved', message_id = $1 WHERE id = $2", c_msg.message_id, conf_id)
            await callback_query.answer("Approved and broadcasted!")
            await safe_send_message(conf['user_id'], f"🎉 <b>Your confession #{conf_id} was approved and posted to the channel!</b>")
            try:
                await callback_query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
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
    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
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

# --- Safe Room & Comments Interaction Handlers ---
@dp.callback_query(F.data.startswith("browse_"))
async def browse_comments_action(callback_query: types.CallbackQuery):
    parts = callback_query.data.split("_")
    if len(parts) >= 3 and parts[1] == "back":
        conf_id = int(parts[2])
        await display_confession_safe_room(callback_query.from_user.id, conf_id, callback_query.message)
        await callback_query.answer()
        return
    conf_id = int(parts[1])
    await callback_query.answer("Loading reflections...")
    await show_comments_for_confession(callback_query.from_user.id, conf_id, callback_query.message)

@dp.callback_query(F.data.startswith("add_"))
async def add_comment_prompt(callback_query: types.CallbackQuery, state: FSMContext):
    conf_id = int(callback_query.data.split("_", 1)[1])
    await state.update_data(confession_id=conf_id, parent_comment_id=None)
    await state.set_state(CommentForm.waiting_for_comment)
    await safe_send_message(
        callback_query.from_user.id,
        f"💬 <b>Adding Supportive Reflection to Confession #{conf_id}</b>\n\n"
        "Please send your reflection below (text message, sticker, or GIF).\n"
        "<i>Your identity remains 100% anonymous. Type /cancel to abort.</i>"
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith("comments_page_"))
async def comments_page_callback(callback_query: types.CallbackQuery):
    _, _, conf_id, page = callback_query.data.split("_")
    await callback_query.answer("Loading page...")
    await show_comments_for_confession(callback_query.from_user.id, int(conf_id), callback_query.message, page=int(page))

@dp.message(CommentForm.waiting_for_comment, F.text | F.sticker | F.animation)
async def receive_comment(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await cancel_any_state(message, state)
        return

    user_id = message.from_user.id
    data = await state.get_data()
    conf_id = data.get("confession_id")
    if not conf_id:
        await message.answer("⚠️ Session context lost. Please try again.")
        await state.clear()
        return

    comm_text, sticker_id, animation_id, log_type = None, None, None, "Unknown"
    if message.text:
        comm_text, log_type = message.text.strip(), "Text"
    elif message.sticker:
        sticker_id, log_type = message.sticker.file_id, "Sticker"
    elif message.animation:
        animation_id, log_type = message.animation.file_id, "GIF"
    else:
        await message.answer("Please send text, a sticker, or a GIF.")
        return

    try:
        async with db.acquire() as conn:
            async with conn.transaction():
                conf_owner_id = await conn.fetchval("SELECT user_id FROM confessions WHERE id = $1 AND status = 'approved'", conf_id)
                if not conf_owner_id:
                    raise Exception("Confession not found or not approved.")
                await conn.execute("""
                    INSERT INTO comments (confession_id, user_id, text, sticker_file_id, animation_file_id) 
                    VALUES ($1, $2, $3, $4, $5)
                """, conf_id, user_id, comm_text, sticker_id, animation_id)

        await message.answer(f"💬 <b>Your reflection has been posted anonymously! (+{POINTS_PER_COMMENT} Aura 🏅)</b>")
        await award_points(user_id, POINTS_PER_COMMENT)
        await update_channel_post_button(conf_id)

        if conf_owner_id and conf_owner_id != user_id and bot_info:
            link = f"https://t.me/{bot_info.username}?start=view_{conf_id}"
            preview = html.quote(comm_text[:120]) if comm_text else f"[{log_type}]"
            await safe_send_message(
                conf_owner_id,
                f"💌 <b>Someone left a supportive reflection on your Confession #{conf_id}!</b>\n\n"
                f"<i>\"{preview}...\"</i>\n\n"
                f"<a href='{link}'>Click here to view the reflection in your safe room.</a>",
                disable_web_page_preview=True
            )
        await show_comments_for_confession(user_id, conf_id)
    except Exception as e:
        logging.error(f"Error saving comment for conf #{conf_id}: {e}", exc_info=True)
        await message.answer("❌ Error saving reflection. The confession may have been deleted.")
    finally:
        await state.clear()

@dp.callback_query(F.data.startswith("reply_"))
async def reply_comment_prompt(callback_query: types.CallbackQuery, state: FSMContext):
    parent_id = int(callback_query.data.split("_", 1)[1])
    if not db:
        await callback_query.answer("Database unavailable.")
        return
    async with db.acquire() as conn:
        comm_data = await conn.fetchrow("SELECT confession_id, text, sticker_file_id, animation_file_id, user_id FROM comments WHERE id = $1", parent_id)
    if not comm_data:
        await callback_query.answer("Comment no longer exists.", show_alert=True)
        return
    if callback_query.from_user.id == comm_data['user_id']:
        await callback_query.answer("You cannot reply to your own reflection.", show_alert=True)
        return

    try:
        if comm_data['text']:
            await safe_send_message(callback_query.from_user.id, f"<i>Replying to:</i>\n\n{html.quote(comm_data['text'])}")
        elif comm_data['sticker_file_id']:
            await bot.send_sticker(callback_query.from_user.id, sticker=comm_data['sticker_file_id'])
        elif comm_data['animation_file_id']:
            await bot.send_animation(callback_query.from_user.id, animation=comm_data['animation_file_id'])

        prompt_message = await bot.send_message(
            callback_query.from_user.id,
            "⬆️ Please send your reply now (text, sticker, or GIF), or type /cancel.",
            reply_markup=ForceReply(input_field_placeholder="Your reply...")
        )

        await state.update_data(
            confession_id=comm_data['confession_id'],
            parent_comment_id=parent_id,
            message_id_to_reply_to=prompt_message.message_id
        )
        await state.set_state(CommentForm.waiting_for_reply)
        await callback_query.answer()
    except Exception as e:
        logging.error(f"Error starting reply prompt: {e}", exc_info=True)
        await callback_query.answer("Could not start reply process.", show_alert=True)
        await state.clear()

@dp.message(CommentForm.waiting_for_reply, F.text | F.sticker | F.animation)
async def receive_reply(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await cancel_any_state(message, state)
        return

    user_id = message.from_user.id
    data = await state.get_data()
    conf_id = data.get("confession_id")
    parent_id = data.get("parent_comment_id")

    if not conf_id or not parent_id:
        await message.answer("⚠️ Reply context expired. Please click 'Reply' again or type /cancel.")
        await state.clear()
        return

    reply_text, sticker_id, animation_id, log_type = None, None, None, "Unknown"
    if message.text:
        reply_text, log_type = message.text.strip(), "Text Reply"
    elif message.sticker:
        sticker_id, log_type = message.sticker.file_id, "Sticker Reply"
    elif message.animation:
        animation_id, log_type = message.animation.file_id, "GIF Reply"
    else:
        await message.answer("Invalid content type for a reply.")
        return

    try:
        async with db.acquire() as conn:
            async with conn.transaction():
                parent_data = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", parent_id)
                if not parent_data:
                    await message.answer("⚠️ The reflection you were replying to has been deleted.")
                    await state.clear()
                    return
                conf_data = await conn.fetchrow("SELECT user_id FROM confessions WHERE id = $1", conf_id)

                await conn.execute("""
                    INSERT INTO comments (confession_id, user_id, text, sticker_file_id, animation_file_id, parent_comment_id) 
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, conf_id, user_id, reply_text, sticker_id, animation_id, parent_id)

        await message.answer(f"↪️ <b>Your reply has been posted! (+{POINTS_PER_COMMENT} Aura 🏅)</b>", reply_markup=ReplyKeyboardRemove())
        await award_points(user_id, POINTS_PER_COMMENT)
        await update_channel_post_button(conf_id)

        if parent_data['user_id'] != user_id and bot_info:
            link = f"https://t.me/{bot_info.username}?start=view_{conf_id}"
            preview = html.quote(reply_text[:120]) if reply_text else f"[{log_type.replace(' Reply', '')}]"
            tag = "(Confession Author)" if conf_data and user_id == conf_data['user_id'] else "A peer"
            await safe_send_message(
                parent_data['user_id'],
                f"↪️ <b>{tag} replied to your reflection on Confession #{conf_id}:</b>\n\n<i>\"{preview}...\"</i>\n\n<a href='{link}'>Click here to view the reply.</a>",
                disable_web_page_preview=True
            )

        await show_comments_for_confession(user_id, conf_id)
    except Exception as e:
        logging.error(f"Error saving reply: {e}", exc_info=True)
        await message.answer("❌ Error saving reply.")
    finally:
        await state.clear()

# --- Emotional Micro-Interactions Handler ---
@dp.callback_query(F.data.startswith("react_"))
async def handle_reaction(callback_query: types.CallbackQuery):
    parts = callback_query.data.split("_")
    r_type = parts[1]
    comm_id = int(parts[2])
    user_id = callback_query.from_user.id
    meta = get_reaction_meta(r_type)
    point_delta, alert = 0, ""

    if not db:
        await callback_query.answer("Database unavailable.")
        return

    async with db.acquire() as conn:
        async with conn.transaction():
            info = await conn.fetchrow("""
                SELECT c.user_id as comm_uid, c.confession_id, co.user_id as conf_owner_id 
                FROM comments c 
                JOIN confessions co ON c.confession_id = co.id 
                WHERE c.id = $1
            """, comm_id)
            if not info:
                await callback_query.answer("Reflection not found.", show_alert=True)
                return
            if info['comm_uid'] == user_id:
                await callback_query.answer("You cannot react to your own reflection.", show_alert=True)
                return

            existing = await conn.fetchval("SELECT reaction_type FROM reactions WHERE comment_id = $1 AND user_id = $2", comm_id, user_id)
            if existing:
                if existing == r_type:
                    await conn.execute("DELETE FROM reactions WHERE comment_id = $1 AND user_id = $2", comm_id, user_id)
                    point_delta = -POINTS_PER_REACTION_RECEIVED
                    alert = f"Removed {meta['emoji']}"
                else:
                    await conn.execute("UPDATE reactions SET reaction_type = $1 WHERE comment_id = $2 AND user_id = $3", r_type, comm_id, user_id)
                    alert = f"Changed to {meta['label']} {meta['emoji']}"
            else:
                await conn.execute("INSERT INTO reactions (comment_id, user_id, reaction_type) VALUES ($1, $2, $3)", comm_id, user_id, r_type)
                point_delta = POINTS_PER_REACTION_RECEIVED
                alert = f"Added {meta['label']} {meta['emoji']}"

                # Real-time encouragement notification
                asyncio.create_task(safe_send_message(
                    info['comm_uid'],
                    f"{meta['emoji']} A peer felt your reflection on Confession #{info['confession_id']}:\n"
                    f"<i>\"{meta['label']}\"</i> (+{POINTS_PER_REACTION_RECEIVED} Aura 🏅)"
                ))

            if point_delta != 0:
                await award_points(info['comm_uid'], point_delta)

    kbd = await build_comment_keyboard(comm_id, info['comm_uid'], user_id, info['conf_owner_id'])
    try:
        await callback_query.message.edit_reply_markup(reply_markup=kbd)
        await callback_query.answer(alert)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.warning(f"Reaction edit markup failed: {e}")
        else:
            await callback_query.answer(alert)

# --- Reporting Flow ---
@dp.callback_query(F.data.startswith("report_confirm_"))
async def report_confirm_callback(callback_query: types.CallbackQuery):
    comment_id = int(callback_query.data.split("_")[-1])
    reporter_user_id = callback_query.from_user.id
    if not db:
        return
    async with db.acquire() as conn:
        comment_data = await conn.fetchrow("SELECT text, user_id FROM comments WHERE id = $1", comment_id)
        if not comment_data:
            await callback_query.answer("Comment deleted.", show_alert=True)
            return
        if comment_data['user_id'] == reporter_user_id:
            await callback_query.answer("You cannot report your own reflection.", show_alert=True)
            return

    snippet = html.quote(comment_data['text'][:100]) if comment_data['text'] else "[Media/Sticker]"
    confirm_text = f"Are you sure you want to report this reflection for administrative moderation?\n\n<i>\"{snippet}...\"</i>"
    kbd = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes, Report", callback_data=f"report_execute_{comment_id}"), 
        InlineKeyboardButton(text="❌ No, Cancel", callback_data="report_cancel")
    ]])
    await safe_send_message(reporter_user_id, confirm_text, reply_markup=kbd)
    await callback_query.answer()

@dp.callback_query(F.data.startswith("report_execute_"))
async def report_execute_callback(callback_query: types.CallbackQuery):
    comment_id = int(callback_query.data.split("_")[-1])
    reporter_user_id = callback_query.from_user.id
    if not db:
        return
    try:
        async with db.acquire() as conn:
            async with conn.transaction():
                comment_data = await conn.fetchrow("SELECT user_id, confession_id, text FROM comments WHERE id = $1", comment_id)
                if not comment_data:
                    await callback_query.message.edit_text("Report failed: Comment no longer exists.")
                    return
                reported_user_id = comment_data['user_id']
                await conn.execute("""
                    INSERT INTO reports (comment_id, reporter_user_id, reported_user_id) 
                    VALUES ($1, $2, $3) 
                    ON CONFLICT (comment_id, reporter_user_id) DO NOTHING
                """, comment_id, reporter_user_id, reported_user_id)

        snippet = html.quote(comment_data['text'][:200]) if comment_data['text'] else "[Media]"
        conf_link = f"https://t.me/{bot_info.username}?start=view_{comment_data['confession_id']}" if bot_info else ""
        admin_notification = (
            f"⚠️ <b>New Comment Report</b> 🛡️\n\n"
            f"<b>Confession:</b> <a href='{conf_link}'>#{comment_data['confession_id']}</a>\n"
            f"<b>Comment ID:</b> <code>{comment_id}</code>\n"
            f"<b>Content:</b>\n<i>{snippet}</i>\n\n"
            f"<b>Reported User ID:</b> <code>{reported_user_id}</code>\n"
            f"<b>Reporter User ID:</b> <code>{reporter_user_id}</code>"
        )
        await safe_send_message(ADMIN_ID, admin_notification, disable_web_page_preview=True)
        await callback_query.message.edit_text("✅ <b>Report Submitted:</b> Our moderators have been notified to review the content.")
        await callback_query.answer("Report sent.")
    except Exception as e:
        logging.error(f"Error reporting comment {comment_id}: {e}")
        await callback_query.message.edit_text("❌ An error occurred while submitting the report.")

@dp.callback_query(F.data == "report_cancel")
async def report_cancel_callback(callback_query: types.CallbackQuery):
    await callback_query.message.edit_text("Report process cancelled.")
    await callback_query.answer("Cancelled.")

# --- Contact Request & Consent Verification ---
@dp.callback_query(F.data.startswith("req_contact_"))
async def handle_request_contact(callback_query: types.CallbackQuery):
    comm_id = int(callback_query.data.split("_")[-1])
    requester_uid = callback_query.from_user.id
    if not db:
        return
    async with db.acquire() as conn:
        async with conn.transaction():
            comm_data = await conn.fetchrow("""
                SELECT c.user_id as comm_uid, c.text, co.id as conf_id, co.user_id as conf_owner_id 
                FROM comments c 
                JOIN confessions co ON c.confession_id = co.id 
                WHERE c.id = $1
            """, comm_id)
            if not comm_data:
                await callback_query.answer("Reflection not found.", show_alert=True)
                return
            commenter_uid, conf_id, conf_owner_id = comm_data['comm_uid'], comm_data['conf_id'], comm_data['conf_owner_id']
            if requester_uid != conf_owner_id:
                await callback_query.answer("Only the author of this confession can initiate contact.", show_alert=True)
                return
            if requester_uid == commenter_uid:
                await callback_query.answer("You cannot contact yourself.", show_alert=True)
                return

            existing_req = await conn.fetchval("SELECT status FROM contact_requests WHERE comment_id = $1 AND requester_user_id = $2", comm_id, requester_uid)
            if existing_req and existing_req not in ['denied', 'failed_to_notify']:
                await callback_query.answer(f"Contact request already pending (status: {existing_req}).", show_alert=True)
                return

            req_id = await conn.fetchval("""
                INSERT INTO contact_requests (confession_id, comment_id, requester_user_id, requested_user_id, status) 
                VALUES ($1, $2, $3, $4, 'pending')
                ON CONFLICT (comment_id, requester_user_id) DO UPDATE SET status = 'pending', updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, conf_id, comm_id, requester_uid, commenter_uid)

            snippet = html.quote(comm_data['text'][:100]) if comm_data['text'] else "[Media]"
            notification_to_commenter = (
                f"🤝 <b>Contact Request from Confession Author</b>\n\n"
                f"The author of Confession #{conf_id} was touched by your reflection:\n"
                f"<i>\"{snippet}...\"</i>\n\n"
                "Would you like to share your Telegram @username with them? Your numeric User ID is never disclosed."
            )
            kbd = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Approve & Share Username", callback_data=f"approve_contact_{req_id}"),
                InlineKeyboardButton(text="❌ Deny Request", callback_data=f"deny_contact_{req_id}")
            ]])
            sent = await safe_send_message(commenter_uid, notification_to_commenter, reply_markup=kbd)
            if sent:
                await callback_query.answer("✅ Contact request sent to the commenter.", show_alert=False)
            else:
                await conn.execute("UPDATE contact_requests SET status = 'failed_to_notify' WHERE id = $1", req_id)
                await callback_query.answer("⚠️ Could not notify commenter (they may have paused the bot).", show_alert=True)

@dp.callback_query(F.data.startswith(("approve_contact_", "deny_contact_")))
async def handle_contact_response(callback_query: types.CallbackQuery):
    action, _, req_id_str = callback_query.data.partition("_contact_")
    try:
        req_id = int(req_id_str)
    except ValueError:
        await callback_query.answer("Invalid request ID.", show_alert=True)
        return

    responder_uid = callback_query.from_user.id
    if not db:
        return
    async with db.acquire() as conn:
        async with conn.transaction():
            req_data = await conn.fetchrow("SELECT * FROM contact_requests WHERE id = $1", req_id)
            if not req_data:
                await callback_query.answer("Request not found.", show_alert=True)
                return
            if responder_uid != req_data['requested_user_id']:
                await callback_query.answer("This request is not addressed to you.", show_alert=True)
                return
            if req_data['status'] != 'pending':
                await callback_query.answer(f"Request already {req_data['status']}.", show_alert=True)
                return

            author_uid = req_data['requester_user_id']
            conf_id = req_data['confession_id']

            if action == "approve":
                username = callback_query.from_user.username
                if not username:
                    try:
                        chat_info = await bot.get_chat(responder_uid)
                        username = chat_info.username
                    except Exception:
                        username = None

                if username:
                    await conn.execute("UPDATE contact_requests SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = $1", req_id)
                    notification_to_author = f"✅ <b>Contact Approved for Confession #{conf_id}!</b>\nYou can reach the commenter at: @{html.quote(username)}"
                    await callback_query.message.edit_text(callback_query.message.html_text + "\n\n-- ✅ Approved. Your username has been shared. --", reply_markup=None)
                else:
                    await conn.execute("UPDATE contact_requests SET status = 'approved_no_username', updated_at = CURRENT_TIMESTAMP WHERE id = $1", req_id)
                    notification_to_author = f"⚠️ <b>Contact Approved for Confession #{conf_id}</b>, but the commenter does not have a public @username set in Telegram."
                    await callback_query.message.edit_text(callback_query.message.html_text + "\n\n-- Approved, but you do not have a public username. --", reply_markup=None)
            else:
                await conn.execute("UPDATE contact_requests SET status = 'denied', updated_at = CURRENT_TIMESTAMP WHERE id = $1", req_id)
                notification_to_author = f"❌ The commenter for Confession #{conf_id} politely declined your contact request."
                await callback_query.message.edit_text(callback_query.message.html_text + "\n\n-- ❌ Denied. The author has been notified. --", reply_markup=None)

            await safe_send_message(author_uid, notification_to_author)
            await callback_query.answer("Response recorded.")

# --- Profile Menus & Confession Deletion Requests ---
def create_profile_pagination_keyboard(base_callback: str, current_page: int, total_pages: int):
    builder = InlineKeyboardBuilder()
    row = []
    if current_page > 1:
        row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"{base_callback}_{current_page - 1}"))
    if total_pages > 1:
        row.append(InlineKeyboardButton(text=f"Page {current_page}/{total_pages}", callback_data="noop"))
    if current_page < total_pages:
        row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"{base_callback}_{current_page + 1}"))
    if row:
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="⬅️ Back to Profile", callback_data="profile_menu_main_1"))
    return builder.as_markup()

@dp.callback_query(F.data.startswith("profile_menu_"))
async def handle_profile_menu(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    parts = callback_query.data.split("_")
    action = parts[2]
    page = int(parts[-1])

    try:
        if action == "main":
            await show_profile(user_id, callback_query)
        elif action == "confessions":
            if not db:
                await callback_query.answer("Database unavailable.")
                return
            async with db.acquire() as conn:
                total_count = await conn.fetchval("SELECT COUNT(*) FROM confessions WHERE user_id = $1", user_id) or 0
                if total_count == 0:
                    await callback_query.answer("You haven't submitted any confessions yet.", show_alert=True)
                    return

                total_pages = (total_count + 5 - 1) // 5
                page = max(1, min(page, total_pages))
                offset = (page - 1) * 5
                confessions = await conn.fetch("""
                    SELECT id, text, status, created_at, photo_file_id 
                    FROM confessions 
                    WHERE user_id = $1 
                    ORDER BY created_at DESC 
                    LIMIT 5 OFFSET $2
                """, user_id, offset)

            response_text = f"<b>📜 Your Confessions (Page {page}/{total_pages})</b>\n\n"
            builder = InlineKeyboardBuilder()
            for conf in confessions:
                snippet = html.quote(conf['text'][:60]) + ('...' if len(conf['text']) > 60 else '')
                status_emoji = {"approved": "✅", "pending": "⏳", "rejected": "❌", "deleted": "🗑️"}.get(conf['status'], "❓")
                photo_indicator = " 📷" if conf['photo_file_id'] else ""
                response_text += f"<b>ID:</b> #{conf['id']} ({status_emoji} {conf['status'].capitalize()}{photo_indicator})\n<i>\"{snippet}\"</i>\n\n"
                if conf['status'] in ['approved', 'pending']:
                    builder.row(InlineKeyboardButton(text=f"🗑️ Request Deletion #{conf['id']}", callback_data=f"req_del_conf_{conf['id']}"))

            nav_keyboard = create_profile_pagination_keyboard("profile_menu_confessions", page, total_pages)
            final_markup = builder.attach(InlineKeyboardBuilder.from_markup(nav_keyboard)).as_markup()
            await callback_query.message.edit_text(response_text, reply_markup=final_markup)

        elif action == "comments":
            if not db:
                await callback_query.answer("Database unavailable.")
                return
            async with db.acquire() as conn:
                total_count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE user_id = $1", user_id) or 0
                if total_count == 0:
                    await callback_query.answer("You haven't made any comments or reflections yet.", show_alert=True)
                    return

                total_pages = (total_count + 5 - 1) // 5
                page = max(1, min(page, total_pages))
                offset = (page - 1) * 5
                comments = await conn.fetch("""
                    SELECT id, text, sticker_file_id, animation_file_id, confession_id, created_at 
                    FROM comments 
                    WHERE user_id = $1 
                    ORDER BY created_at DESC 
                    LIMIT 5 OFFSET $2
                """, user_id, offset)

            response_text = f"<b>💬 Your Reflections (Page {page}/{total_pages})</b>\n\n"
            for comm in comments:
                if comm['text']:
                    snippet = "💬 " + html.quote(comm['text'][:60]) + ('...' if len(comm['text']) > 60 else '')
                elif comm['sticker_file_id']:
                    snippet = "[Sticker]"
                elif comm['animation_file_id']:
                    snippet = "[GIF]"
                else:
                    snippet = "[Content]"
                link = f"https://t.me/{bot_info.username}?start=view_{comm['confession_id']}" if bot_info else ""
                response_text += f"On Confession <a href='{link}'>#{comm['confession_id']}</a>:\n<i>\"{snippet}\"</i>\n\n"

            nav_keyboard = create_profile_pagination_keyboard("profile_menu_comments", page, total_pages)
            await callback_query.message.edit_text(response_text, reply_markup=nav_keyboard, disable_web_page_preview=True)

    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.warning(f"Error handling profile menu: {e}")
    finally:
        await callback_query.answer()

@dp.callback_query(F.data.startswith("req_del_conf_"))
async def request_deletion_prompt(callback_query: types.CallbackQuery):
    conf_id = int(callback_query.data.split("_")[-1])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, Request Deletion", callback_data=f"confirm_del_conf_{conf_id}")],
        [InlineKeyboardButton(text="❌ No, Cancel", callback_data="profile_menu_confessions_1")]
    ])
    await callback_query.message.edit_text(
        f"Are you sure you want to request deletion of Confession #{conf_id}? If approved by an administrator, it will be permanently removed from the channel.",
        reply_markup=keyboard
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith("confirm_del_conf_"))
async def confirm_deletion_request(callback_query: types.CallbackQuery):
    conf_id = int(callback_query.data.split("_")[-1])
    user_id = callback_query.from_user.id
    if not db:
        return
    async with db.acquire() as conn:
        try:
            conf_data = await conn.fetchrow("SELECT user_id, text, status FROM confessions WHERE id = $1", conf_id)
            if not conf_data or conf_data['user_id'] != user_id:
                await callback_query.answer("This is not your confession.", show_alert=True)
                return
            if conf_data['status'] not in ['approved', 'pending']:
                await callback_query.answer(f"Cannot delete confession with status '{conf_data['status']}'.", show_alert=True)
                return

            await conn.execute("""
                INSERT INTO deletion_requests (confession_id, user_id, status) VALUES ($1, $2, 'pending')
                ON CONFLICT (confession_id, user_id) DO NOTHING
            """, conf_id, user_id)

            snippet = html.quote(conf_data['text'][:200])
            admin_text = (
                f"🗑️ <b>New Deletion Request</b>\n\n"
                f"<b>User ID:</b> <code>{user_id}</code>\n"
                f"<b>Confession ID:</b> <code>{conf_id}</code>\n\n"
                f"<b>Content Snippet:</b>\n<i>\"{snippet}...\"</i>"
            )
            admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Approve Deletion", callback_data=f"admin_approve_delete_{conf_id}")],
                [InlineKeyboardButton(text="❌ Reject Deletion", callback_data=f"admin_reject_delete_{conf_id}")]
            ])
            await bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_keyboard)
            await callback_query.answer("✅ Deletion request sent. An admin will review it shortly.", show_alert=True)
            callback_query.data = "profile_menu_confessions_1"
            await handle_profile_menu(callback_query)

        except asyncpg.exceptions.UniqueViolationError:
            await callback_query.answer("You have already requested deletion for this confession.", show_alert=True)
        except Exception as e:
            logging.error(f"Error processing deletion request for conf {conf_id} by user {user_id}: {e}")
            await callback_query.answer("An error occurred while sending your request.", show_alert=True)

@dp.callback_query(F.data.startswith(("admin_approve_delete_", "admin_reject_delete_")))
async def admin_handle_deletion_request(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("Unauthorized.", show_alert=True)
        return

    parts = callback_query.data.split("_")
    action = parts[1]
    conf_id = int(parts[-1])
    final_status = ""

    if not db:
        return

    async with db.acquire() as conn:
        async with conn.transaction():
            req_data = await conn.fetchrow("SELECT id, user_id FROM deletion_requests WHERE confession_id = $1 AND status = 'pending'", conf_id)
            if not req_data:
                await callback_query.answer("Request not found or already processed.", show_alert=True)
                return

            if action == "approve":
                conf_to_delete = await conn.fetchrow("SELECT message_id, user_id FROM confessions WHERE id = $1", conf_id)
                await conn.execute("UPDATE deletion_requests SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP WHERE id = $1", req_data['id'])
                if conf_to_delete:
                    if conf_to_delete['message_id']:
                        try:
                            await bot.delete_message(chat_id=CHANNEL_ID, message_id=conf_to_delete['message_id'])
                        except Exception as e:
                            logging.warning(f"Could not delete channel message {conf_to_delete.get('message_id')}: {e}")
                    await conn.execute("DELETE FROM confessions WHERE id = $1", conf_id)

                await safe_send_message(req_data['user_id'], f"✅ Your request to delete Confession #{conf_id} has been approved.")
                final_status = "Approved & Deleted"
            else:
                await conn.execute("UPDATE deletion_requests SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP WHERE id = $1", req_data['id'])
                await safe_send_message(req_data['user_id'], f"❌ Your request to delete Confession #{conf_id} was rejected by the admin.")
                final_status = "Rejected"

    await callback_query.message.edit_text(callback_query.message.html_text + f"\n\n-- Deletion Request: {final_status} --", reply_markup=None)
    await callback_query.answer(f"Request {final_status}.")

# --- Privacy, Administration Contact & User Inspection Commands ---
@dp.message(Command("privacy"))
async def show_privacy(message: types.Message):
    privacy_text = (
        "<b>Privacy Information & Cryptographic Anonymity</b> 🔒\n\n"
        "▪️ <b>Zero-Identity Isolation:</b> Your numeric Telegram ID is stored securely in an isolated database and never posted publicly.\n"
        "▪️ <b>Safe Expression:</b> Confessions and comments are stripped of your Telegram handle.\n"
        "▪️ <b>Consent-Driven Contact:</b> If a confession author requests to connect, your @username is only shared with your explicit approval.\n"
        f"▪️ <b>Community Moderation:</b> Our administration (ID: <code>{ADMIN_ID}</code>) moderates submissions to keep the vault zero-doxxing and safe."
    )
    await message.answer(privacy_text)

@dp.message(Command("contact"))
async def cmd_contact_admin(message: types.Message, state: FSMContext):
    await state.set_state(ContactAdminForm.waiting_for_message)
    await message.answer(
        "✉️ <b>Contact Bot Administrators</b>\n\n"
        "Please send your private feedback, report, or inquiry below.\n"
        "Type /cancel to abort.",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(ContactAdminForm.waiting_for_message, F.text)
async def receive_admin_message(message: types.Message, state: FSMContext):
    if message.text.startswith('/cancel'):
        await state.clear()
        await message.answer("Contact message cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    user_id = message.from_user.id
    user_info = message.from_user
    message_text = message.text.strip()
    if len(message_text) < 5:
        await message.answer("Message too short (minimum 5 characters).")
        return
    if len(message_text) > 2000:
        await message.answer("Message too long (maximum 2000 characters).")
        return

    admin_message = (
        f"<b>📬 Message from User to Administration</b>\n\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<b>Username:</b> @{user_info.username if user_info.username else 'Not Set'}\n"
        f"<b>Name:</b> {html.quote(user_info.full_name or 'N/A')}\n\n"
        f"<b>Message:</b>\n{html.quote(message_text)}"
        f"\n\n---\n<i>Reply to this message in Telegram to respond directly to User ID <code>{user_id}</code>.</i>"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_message)
        await message.answer("✅ <b>Your message has been delivered to the administration!</b>", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logging.error(f"Failed forward message to admin: {e}")
        await message.answer("❌ Error sending message. Please try again later.")
    finally:
        await state.clear()

@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def handle_admin_reply(message: types.Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    replied_to = message.reply_to_message
    if not replied_to or not bot_info or not replied_to.from_user or replied_to.from_user.id != bot_info.id:
        return

    text_to_search = replied_to.html_text or html.quote(replied_to.caption or "") or ""
    match = re.search(r"User ID:\s*<code>(\d+)</code>", text_to_search, re.IGNORECASE)
    if not match:
        return

    target_user_id = int(match.group(1))
    sent = await safe_send_message(target_user_id, f"💬 <b>Official Admin Reply:</b>\n\n{html.quote(message.text or '')}")
    if sent:
        await message.reply("✅ Reply delivered to the user.")
    else:
        await message.reply("⚠️ Failed to deliver reply (user may have blocked the bot).")

@dp.message(Command("id"))
async def get_user_info_command(message: types.Message, command: CommandObject):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    if not command.args:
        await message.reply("Usage: <code>/id &lt;user_id&gt;</code>")
        return
    try:
        target_user_id = int(command.args.strip())
    except ValueError:
        await message.reply("Invalid User ID.")
        return
    info_parts = [f"ℹ️ <b>User Info for ID:</b> <code>{target_user_id}</code>\n"]
    try:
        chat_info = await bot.get_chat(target_user_id)
        info_parts.append(f"<b>Username:</b> @{html.quote(chat_info.username or 'Not Set')}")
        info_parts.append(f"<b>First Name:</b> {html.quote(chat_info.first_name or 'N/A')}")
    except Exception as e:
        info_parts.append(f"⚠️ <b>Telegram Details:</b> Could not fetch ({e})")
    if db:
        try:
            async with db.acquire() as conn:
                user_points = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", target_user_id) or 0
                conf_count = await conn.fetchval("SELECT COUNT(*) FROM confessions WHERE user_id = $1", target_user_id) or 0
                comm_count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE user_id = $1", target_user_id) or 0
                status_data = await conn.fetchrow("SELECT is_blocked, blocked_until, has_accepted_rules FROM user_status WHERE user_id = $1", target_user_id)

                info_parts.append(f"\n<b>Bot Activity:</b>\n  - <b>Aura Points:</b> 🏅 {user_points}\n  - <b>Confessions:</b> {conf_count}\n  - <b>Comments:</b> {comm_count}")
                if status_data:
                    info_parts.append(f"  - <b>Accepted Rules:</b> {'Yes' if status_data['has_accepted_rules'] else 'No'}")
                    if status_data['is_blocked']:
                        expiry = f"until {status_data['blocked_until'].strftime('%Y-%m-%d %H:%M')}" if status_data['blocked_until'] else "Permanently"
                        info_parts.append(f"  - <b>Status:</b> ❌ Blocked ({expiry})")
        except Exception as e:
            info_parts.append(f"\n❌ Error fetching database info: {e}")
    await message.reply("\n".join(info_parts))

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
            types.BotCommand(command="privacy", description="Privacy information & anonymity"),
            types.BotCommand(command="contact", description="Contact administrators"),
            types.BotCommand(command="rules", description="Zero-doxxing safety rules"),
            types.BotCommand(command="help", description="Show help and commands"),
            types.BotCommand(command="cancel", description="Cancel current action"),
        ]
        admin_commands = commands + [
            types.BotCommand(command="adminmusic", description="ADMIN: 🎵 Music Library & Moderation"),
            types.BotCommand(command="settheme", description="ADMIN: Dynamic Community Theme Switcher"),
            types.BotCommand(command="postprompt", description="ADMIN: Post daily prompt to channel"),
            types.BotCommand(command="id", description="ADMIN: Inspect user info and activity"),
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
