import os
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F, html
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from aiohttp import web
import asyncpg

# Logging configuration
logging.basicConfig(level=logging.INFO)

# --- ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CHANNEL_ID = os.getenv("CHANNEL_ID")
# This string is cleaned in the next step to support multi-admin via Render
RAW_ADMIN_IDS = os.getenv("ADMIN_ID", "") 

# --- DATABASE SETUP ---
async def setup_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS confessions (
            id SERIAL PRIMARY KEY,
            text TEXT,
            user_id BIGINT,
            categories TEXT[],
            status TEXT DEFAULT 'pending',
            rejection_reason TEXT,
            message_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_points (
            user_id BIGINT PRIMARY KEY,
            points INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            confession_id INTEGER REFERENCES confessions(id),
            user_id BIGINT,
            text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reactions (
            id SERIAL PRIMARY KEY,
            comment_id INTEGER REFERENCES comments(id),
            user_id BIGINT,
            reaction_type TEXT,
            UNIQUE(comment_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS user_status (
            user_id BIGINT PRIMARY KEY,
            is_blocked BOOLEAN DEFAULT FALSE,
            blocked_until TIMESTAMP,
            block_reason TEXT
        );
    ''')
    await conn.close()
    logging.info("Database tables verified.")

# Database connection helper
async def get_db_pool():
    return await asyncpg.create_pool(DATABASE_URL)
# ==========================================
# MODULE 2: BOT CONFIG & FSM
# ==========================================

# Initialize Bot and Dispatcher
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# --- MULTI-ADMIN PARSING ---
# This converts your Render string "123, 456" into a usable Python list [123, 456]
ADMIN_IDS = []
for item in RAW_ADMIN_IDS.split(","):
    item = item.strip()
    if item.lstrip('-').isdigit():  # Supports both User IDs and Group IDs (starting with -)
        ADMIN_IDS.append(int(item))

def is_admin(user_id: int) -> bool:
    """Helper to check if a user is an admin."""
    return user_id in ADMIN_IDS

# --- FSM STATES ---
class ConfessionForm(StatesGroup):
    selecting_categories = State()
    waiting_for_text = State()

class CommentForm(StatesGroup):
    waiting_for_comment = State()

# --- CONSTANTS ---
CATEGORIES = ["Love 💖", "School 📚", "Funny 😂", "Deep 🌊", "Random 🎲"]
MAX_CATEGORIES = 3
BANNED_WORDS = ["http", "t.me/", "joinchat", "bit.ly"] # Simple spam filter
# ==========================================
# MODULE 3: START LOGIC & WELCOME
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Handles the /start command and deep-linking for specific posts."""
    user_id = message.from_user.id
    
    # Check for deep-linking (e.g., /start view_123)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("view_"):
        conf_id = int(args[1].split("_")[1])
        return await show_confession_details(message, conf_id)

    # Register user in points table if not exists
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_points (user_id, points) VALUES ($1, 0) ON CONFLICT DO NOTHING",
            user_id
        )
    await pool.close()

    welcome_text = (
        f"👋 <b>Welcome to MWU CONFESSION!</b>\n\n"
        f"This is your anonymous space to share thoughts and secrets within the community.\n\n"
        f"📜 <b>Commands:</b>\n"
        f"/confess - Share a secret\n"
        f"/hot - See trending posts\n"
        f"/profile - Check your Aura points\n"
        f"/rules - Read our guidelines"
    )
    
    # Main Menu Keyboard
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Write Confession", callback_data="start_confession")
    kb.button(text="🔥 Trending", callback_data="view_hot")
    kb.button(text="👤 My Profile", callback_data="view_profile")
    kb.adjust(1)

    await message.answer(welcome_text, reply_markup=kb.as_markup())

@dp.message(Command("rules"))
async def cmd_rules(message: types.Message):
    rules = (
        "⚖️ <b>Community Rules:</b>\n"
        "1. No hate speech or bullying.\n"
        "2. No leaking personal phone numbers.\n"
        "3. No spam or advertising.\n"
        "<i>Violators will be blocked from using the bot.</i>"
    )
    await message.answer(rules)
# ==========================================
# MODULE 4: CONFESSION SUBMISSION (USER)
# ==========================================

@dp.callback_query(F.data == "start_confession")
@dp.message(Command("confess"))
async def start_confess(event: types.Message | types.CallbackQuery, state: FSMContext):
    """Initializes category selection."""
    # Handle both button clicks and commands
    message = event if isinstance(event, types.Message) else event.message
    
    builder = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        builder.button(text=cat, callback_data=f"sel_cat_{cat}")
    builder.button(text="✅ Done Selecting", callback_data="cats_complete")
    builder.adjust(2)
    
    await state.set_state(ConfessionForm.selecting_categories)
    await state.update_data(chosen_cats=[])
    
    prompt = "<b>Step 1: Choose Categories</b>\nSelect up to 3 categories for your confession:"
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(prompt, reply_markup=builder.as_markup())
    else:
        await message.answer(prompt, reply_markup=builder.as_markup())

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
            return await cb.answer(f"Limit: {MAX_CATEGORIES} categories!", show_alert=True)
        chosen.append(cat)
        await cb.answer(f"Added {cat}")

    await state.update_data(chosen_cats=chosen)
    cats_str = ", ".join(chosen) if chosen else "None"
    
    # Update message to show current selection
    try:
        await cb.message.edit_text(
            f"<b>Step 1: Choose Categories</b>\nSelected: <i>{cats_str}</i>\n\nPick up to 3:",
            reply_markup=cb.message.reply_markup
        )
    except:
        pass

@dp.callback_query(F.data == "cats_complete", ConfessionForm.selecting_categories)
async def categories_done(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("chosen_cats"):
        return await cb.answer("Please select at least one category!", show_alert=True)
    
    await state.set_state(ConfessionForm.waiting_for_text)
    await cb.message.edit_text(
        "<b>Step 2: Write your confession</b>\n"
        "Type your secret below. (Min 10 characters)\n\n"
        "<i>Your identity is 100% anonymous.</i>"
    )

@dp.message(ConfessionForm.waiting_for_text)
async def handle_confession_text(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 10:
        return await message.answer("❌ Your confession is too short. Please add more detail.")

    # Check for banned words/links
    if any(word in message.text.lower() for word in BANNED_WORDS):
        return await message.answer("⚠️ Your message contains forbidden links or words. Please remove them.")

    data = await state.get_data()
    chosen_cats = data.get("chosen_cats")
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        conf_id = await conn.fetchval(
            "INSERT INTO confessions (text, user_id, categories, status) VALUES ($1, $2, $3, 'pending') RETURNING id",
            message.text, message.from_user.id, chosen_cats
        )
    await pool.close()

    await state.clear()
    await message.answer(f"✅ <b>Success!</b>\nYour confession #{conf_id} has been sent to admins for review.")

    # This is where the Admin Notification will trigger in the next step
    await notify_admins_of_new_submission(conf_id, message.text, chosen_cats)
# ==========================================
# MODULE 5: ADMIN NOTIFICATIONS & MODERATION
# ==========================================

async def notify_admins_of_new_submission(conf_id, text, categories):
    """Sends the approval request to every admin in the ADMIN_IDS list."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"adm_app_{conf_id}")
    builder.button(text="❌ Reject", callback_data=f"adm_rej_{conf_id}")
    builder.adjust(2)

    notification_text = (
        f"🆕 <b>New Submission #{conf_id}</b>\n"
        f"📂 Categories: {', '.join(categories)}\n\n"
        f"{html.quote(text)}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id, 
                notification_text, 
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.warning(f"Could not notify admin {admin_id}: {e}")

@dp.callback_query(F.data.startswith("adm_app_"))
async def handle_approval(cb: types.CallbackQuery):
    conf_id = int(cb.data.split("_")[2])
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Get confession details
        conf = await conn.fetchrow(
            "SELECT text, categories, user_id FROM confessions WHERE id = $1", 
            conf_id
        )
        
        if not conf:
            return await cb.answer("Confession not found.")

        # 1. Update status in DB
        await conn.execute("UPDATE confessions SET status = 'approved' WHERE id = $1", conf_id)
        
        # 2. Reward User with Aura Points (e.g., +10 for an approved post)
        await conn.execute(
            "INSERT INTO user_points (user_id, points) VALUES ($1, 10) "
            "ON CONFLICT (user_id) DO UPDATE SET points = user_points.points + 10",
            conf['user_id']
        )

    # 3. Post to the Public Channel
    post_text = (
        f"<b>Confession #{conf_id}</b>\n"
        f"📂 {', '.join(conf['categories'])}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"{conf['text']}\n\n"
        f"💬 <a href='https://t.me/{ (await bot.get_me()).username }?start=view_{conf_id}'>Comment & React</a>"
    )
    
    try:
        sent_msg = await bot.send_message(CHANNEL_ID, post_text)
        # Store message_id to link comments later
        async with pool.acquire() as conn:
            await conn.execute("UPDATE confessions SET message_id = $1 WHERE id = $2", sent_msg.message_id, conf_id)
    except Exception as e:
        logging.error(f"Channel post failed: {e}")

    await pool.close()
    await cb.message.edit_text(f"✅ Approved & Posted #{conf_id}\n(Approved by {cb.from_user.first_name})")
    await cb.answer("Post Published!")

@dp.callback_query(F.data.startswith("adm_rej_"))
async def handle_rejection(cb: types.CallbackQuery):
    conf_id = int(cb.data.split("_")[2])
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE confessions SET status = 'rejected' WHERE id = $1", conf_id)
    await pool.close()
    
    await cb.message.edit_text(f"❌ Rejected #{conf_id}")
    await cb.answer("Post Rejected")
# ==========================================
# MODULE 6: COMMENTS & REACTIONS
# ==========================================

async def show_confession_details(message: types.Message, conf_id: int):
    """Displays a specific confession and its comments."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        conf = await conn.fetchrow("SELECT * FROM confessions WHERE id = $1 AND status = 'approved'", conf_id)
        if not conf:
            return await message.answer("❌ This confession doesn't exist or hasn't been approved yet.")
        
        comments = await conn.fetch(
            "SELECT * FROM comments WHERE confession_id = $1 ORDER BY created_at ASC", conf_id
        )

    response = (
        f"<b>Confession #{conf_id}</b>\n"
        f"📂 {', '.join(conf['categories'])}\n"
        f"━━━━━━━━━━━━━━\n\n"
        f"{conf['text']}\n\n"
        f"💬 <b>Comments ({len(comments)}):</b>\n"
    )

    if not comments:
        response += "<i>No comments yet. Be the first!</i>"
    else:
        for i, c in enumerate(comments, 1):
            response += f"{i}. {html.quote(c['text'])}\n"

    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Add Comment", callback_data=f"add_comm_{conf_id}")
    kb.button(text="🔄 Refresh", callback_data=f"refresh_{conf_id}")
    kb.adjust(1)

    await message.answer(response, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("add_comm_"))
async def start_comment(cb: types.CallbackQuery, state: FSMContext):
    conf_id = int(cb.data.split("_")[2])
    await state.set_state(CommentForm.waiting_for_comment)
    await state.update_data(active_conf_id=conf_id)
    
    # Use ForceReply to make sure the user replies to this prompt
    await cb.message.answer(
        f"✍️ <b>Adding comment to #{conf_id}</b>\nWrite your comment below (max 200 chars):",
        reply_markup=types.ForceReply(selective=True)
    )
    await cb.answer()

@dp.message(CommentForm.waiting_for_comment)
async def save_comment(message: types.Message, state: FSMContext):
    if not message.text or len(message.text) < 2:
        return await message.answer("❌ Comment too short.")
    
    data = await state.get_data()
    conf_id = data.get("active_conf_id")
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Save comment
        await conn.execute(
            "INSERT INTO comments (confession_id, user_id, text) VALUES ($1, $2, $3)",
            conf_id, message.from_user.id, message.text[:200]
        )
        # Reward for participation (+2 Aura Points)
        await conn.execute(
            "INSERT INTO user_points (user_id, points) VALUES ($1, 2) "
            "ON CONFLICT (user_id) DO UPDATE SET points = user_points.points + 2",
            message.from_user.id
        )
    
    await state.clear()
    await message.answer(f"✅ Comment added to #{conf_id}! You earned +2 Aura.")
    await show_confession_details(message, conf_id)

# ==========================================
# MODULE 7: TRENDING & PROFILES
# ==========================================

@dp.message(Command("hot"))
@dp.callback_query(F.data == "view_hot")
async def show_trending(event: types.Message | types.CallbackQuery):
    """Algorithm: Shows top 5 posts with most comments in the last 7 days."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        hot_posts = await conn.fetch("""
            SELECT c.id, COUNT(com.id) as comment_count 
            FROM confessions c 
            LEFT JOIN comments com ON c.id = com.confession_id 
            WHERE c.status = 'approved' AND c.created_at > NOW() - INTERVAL '7 days'
            GROUP BY c.id 
            ORDER BY comment_count DESC 
            LIMIT 5
        """)
    await pool.close()

    text = "<b>🔥 Trending Discussions (Last 7 Days)</b>\n\n"
    
    if not hot_posts:
        text += "<i>No trending posts yet. Start the conversation!</i>"
        if isinstance(event, types.CallbackQuery):
            return await event.message.edit_text(text, reply_markup=event.message.reply_markup)
        return await event.answer(text)

    for row in hot_posts:
        text += f"📌 <b>#{row['id']}</b> — {row['comment_count']} comments\n"
        text += f"🔗 /start view_{row['id']}\n\n"

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text)
    else:
        await event.answer(text)

@dp.message(Command("profile"))
@dp.callback_query(F.data == "view_profile")
async def cmd_profile(event: types.Message | types.CallbackQuery):
    """Shows user's Aura points and stats."""
    user_id = event.from_user.id
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        points = await conn.fetchval("SELECT points FROM user_points WHERE user_id = $1", user_id) or 0
        conf_count = await conn.fetchval("SELECT COUNT(*) FROM confessions WHERE user_id = $1 AND status = 'approved'", user_id)
        comm_count = await conn.fetchval("SELECT COUNT(*) FROM comments WHERE user_id = $1", user_id)
    await pool.close()

    profile_text = (
        f"👤 <b>Your Profile</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏅 <b>Aura Points:</b> {points}\n"
        f"📝 <b>Approved Confessions:</b> {conf_count}\n"
        f"💬 <b>Comments Made:</b> {comm_count}\n\n"
        f"<i>Keep interacting to earn more Aura!</i>"
    )
    
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(profile_text)
    else:
        await event.answer(profile_text)



# ==========================================
# MODULE 8: DEBUG TOOLS & BOT RUNNER
# ==========================================

@dp.message(Command("test_admin"))
async def cmd_test_admin(message: types.Message):
    """Diagnoses if the multi-admin setup in Render is working."""
    uid = message.from_user.id
    
    # 1. Check recognition
    recognized = is_admin(uid)
    
    status_report = (
        f"🛠 <b>Admin Diagnostic Report</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 <b>Your ID:</b> <code>{uid}</code>\n"
        f"📋 <b>Bot Memory List:</b> <code>{ADMIN_IDS}</code>\n"
        f"✅ <b>Recognized?:</b> {'YES' if recognized else '❌ NO'}\n"
        f"━━━━━━━━━━━━━━\n"
    )
    
    await message.answer(status_report)

    if recognized:
        try:
            await bot.send_message(uid, "🔔 <b>Test:</b> If you see this, notifications are working!")
        except Exception as e:
            await message.answer(f"❌ <b>Error:</b> I can't message you. Have you started the bot?\nDetails: {e}")
    else:
        await message.answer("⚠️ <b>Fix:</b> Copy your ID above and add it to the <code>ADMIN_ID</code> variable in Render.")

# --- RENDER HEALTH CHECK SERVER ---
async def handle_health_check(request):
    return web.Response(text="Bot is running smoothly!", status=200)

async def main():
    # 1. Initialize DB Tables
    await setup_db()
    
    # 2. Setup Web Server (to keep Render happy)
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render uses the 'PORT' environment variable
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"Health check server started on port {port}")
    logging.info(f"Bot starting... Admins loaded: {ADMIN_IDS}")

    # 3. Start Polling
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
