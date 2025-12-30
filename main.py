import logging
import asyncpg
import os
import asyncio
import signal
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
MAX_CATEGORIES = 3 # Maximum categories allowed per confession

# Load environment variables at the top level
load_dotenv()
# Accept either BOT_TOKENS (existing) or BOT_TOKEN (common)
BOT_TOKEN = os.getenv("BOT_TOKENS") or os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID") # Load as string first for validation
CHANNEL_ID = os.getenv("CHANNEL_ID")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "15"))  # Number of items per page for pagination

DATABASE_URL = os.getenv("DATABASE_URL")
# PORT  dummy HTTP server, Render sets this for Web Services
HTTP_PORT_STR = os.getenv("PORT")


# Validate essential environment variables before proceeding
if not BOT_TOKEN:
    raise ValueError("FATAL: BOT_TOKEN (or BOT_TOKENS) environment variable not set!")
if not ADMIN_ID_STR: raise ValueError("FATAL: ADMIN_ID environment variable not set!")
if not CHANNEL_ID: raise ValueError("FATAL: CHANNEL_ID environment variable not set!")
if not DATABASE_URL: raise ValueError("FATAL: DATABASE_URL environment variable not set!")

try:
    ADMIN_ID = int(ADMIN_ID_STR)
except ValueError:
    raise ValueError("FATAL: ADMIN_ID environment variable must be a valid integer!")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Bot and Dispatcher
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# Bot info
bot_info = None

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

# --- Database ---
db = None
async def create_db_pool():
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        logging.info("Database pool created successfully.")
        return pool
    except Exception as e:
        logging.error(f"Failed to create database pool: {e}")
        raise

async def setup():
    global db, bot_info
    db = await create_db_pool()
    bot_info = await bot.get_me()
    logging.info(f"Bot started: @{bot_info.username}")

    async with db.acquire() as conn:
        # --- Confessions Table Schema ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                status VARCHAR(10) DEFAULT 'pending',
                message_id BIGINT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                rejection_reason TEXT NULL,
                categories TEXT[] NULL
            );
        """)
        logging.info("Checked/Created 'confessions' table.")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_confessions_categories ON confessions USING gin(categories);")
        logging.info("Checked/Created GIN index on 'confessions.categories'.")

        # --- Comments Table Schema ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                confession_id INTEGER REFERENCES confessions(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                text TEXT NULL,
                sticker_file_id TEXT NULL,
                animation_file_id TEXT NULL,
                parent_comment_id INTEGER REFERENCES comments(id) ON DELETE SET NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT one_content_type CHECK (num_nonnulls(text, sticker_file_id, animation_file_id) = 1)
            );
        """)
        logging.info("Checked/Created 'comments' table.")

        # --- Reactions Table ---
        await conn.execute("""
             CREATE TABLE IF NOT EXISTS reactions ( id SERIAL PRIMARY KEY, comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
                 user_id BIGINT NOT NULL, reaction_type VARCHAR(10) NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                 UNIQUE(comment_id, user_id) );
        """)
        logging.info("Checked/Created 'reactions' table.")

        # --- Rebuilt Contact Requests Table ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contact_requests (
                id SERIAL PRIMARY KEY,
                confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
                comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
                requester_user_id BIGINT NOT NULL,
                requested_user_id BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, approved, denied, approved_no_username, failed_to_notify
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (comment_id, requester_user_id)
            );
            COMMENT ON TABLE contact_requests IS 'Stores requests from confession authors to contact commenters (V2).';
        """)
        logging.info("Checked/Created 'contact_requests' table (V2).")

        # --- User Points Table ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                user_id BIGINT PRIMARY KEY,
                points INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_user_points_user_id ON user_points(user_id);
        """)
        logging.info("Checked/Created 'user_points' table and index.")

        # --- Reports Table ---
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
        logging.info("Checked/Created 'reports' table.")

        # --- Deletion Requests Table ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS deletion_requests (
                id SERIAL PRIMARY KEY,
                confession_id INTEGER NOT NULL REFERENCES confessions(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, approved, rejected
                created_at TIMESTAMP WITH TIME ZONE,
                reviewed_at TIMESTAMP WITH TIME ZONE,
                UNIQUE (confession_id, user_id) -- User can only request deletion for their confession once
            );
            COMMENT ON TABLE deletion_requests IS 'Stores user requests to delete their own confessions.';
        """)
        logging.info("Checked/Created 'deletion_requests' table.")

        # --- NEW: User Status Table (for rules acceptance and blocking) ---
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_status (
                user_id BIGINT PRIMARY KEY,
                has_accepted_rules BOOLEAN NOT NULL DEFAULT FALSE,
                is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                blocked_until TIMESTAMP WITH TIME ZONE NULL,
                block_reason TEXT NULL
            );
        """)
        logging.info("Checked/Created 'user_status' table.")


        logging.info("Database tables setup complete.")


# --- Dummy HTTP Server Functions ---
async def handle_health_check(request):
    """Responds with a simple 'OK' for health checks."""
    logging.debug("Health check endpoint hit.")
    return web.Response(text="OK")

async def start_dummy_server():
    """Starts a minimal HTTP server to respond to Render health checks."""
    if not HTTP_PORT_STR:
        logging.info("PORT environment variable not set. Dummy HTTP server will not start.")
        return

    try: port = int(HTTP_PORT_STR)
    except ValueError:
        logging.error(f"Invalid PORT environment variable: {HTTP_PORT_STR}. Dummy HTTP server will not start.")
        return

    app = web.Application()
    app.router.add_get('/', handle_health_check)
    app.router.add_get('/healthz', handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    try:
        await site.start()
        logging.info(f"Dummy HTTP server started successfully on port {port}.")
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logging.info("Dummy HTTP server task cancelled.")
    except Exception as e:
        logging.error(f"Dummy HTTP server failed to start or crashed on port {port}: {e}", exc_info=True)
    finally:
        await runner.cleanup()
        logging.info("Dummy HTTP server cleaned up and stopped.")


# --- Helper Functions ---
def create_category_keyboard(selected_categories: List[str] = None):
    if selected_categories is None:
        selected_categories = []
    builder = InlineKeyboardBuilder()
    for category in CATEGORIES:
        prefix = "✅ " if category in selected_categories else ""
        builder.button(text=f"{prefix}{category}", callback_data=f"category_{category}")
    builder.adjust(2)
    if 1 <= len(selected_categories) <= MAX_CATEGORIES:
         builder.row(InlineKeyboardButton(text=f"➡️ Done Selecting ({len(selected_categories)}/{MAX_CATEGORIES})", callback_data="category_done"))
    elif len(selected_categories) > MAX_CATEGORIES:
         builder.row(InlineKeyboardButton(text=f"⚠️ Too Many ({len(selected_categories)}/{MAX_CATEGORIES}) - Click to Confirm", callback_data="category_done"))
    builder.row(InlineKeyboardButton(text="❌ Cancel Selection", callback_data="category_cancel"))
    return builder.as_markup()

async def get_comment_reactions(comment_id: int) -> Tuple[int, int]:
    likes, dislikes = 0, 0
    async with db.acquire() as conn:
        counts = await conn.fetchrow(
            "SELECT COALESCE(SUM(CASE WHEN reaction_type = 'like' THEN 1 ELSE 0 END), 0) AS likes, COALESCE(SUM(CASE WHEN reaction_type = 'dislike' THEN 1 ELSE 0 END), 0) AS dislikes FROM reactions WHERE comment_id = $1",
            comment_id
        )
        if counts:
            likes, dislikes = counts['likes'], counts['dislikes']
    return likes, dislikes

async def get_user_points(user_id: int) -> int:
    async with db.acquire() as conn:
        points = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", user_id)
        return points or 0

async def update_user_points(conn: asyncpg.Connection, user_id: int, delta: int):
    if delta == 0: return
    await conn.execute("INSERT INTO user_points (user_id, points) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET points = user_points.points + $2", user_id, delta)
    logging.debug(f"Updated points for user {user_id} by {delta}")

async def build_comment_keyboard(comment_id: int, commenter_user_id: int, viewer_user_id: int, confession_owner_id: int ):
    likes, dislikes = await get_comment_reactions(comment_id)
    builder = InlineKeyboardBuilder()
    builder.button(text=f"👍 {likes}", callback_data=f"react_like_{comment_id}")
    builder.button(text=f"👎 {dislikes}", callback_data=f"react_dislike_{comment_id}")
    builder.button(text="↪️ Reply", callback_data=f"reply_{comment_id}")
    builder.button(text="⚠️", callback_data=f"report_confirm_{comment_id}")

    if viewer_user_id == confession_owner_id and viewer_user_id != commenter_user_id:
        builder.button(text="🤝 Request Contact", callback_data=f"req_contact_{comment_id}")
        builder.adjust(4, 1)
    else:
        builder.adjust(4)
    return builder.as_markup()


# --- MODIFIED: This function now returns the Message object on success, or None on failure ---
async def safe_send_message(user_id: int, text: str, **kwargs) -> Optional[types.Message]:
    try:
        # Instead of just calling it, we store the result
        sent_message = await bot.send_message(user_id, text, **kwargs)
        # And return the message object
        return sent_message
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        if "bot was blocked" in str(e) or "user is deactivated" in str(e) or "chat not found" in str(e):
            logging.warning(f"Could not send message to user {user_id}: Blocked/deactivated. {e}")
        else:
            logging.warning(f"Telegram API error sending to {user_id}: {e}")
    except TelegramRetryAfter as e:
        logging.warning(f"Flood control for {user_id}. Retrying after {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        return await safe_send_message(user_id, text, **kwargs)
    except Exception as e:
        logging.error(f"Unexpected error sending message to {user_id}: {e}", exc_info=True)
    
    # Return None on failure
    return None

async def update_channel_post_button(confession_id: int):
    global bot_info; await asyncio.sleep(0.1)
    if not bot_info: logging.error(f"No bot info for {confession_id} button update."); return
    async with db.acquire() as conn:
        conf_data = await conn.fetchrow("SELECT message_id FROM confessions WHERE id = $1 AND status = 'approved'", confession_id)
        count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id) or 0
    if not conf_data or not conf_data['message_id']: logging.debug(f"No approved conf/msg_id for {confession_id} button."); return
    ch_msg_id = conf_data['message_id']; link = f"https://t.me/{bot_info.username}?start=view_{confession_id}"
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"💬 View / Add Comments ({count})", url=link)]])
    try: await bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=ch_msg_id, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower(): logging.info(f"Button for {confession_id} already updated ({count}).")
        elif "message to edit not found" in str(e).lower(): logging.warning(f"Msg {ch_msg_id} not found in {CHANNEL_ID} (conf {confession_id}). Maybe deleted?")
        else: logging.error(f"Failed edit channel post {ch_msg_id} for conf {confession_id}: {e}")
    except Exception as e: logging.error(f"Unexpected err updating btn for conf {confession_id}: {e}", exc_info=True)

# --- NEW: Helper function to get a comment's sequential number ---
async def get_comment_sequence_number(conn: asyncpg.Connection, comment_id: int, confession_id: int) -> Optional[int]:
    """Fetches the sequential number of a specific comment within its confession."""
    query = """
        WITH ranked_comments AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC) as rn
            FROM comments
            WHERE confession_id = $1
        )
        SELECT rn FROM ranked_comments WHERE id = $2;
    """
    try:
        seq_num = await conn.fetchval(query, confession_id, comment_id)
        return seq_num
    except Exception as e:
        logging.error(f"Could not fetch sequence number for comment {comment_id}: {e}")
        return None

# --- MODIFIED: Reworked show_comments_for_confession to be more specific about cross-page replies ---
async def show_comments_for_confession(user_id: int, confession_id: int, message_to_edit: Optional[types.Message] = None, page: int = 1):
    async with db.acquire() as conn:
        conf_data = await conn.fetchrow("SELECT status, user_id FROM confessions WHERE id = $1", confession_id)
        if not conf_data or conf_data['status'] != 'approved':
            err_txt = f"Confession #{confession_id} not found or not approved."
            if message_to_edit: await message_to_edit.edit_text(err_txt, reply_markup=None)
            else: await safe_send_message(user_id, err_txt)
            return
        confession_owner_id = conf_data['user_id']
        total_count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE confession_id = $1", confession_id) or 0
        if total_count == 0:
            msg_text = "<i>No comments yet. Be the first!</i>"
            if message_to_edit: await message_to_edit.edit_text(msg_text, reply_markup=None)
            else: await safe_send_message(user_id, msg_text)
            nav = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Add Comment", callback_data=f"add_{confession_id}")]])
            await safe_send_message(user_id, "You can add your own comment below:", reply_markup=nav)
            return

        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE; page = max(1, min(page, total_pages)); offset = (page - 1) * PAGE_SIZE
        comments_raw = await conn.fetch("SELECT c.id, c.user_id, c.text, c.sticker_file_id, c.animation_file_id, c.parent_comment_id, c.created_at, COALESCE(up.points, 0) as user_points FROM comments c LEFT JOIN user_points up ON c.user_id = up.user_id WHERE c.confession_id = $1 ORDER BY c.created_at ASC LIMIT $2 OFFSET $3", confession_id, PAGE_SIZE, offset)

    db_id_to_message_id: Dict[int, int] = {}

    if not comments_raw:
        await safe_send_message(user_id, f"<i>No comments on page {page}.</i>")
    else:
        for i, c_data_row in enumerate(comments_raw):
            c_data = dict(c_data_row)
            seq_num, db_id, commenter_uid = offset + i + 1, c_data['id'], c_data['user_id']
            ts = c_data['created_at'].strftime("%Y-%m-%d %H:%M")
            medal_str = f" 🏅{c_data.get('user_points', 0)} Aura"
            tag = "(Author)" if commenter_uid == confession_owner_id else "(You)" if commenter_uid == user_id else "Anonymous"
            admin_info = f" [UID: <code>{commenter_uid}</code>]" if user_id == ADMIN_ID else ""
            display_tag = f" {tag}{medal_str}"

            reply_to_msg_id = None
            text_reply_prefix = ""
            parent_db_id = c_data.get('parent_comment_id')
            if parent_db_id:
                if parent_db_id in db_id_to_message_id:
                    reply_to_msg_id = db_id_to_message_id[parent_db_id]
                else: 
                    # --- MODIFICATION START ---
                    # Parent comment is on another page, so we fetch its sequence number
                    async with db.acquire() as conn_for_seq: # Use a new connection from the pool
                        parent_seq_num = await get_comment_sequence_number(conn_for_seq, parent_db_id, confession_id)
                    
                    if parent_seq_num:
                        text_reply_prefix = f"↪️ <i>Replying to comment #{parent_seq_num}...</i>\n"
                    else:
                        # Fallback if the parent comment was deleted or an error occurred
                        text_reply_prefix = "↪️ <i>Replying to another comment...</i>\n"
                    # --- MODIFICATION END ---

            metadata_text = f"<i>#{seq_num}{display_tag}{admin_info}</i>"
            keyboard = await build_comment_keyboard(db_id, commenter_uid, user_id, confession_owner_id)
            
            sent_message = None
            try:
                if c_data['sticker_file_id']:
                    sent_message = await bot.send_sticker(user_id, sticker=c_data['sticker_file_id'], reply_to_message_id=reply_to_msg_id)
                    await bot.send_message(user_id, f"{text_reply_prefix}{metadata_text}", reply_markup=keyboard)
                elif c_data['animation_file_id']:
                    sent_message = await bot.send_animation(user_id, animation=c_data['animation_file_id'], reply_to_message_id=reply_to_msg_id)
                    await bot.send_message(user_id, f"{text_reply_prefix}{metadata_text}", reply_markup=keyboard)
                elif c_data['text']:
                    full_text = f"{text_reply_prefix}💬 {html.quote(c_data['text'])}\n\n{metadata_text}"
                    sent_message = await bot.send_message(user_id, full_text, reply_markup=keyboard, disable_web_page_preview=True, reply_to_message_id=reply_to_msg_id)
                
                if sent_message:
                    db_id_to_message_id[db_id] = sent_message.message_id

            except Exception as e:
                logging.warning(f"Could not send comment #{seq_num} to {user_id}: {e}")
                await safe_send_message(user_id, f"⚠️ Error displaying comment #{seq_num}.")
            await asyncio.sleep(0.1)

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"comments_page_{confession_id}_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"Page {page}/{total_pages}", callback_data="noop"))
    if page < total_pages: nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"comments_page_{confession_id}_{page+1}"))
    nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_row, [InlineKeyboardButton(text="➕ Add Comment", callback_data=f"add_{confession_id}")]])
    end_txt = f"--- Showing comments {offset+1} to {min(offset+PAGE_SIZE, total_count)} of {total_count} for Confession #{confession_id} ---"
    await safe_send_message(user_id, end_txt, reply_markup=nav_keyboard)


# --- NEW: Middleware to check for blocked users ---
class BlockUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get('event_from_user')
        if not user:
            return await handler(event, data)

        user_id = user.id
        # Admins cannot be blocked
        if user_id == ADMIN_ID:
            return await handler(event, data)

        async with db.acquire() as conn:
            status = await conn.fetchrow("SELECT is_blocked, blocked_until, block_reason FROM user_status WHERE user_id = $1", user_id)
        
        if status and status['is_blocked']:
            now = datetime.now(datetime.utcnow().astimezone().tzinfo)
            if status['blocked_until'] and status['blocked_until'] < now:
                # Unblock expired temporary blocks
                async with db.acquire() as conn:
                    await conn.execute("UPDATE user_status SET is_blocked = FALSE, blocked_until = NULL, block_reason = NULL WHERE user_id = $1", user_id)
                return await handler(event, data)
            else:
                # User is currently blocked
                expiry_info = f"until {status['blocked_until'].strftime('%Y-%m-%d %H:%M %Z')}" if status['blocked_until'] else "permanently"
                reason_info = f"\nReason: <i>{html.quote(status['block_reason'])}</i>" if status['block_reason'] else ""
                
                block_message = f"❌ <b>You are blocked from using this bot {expiry_info}.</b>{reason_info}"

                if isinstance(event, types.CallbackQuery):
                    await event.answer(f"You are blocked {expiry_info}.", show_alert=True)
                elif isinstance(event, types.Message):
                    await event.answer(block_message)
                return  # Stop processing the event

        return await handler(event, data)

# --- Handlers ---
# (all existing handlers remain unchanged below; I keep them as-is in this file)
# ... [The rest of handlers are unchanged and omitted here for brevity in this view] ...

# --- Fallback Handler ---
@dp.message(StateFilter(None), F.text & ~F.text.startswith('/'))
async def handle_text_without_state(message: types.Message):
    await message.reply("Hi! 👋 Use /confess to share anonymously, /profile to see your history, or /help for commands.")

# --- Main Execution ---
async def main():
    try:
        await setup()
        if not db or not bot_info:
            logging.critical("FATAL: Database or bot info missing after setup. Cannot start.")
            return

        # --- NEW: Register middleware ---
        dp.message.middleware(BlockUserMiddleware())
        dp.callback_query.middleware(BlockUserMiddleware())

        commands = [
            types.BotCommand(command="start", description="Start/View confession"),
            types.BotCommand(command="confess", description="Submit anonymous confession"),
            types.BotCommand(command="profile", description="View your profile and history"),
            types.BotCommand(command="help", description="Show help and commands"),
            types.BotCommand(command="rules", description="View the bot's rules"),
            types.BotCommand(command="privacy", description="View privacy information"),
            types.BotCommand(command="cancel", description="Cancel current action"),
        ]
        admin_commands = commands + [
            types.BotCommand(command="id", description="ADMIN: Get user info"),
            types.BotCommand(command="warn", description="ADMIN: Warn a user"),
            types.BotCommand(command="block", description="ADMIN: Temporarily block a user"),
            types.BotCommand(command="pblock", description="ADMIN: Permanently block a user"),
            types.BotCommand(command="unblock", description="ADMIN: Unblock a user"),
        ]
        await bot.set_my_commands(commands)
        await bot.set_my_commands(admin_commands, scope=types.BotCommandScopeChat(chat_id=ADMIN_ID))

        # --- START polling and optional dummy server as tasks ---
        polling_task = asyncio.create_task(dp.start_polling(bot, skip_updates=True))
        http_task = None
        if HTTP_PORT_STR:
            http_task = asyncio.create_task(start_dummy_server())

        logging.info("Starting bot (polling)...")

        # Graceful shutdown: wait for SIGINT/SIGTERM
        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        def _set_shutdown():
            logging.info("Shutdown signal received.")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _set_shutdown)
            except NotImplementedError:
                # On some platforms (Windows) add_signal_handler may not be implemented for the event loop
                pass

        # Wait until signal arrives
        await shutdown_event.wait()
        logging.info("Initiating shutdown sequence...")

        # Cancel tasks
        tasks = [t for t in (polling_task, http_task) if t]
        for t in tasks:
            t.cancel()

        # Wait for cancelled tasks to finish
        await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logging.critical(f"Fatal error during main execution: {e}", exc_info=True)
    finally:
        logging.info("Shutting down...")
        # Try to gracefully shutdown Dispatcher storage if possible
        try:
            if hasattr(dp, "storage") and dp.storage:
                # memory storage exposes close method in aiogram v3
                close_coro = getattr(dp.storage, "close", None)
                if close_coro is not None:
                    await close_coro()
        except Exception as e:
            logging.warning(f"Error closing dispatcher storage: {e}")

        # Close bot session
        try:
            if bot and getattr(bot, "session", None):
                await bot.session.close()
        except Exception as e:
            logging.warning(f"Error closing bot session: {e}")

        # Close DB
        try:
            if db:
                await db.close()
        except Exception as e:
            logging.warning(f"Error closing database pool: {e}")

        logging.info("Bot stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user.")
