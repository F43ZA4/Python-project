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
BANNED_WORDS = ["scam", "nude", "hack", "t.me/", "telegram.me"]

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "15"))
DATABASE_URL = os.getenv("DATABASE_URL")
HTTP_PORT_STR = os.getenv("PORT")

if not BOT_TOKEN or not ADMIN_ID_STR or not CHANNEL_ID or not DATABASE_URL:
    raise ValueError("FATAL: Missing Environment Variables!")

ADMIN_ID = int(ADMIN_ID_STR)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
db = None
bot_info = None

# --- Reputation System ---
def get_reputation_title(points: int) -> str:
    if points >= 500: return "Legend 🏆"
    if points >= 201: return "Wise Elder 🧙‍♂️"
    if points >= 51: return "Truth Teller 🗣️"
    if points >= 0: return "Newbie 🌱"
    return "Troublemaker 💀"

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

# --- Database & Middleware ---
async def setup_db():
    global db, bot_info
    db = await asyncpg.create_pool(DATABASE_URL)
    bot_info = await bot.get_me()
    async with db.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS confessions (id SERIAL PRIMARY KEY, text TEXT, user_id BIGINT, status VARCHAR(10) DEFAULT 'pending', message_id BIGINT, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, categories TEXT[]);
            CREATE TABLE IF NOT EXISTS comments (id SERIAL PRIMARY KEY, confession_id INTEGER REFERENCES confessions(id) ON DELETE CASCADE, user_id BIGINT, text TEXT, sticker_file_id TEXT, animation_file_id TEXT, parent_comment_id INTEGER, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS user_status (user_id BIGINT PRIMARY KEY, has_accepted_rules BOOLEAN DEFAULT FALSE, is_blocked BOOLEAN DEFAULT FALSE, blocked_until TIMESTAMP WITH TIME ZONE, block_reason TEXT);
            CREATE TABLE IF NOT EXISTS user_points (user_id BIGINT PRIMARY KEY, points INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS reactions (id SERIAL PRIMARY KEY, comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE, user_id BIGINT, reaction_type VARCHAR(10), UNIQUE(comment_id, user_id));
        """)

class BlockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user:
            async with db.acquire() as conn:
                status = await conn.fetchrow("SELECT is_blocked, blocked_until FROM user_status WHERE user_id = $1", user.id)
                if status and status['is_blocked']:
                    return await event.answer("🚫 You are currently blocked.")
        return await handler(event, data)

dp.message.outer_middleware(BlockMiddleware())
# ==========================================
# MODULE 5: CONFESSION SYSTEM HANDLERS
# ==========================================

@dp.message(Command("confess"))
async def cmd_confess(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with db.acquire() as conn:
        status = await conn.fetchrow("SELECT has_accepted_rules FROM user_status WHERE user_id = $1", user_id)
        if not status or not status['has_accepted_rules']:
            return await message.answer("⚠️ You must accept the /rules before confessing.")
    
    # Category Selection
    builder = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        builder.button(text=cat, callback_data=f"cat_select_{cat}")
    builder.button(text="✅ Done Selecting", callback_data="cat_done")
    builder.adjust(2)
    
    await state.set_state(ConfessionForm.selecting_categories)
    await state.update_data(selected_cats=[])
    await message.answer("Select up to 3 categories for your confession:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("cat_select_"), ConfessionForm.selecting_categories)
async def process_cat_selection(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_cats", [])
    cat = cb.data.split("_")[2]
    
    if cat in selected:
        selected.remove(cat)
        await cb.answer(f"Removed {cat}")
    elif len(selected) < MAX_CATEGORIES:
        selected.append(cat)
        await cb.answer(f"Added {cat}")
    else:
        return await cb.answer("Max 3 categories allowed!", show_alert=True)
    
    await state.update_data(selected_cats=selected)

@dp.callback_query(F.data == "cat_done", ConfessionForm.selecting_categories)
async def cat_selection_done(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(ConfessionForm.waiting_for_text)
    await cb.message.edit_text("Now, type your confession. It will be posted anonymously once approved.")

@dp.message(ConfessionForm.waiting_for_text)
async def handle_confession_text(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 10:
        return await message.answer("Your confession is too short. Please add more detail.")
    
    if any(word in message.text.lower() for word in BANNED_WORDS):
        return await message.answer("❌ Your confession contains prohibited links or words.")

    data = await state.get_data()
    cats = data.get("selected_cats", ["Other"])
    
    async with db.acquire() as conn:
        cid = await conn.fetchval(
            "INSERT INTO confessions (text, user_id, categories, status) VALUES ($1, $2, $3, 'pending') RETURNING id",
            message.text, message.from_user.id, cats
        )
    
    await state.clear()
    await message.answer(f"✅ Confession #{cid} submitted for review.")
    
    # Notify Admin
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data=f"admin_app_{cid}")
    kb.button(text="❌ Reject", callback_data=f"admin_rej_{cid}")
    await bot.send_message(ADMIN_ID, f"📑 <b>New Review #{cid}</b>\nCats: {', '.join(cats)}\n\n{message.text}", reply_markup=kb.as_markup())

# ==========================================
# MODULE 6: COMMENT & REACTION SYSTEM
# ==========================================

async def get_comment_reactions(comment_id: int):
    async with db.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE reaction_type = 'like') as likes,
                COUNT(*) FILTER (WHERE reaction_type = 'dislike') as dislikes
            FROM reactions WHERE comment_id = $1
        """, comment_id)
        return row['likes'], row['dislikes']

async def build_comment_keyboard(comment_id, commenter_uid, viewer_uid, owner_uid):
    likes, dislikes = await get_comment_reactions(comment_id)
    builder = InlineKeyboardBuilder()
    builder.button(text=f"👍 {likes}", callback_data=f"re_like_{comment_id}")
    builder.button(text=f"👎 {dislikes}", callback_data=f"re_dis_{comment_id}")
    builder.button(text="↪️ Reply", callback_data=f"com_reply_{comment_id}")
    
    if viewer_uid == owner_uid and viewer_uid != commenter_uid:
        builder.button(text="🤝 Request Contact", callback_data=f"contact_req_{comment_id}")
    
    if viewer_uid == ADMIN_ID:
        builder.button(text="🗑️ Delete/Warn", callback_data=f"admin_warn_delete_{comment_id}")
    
    builder.adjust(3, 1)
    return builder.as_markup()

async def show_comments_for_confession(user_id, confession_id, page=1):
    async with db.acquire() as conn:
        conf = await conn.fetchrow("SELECT user_id, status FROM confessions WHERE id = $1", confession_id)
        if not conf or conf['status'] != 'approved': return
        
        owner_id = conf['user_id']
        offset = (page - 1) * PAGE_SIZE
        
        comments = await conn.fetch("""
            SELECT c.*, COALESCE(up.points, 0) as pts 
            FROM comments c 
            LEFT JOIN user_points up ON c.user_id = up.user_id 
            WHERE c.confession_id = $1 ORDER BY c.created_at ASC LIMIT $2 OFFSET $3
        """, confession_id, PAGE_SIZE, offset)

        if not comments and page == 1:
            return await bot.send_message(user_id, "💬 No comments yet. Be the first!")

        for c in comments:
            pts = c['pts']
            title = get_reputation_title(pts)
            tag = "(Author)" if c['user_id'] == owner_id else "(You)" if c['user_id'] == user_id else "Anonymous"
            
            # --- FIXED: Admin Metadata (No Parse Error) ---
            admin_tag = f" [UID: {c['user_id']}]" if user_id == ADMIN_ID else ""
            meta = f"<i>{tag} | {pts} {title}{admin_tag}</i>"
            
            kb = await build_comment_keyboard(c['id'], c['user_id'], user_id, owner_id)
            
            if c['text']:
                await bot.send_message(user_id, f"💬 {html.quote(c['text'])}\n\n{meta}", reply_markup=kb)
            elif c['sticker_file_id']:
                await bot.send_sticker(user_id, c['sticker_file_id'])
                await bot.send_message(user_id, meta, reply_markup=kb)

# --- Trending Command ---
@dp.message(Command("hot"))
async def cmd_hot(message: types.Message):
    async with db.acquire() as conn:
        hot = await conn.fetch("""
            SELECT c.id, c.text, COUNT(com.id) as cc 
            FROM confessions c JOIN comments com ON c.id = com.confession_id 
            WHERE c.status = 'approved' AND c.created_at > NOW() - INTERVAL '7 days'
            GROUP BY c.id ORDER BY cc DESC LIMIT 5
        """)
    if not hot: return await message.answer("No hot topics this week!")
    res = "<b>🔥 Trending Discussions</b>\n\n"
    for r in hot:
        res += f"#{r['id']} ({r['cc']} 💬)\n{html.quote(r['text'][:50])}...\n/start view_{r['id']}\n\n"
    await message.answer(res)
# ==========================================
# MODULE 7: ADMIN ACTIONS & REACTIONS
# ==========================================

@dp.callback_query(F.data.startswith("admin_app_"))
async def approve_confession(cb: types.CallbackQuery):
    cid = int(cb.data.split("_")[2])
    async with db.acquire() as conn:
        data = await conn.fetchrow("UPDATE confessions SET status = 'approved' WHERE id = $1 RETURNING text, user_id", cid)
    
    if data:
        post_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Browse Comments", url=f"https://t.me/{bot_info.username}?start=view_{cid}")
        ]])
        msg = await bot.send_message(CHANNEL_ID, f"<b>Confession #{cid}</b>\n\n{data['text']}", reply_markup=post_kb)
        
        async with db.acquire() as conn:
            await conn.execute("UPDATE confessions SET message_id = $1 WHERE id = $2", msg.message_id, cid)
            await conn.execute("UPDATE user_points SET points = points + $1 WHERE user_id = $2", POINTS_PER_CONFESSION, data['user_id'])
        
        await cb.message.edit_text(f"✅ Approved #{cid}")
        await safe_send_message(data['user_id'], f"🎉 Your confession #{cid} was approved!")

@dp.callback_query(F.data.startswith("re_"))
async def handle_reactions(cb: types.CallbackQuery):
    _, r_type, c_id = cb.data.split("_")
    c_id = int(c_id)
    r_type = "like" if r_type == "like" else "dislike"
    
    async with db.acquire() as conn:
        # Check existing
        existing = await conn.fetchval("SELECT reaction_type FROM reactions WHERE comment_id = $1 AND user_id = $2", c_id, cb.from_user.id)
        
        if existing == r_type:
            await conn.execute("DELETE FROM reactions WHERE comment_id = $1 AND user_id = $2", c_id, cb.from_user.id)
            await cb.answer("Reaction removed")
        else:
            await conn.execute("""
                INSERT INTO reactions (comment_id, user_id, reaction_type) 
                VALUES ($1, $2, $3) 
                ON CONFLICT (comment_id, user_id) DO UPDATE SET reaction_type = $3
            """, c_id, cb.from_user.id, r_type)
            await cb.answer(f"You {r_type}d this")

    # Update UI
    likes, dislikes = await get_comment_reactions(c_id)
    # Note: For efficiency, in a full production bot, you'd only edit the reply_markup here
    await cb.answer()

@dp.callback_query(F.data.startswith("admin_warn_delete_"))
async def admin_delete_comment(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    cid = int(cb.data.split("_")[3])
    async with db.acquire() as conn:
        target = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", cid)
        if target:
            await conn.execute("DELETE FROM comments WHERE id = $1", cid)
            await conn.execute("UPDATE user_points SET points = points - 10 WHERE user_id = $1", target['user_id'])
            await cb.message.delete()
            await safe_send_message(target['user_id'], "⚠️ Your comment was deleted by admin. -10 Aura.")
            await cb.answer("Comment deleted & user penalized", show_alert=True)

# ==========================================
# MODULE 8: CONTACT REQUESTS & PROFILE
# ==========================================

@dp.callback_query(F.data.startswith("contact_req_"))
async def request_contact(cb: types.CallbackQuery):
    c_id = int(cb.data.split("_")[2])
    async with db.acquire() as conn:
        commenter = await conn.fetchrow("SELECT user_id FROM comments WHERE id = $1", c_id)
    
    if commenter:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Share Username", callback_data=f"share_yes_{cb.from_user.id}")
        kb.button(text="❌ Decline", callback_data="share_no")
        await safe_send_message(commenter['user_id'], f"👤 The author of the confession wants to connect with you. Share your username?", reply_markup=kb.as_markup())
        await cb.answer("Request sent to the commenter!", show_alert=True)

@dp.message(Command("id"))
async def cmd_view_id(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args: return await message.answer("Usage: /id [user_id]")
    
    uid = int(command.args)
    async with db.acquire() as conn:
        pts = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", uid) or 0
        status = await conn.fetchrow("SELECT * FROM user_status WHERE user_id = $1", uid)
    
    title = get_reputation_title(pts)
    report = f"👤 <b>User Profile:</b> {uid}\n🏅 <b>Aura:</b> {pts} ({title})\n"
    report += f"🚫 <b>Blocked:</b> {'Yes' if status and status['is_blocked'] else 'No'}"
    await message.answer(report)

# ==========================================
# MODULE 9: SERVER STARTUP
# ==========================================

async def handle_hc(request):
    return web.Response(text="Bot is running smoothly.")

async def main():
    await setup_db()
    
    # Set Bot Commands
    await bot.set_my_commands([
        types.BotCommand(command="start", description="Start the bot"),
        types.BotCommand(command="confess", description="Submit a confession"),
        types.BotCommand(command="hot", description="Trending confessions"),
        types.BotCommand(command="rules", description="View rules"),
        types.BotCommand(command="profile", description="View your aura")
    ])

    # Health Check Server for Render
    app = web.Application()
    app.router.add_get("/", handle_hc)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
    asyncio.create_task(site.start())

    logging.info("Bot is now online.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")

