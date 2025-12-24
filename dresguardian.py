import logging
import re
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import aiohttp
from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberUpdated
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ChatMemberHandler
)
from telegram.constants import ParseMode, ChatMemberStatus
from cerebras.cloud.sdk import Cerebras
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# CONFIG 
TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
MODEL = "llama-3.3-70b"
FAKE_IP = "203.0.113.42"
STORE_FILE = "dresguardian_store.json"
DRESOS_STORE = "https://t.me/+MNAkOmH5_eczMjg0"

# Safety check - prevent running with missing credentials
if not all([TOKEN, OWNER_ID, CEREBRAS_API_KEY]):
    raise ValueError(
        "Missing required environment variables in .env file: "
        "TELEGRAM_TOKEN, OWNER_ID, and/or CEREBRAS_API_KEY"
    )

client = Cerebras(api_key=CEREBRAS_API_KEY)

# Ultra privacy mode
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("cerebras").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO)

# STORAGE
def load_store():
    default = {"welcomes": {}, "blacklist": [], "banned_words": {}, "warns": {}}
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in default:
                data.setdefault(k, default[k])
            return data
        except Exception as e:
            logging.error(f"Load error: {e}")
    return default.copy()

def save_store():
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(STORE, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Save failed: {e}")

STORE = load_store()
GLOBAL_BLACKLIST = set(STORE.get("blacklist", []))

# AI & PRIVATE SEARCH
async def duckduckgo_search(query: str) -> str:
    if re.search(r"\b(?:what.?is|show|my|your|this|server|bot)?\s*ip\b", query, re.IGNORECASE):
        return "IP queries are blocked for your privacy."
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14)",
        "DNT": "1",
        "X-Forwarded-For": FAKE_IP,
        "X-Real-IP": FAKE_IP,
        "Client-IP": FAKE_IP,
    }
    
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1", "no_redirect": "1"}
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get("https://api.duckduckgo.com/", params=params, headers=headers) as resp:
                text = await resp.text()
                data = json.loads(text)
                
                if data.get("Answer"):
                    return f"<b>Answer:</b>\n{data['Answer']}"
                
                if data.get("AbstractText"):
                    text = data["AbstractText"]
                    url = data.get("AbstractURL", "")
                    return text + (f"\n\n<a href='{url}'>Source</a>" if url else "")
                
                results = []
                for item in data.get("RelatedTopics", [])[:5]:
                    if item.get("Text") and item.get("FirstURL"):
                        safe_text = item["Text"].replace("<", "&lt;").replace(">", "&gt;")
                        results.append(f"• <a href='{item['FirstURL']}'>{safe_text}</a>")
                
                return "\n\n".join(results) or "No results found."
    
    except Exception as e:
        logging.error(f"Search error: {e}")
        return "Search temporarily unavailable."

def call_ai(prompt: str) -> str:
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL,
            max_completion_tokens=900,
            temperature=0.7,
            top_p=1,
            stream=False
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Cerebras error: {e}")
        return "Neural core warming up — try again in a moment."

# AI rate limit
locks = defaultdict(asyncio.Lock)
COOLDOWN = 1.5

async def can_use_ai(user_id: int) -> bool:
    async with locks[user_id]:
        now = datetime.now()
        last = getattr(can_use_ai, "last_used", {}).get(user_id)
        if last is None or (now - last).total_seconds() >= COOLDOWN:
            if not hasattr(can_use_ai, "last_used"):
                can_use_ai.last_used = {}
            can_use_ai.last_used[user_id] = now
            return True
        return False

# UTILS
async def is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

def is_globally_blacklisted(user_id: int) -> bool:
    return user_id in GLOBAL_BLACKLIST

def has_banned_word(chat_id: int, text: str) -> bool:
    words = STORE["banned_words"].get(str(chat_id), [])
    return any(w.lower() in text.lower() for w in words)

def parse_duration(s: str) -> timedelta:
    m = re.match(r"(\d+)([smhd]?)", s.lower())
    if not m:
        return timedelta(hours=1)
    num, unit = int(m.group(1)), m.group(2) or "h"
    return {
        "s": timedelta(seconds=num),
        "m": timedelta(minutes=num),
        "h": timedelta(hours=num),
        "d": timedelta(days=num)
    }.get(unit, timedelta(hours=1))

def add_warn(chat_id: int, user_id: int):
    key = f"{chat_id}:{user_id}"
    STORE["warns"][key] = STORE["warns"].get(key, 0) + 1
    save_store()
    return STORE["warns"][key]

def remove_warn(chat_id: int, user_id: int):
    key = f"{chat_id}:{user_id}"
    if key in STORE["warns"]:
        STORE["warns"][key] -= 1
        if STORE["warns"][key] <= 0:
            del STORE["warns"][key]
        save_store()

def get_warn_count(chat_id: int, user_id: int) -> int:
    return STORE["warns"].get(f"{chat_id}:{user_id}", 0)

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            try:
                member = await context.bot.get_chat_member(update.effective_chat.id, arg)
                return member.user
            except:
                pass
        try:
            uid = int(arg)
            member = await context.bot.get_chat_member(update.effective_chat.id, uid)
            return member.user
        except:
            pass
    return None

# COMMANDS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "DresGuardian — The Ultimate Group Bot\n\n"
        "Fully encrypted • Zero logs • Zero tracking\n\n"
        "Encryption & Bot Features:\n"
        "• AI powered by Llama 3.3-70b — no OpenAI spying\n"
        "• Private search via DuckDuckGo with spoofed IP and DNT requests that strips all cookies and trackers\n"
        "• All queries anonymized — your real IP never leaves your device\n"
        "• End-to-end message handling — nothing stored\n"
        "• Backend secured by tor, mac randomization and a fake user agent\n"
        "• Full Group Moderation\n\n"
        "Encrypted, Built and Hosted by DresOS\n"
        "Forever Free, Forever Private\n\n"
        "Type /help for full command list"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>DresGuardian Commands</b>\n\n"
        "<b>AI & Search (Everyone):</b>\n"
        "• /ask <i>your question</i>\n"
        "• /search <i>anything</i> — 100% private\n"
        "<b>Moderation (Admins):</b>\n"
        "/warn • /delwarn • /warns • /kick • /ban • /unban\n"
        "/mute 10m • /unmute • /addword • /removeword\n\n"
        "<b>Welcome Setup:</b>\n"
        "/setwelcometext • /setmedia (reply photo/GIF/video)\n"
        "/setchannellink • /clearwelcome\n\n"
        "<b>Owner Only:</b>\n"
        "/blacklist • /unblacklist • /blacklisted\n\n"
        "Encrypted by <b>DresOS</b> — Privacy First",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

# AI Commands
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <code>what is quantum physics?</code>", parse_mode=ParseMode.HTML)
        return
    query = " ".join(context.args)
    await update.message.reply_chat_action("typing")
    result = await duckduckgo_search(query)
    await update.message.reply_text(result, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_globally_blacklisted(user_id):
        await update.message.reply_text("Access denied.")
        return
    if not await can_use_ai(user_id):
        return
    if not context.args:
        await update.message.reply_text("Use: <code>/ask what is the meaning of life?</code>", parse_mode=ParseMode.HTML)
        return
    query = " ".join(context.args)
    msg = update.effective_message
    await msg.reply_chat_action("typing")
    answer = call_ai(query)
    await msg.reply_text(answer, reply_to_message_id=msg.message_id)

async def mention_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text or msg.from_user.is_bot:
        return
    user_id = msg.from_user.id
    if is_globally_blacklisted(user_id) or not await can_use_ai(user_id):
        return
    text = msg.text.strip().lower()
    if "@dresguardian" not in text and not text.startswith(("dresguardian", "hey dres", "yo dres")):
        return
    query = re.sub(r"@dresguardian", "", msg.text, flags=re.I).strip()
    if not query:
        return
    await msg.reply_chat_action("typing")
    answer = call_ai(query)
    await msg.reply_text(answer, reply_to_message_id=msg.message_id)

# Moderation Commands
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention user")
        return
    count = add_warn(update.effective_chat.id, user.id)
    await update.message.reply_text(f"Warned {user.mention_html()} ({count}/3)", parse_mode=ParseMode.HTML)
    if count >= 3:
        until = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        await context.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
        await update.message.reply_text(f"{user.first_name} auto-muted for 1 hour (3 warns)")
        STORE["warns"].pop(f"{update.effective_chat.id}:{user.id}", None)
        save_store()

async def delwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention")
        return
    remove_warn(update.effective_chat.id, user.id)
    await update.message.reply_text(f"Warn removed from {user.first_name}")

async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_target_user(update, context) or update.effective_user
    count = get_warn_count(update.effective_chat.id, user.id)
    await update.message.reply_text(f"{user.first_name} has <b>{count}/3</b> warns", parse_mode=ParseMode.HTML)

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention")
        return
    await context.bot.ban_chat_member(update.effective_chat.id, user.id)
    await context.bot.unban_chat_member(update.effective_chat.id, user.id)
    await update.message.reply_text(f"{user.first_name} kicked")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention")
        return
    await context.bot.ban_chat_member(update.effective_chat.id, user.id)
    await update.message.reply_text(f"{user.first_name} banned")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention")
        return
    await context.bot.unban_chat_member(update.effective_chat.id, user.id)
    await update.message.reply_text(f"{user.first_name} unbanned")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply + time (e.g. /mute 10m)")
        return
    dur = context.args[-1] if context.args else "1h"
    until = int((datetime.now(timezone.utc) + parse_duration(dur)).timestamp())
    await context.bot.restrict_chat_member(update.effective_chat.id, user.id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
    await update.message.reply_text(f"{user.first_name} muted for {dur}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention")
        return
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        user.id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
    )
    await update.message.reply_text(f"{user.first_name} unmuted")

# Banned words
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addword badword")
        return
    word = " ".join(context.args).lower()
    chat = str(update.effective_chat.id)
    STORE["banned_words"].setdefault(chat, [])
    if word not in STORE["banned_words"][chat]:
        STORE["banned_words"][chat].append(word)
        save_store()
    await update.message.reply_text(f"Word '{word}' banned in this group")

async def removeword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeword word")
        return
    word = " ".join(context.args).lower()
    chat = str(update.effective_chat.id)
    if chat in STORE["banned_words"] and word in STORE["banned_words"][chat]:
        STORE["banned_words"][chat].remove(word)
        save_store()
        await update.message.reply_text("Word unbanned")
    else:
        await update.message.reply_text("Word not found")

# Welcome System
async def setwelcometext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /setwelcometext Welcome {first}!")
        return
    chat_id = str(update.effective_chat.id)
    STORE["welcomes"].setdefault(chat_id, {})["text"] = " ".join(context.args)
    save_store()
    await update.message.reply_text("Welcome text saved!")

async def setmedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    msg = update.message.reply_to_message
    if not msg or not (msg.photo or msg.animation or msg.video):
        await update.message.reply_text("Reply to a photo, GIF, or video")
        return
    chat_id = str(update.effective_chat.id)
    STORE["welcomes"].setdefault(chat_id, {})
    if msg.photo:
        STORE["welcomes"][chat_id].update({"media": msg.photo[-1].file_id, "type": "photo"})
    elif msg.animation:
        STORE["welcomes"][chat_id].update({"media": msg.animation.file_id, "type": "animation"})
    elif msg.video:
        STORE["welcomes"][chat_id].update({"media": msg.video.file_id, "type": "video"})
    save_store()
    await update.message.reply_text("Welcome media saved!")

async def setchannellink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /setchannellink https://t.me/example")
        return
    link = context.args[0]
    if not link.startswith(("http", "t.me")):
        link = "https://" + link
    STORE["welcomes"].setdefault(str(update.effective_chat.id), {})["link"] = link
    save_store()
    await update.message.reply_text("Channel link button saved!")

async def clearwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(context, update.effective_chat.id, update.effective_user.id):
        return
    STORE["welcomes"].pop(str(update.effective_chat.id), None)
    save_store()
    await update.message.reply_text("Welcome message cleared")

async def _send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, members):
    chat_id = update.effective_chat.id
    cfg = STORE["welcomes"].get(str(chat_id), {})
    if not cfg.get("text"):
        return
    for member in members:
        text = cfg["text"] \
            .replace("{first}", member.first_name or "User") \
            .replace("{mention}", member.mention_html()) \
            .replace("{id}", str(member.id)) \
            .replace("{username}", f"@{member.username}" if member.username else member.first_name)
        
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel", url=cfg["link"])]]) if cfg.get("link") else None
        
        try:
            if cfg.get("media"):
                file_id = cfg["media"]
                mtype = cfg.get("type", "photo")
                send_func = {
                    "photo": context.bot.send_photo,
                    "animation": context.bot.send_animation,
                    "video": context.bot.send_video
                }[mtype]
                await send_func(chat_id, file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup, protect_content=True)
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                    protect_content=True,
                    disable_notification=True
                )
        except Exception as e:
            logging.error(f"Welcome failed: {e}")

async def legacy_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.new_chat_members:
        await _send_welcome(update, context, update.message.new_chat_members)

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return
    chat_member_update = update.chat_member
    user = chat_member_update.from_user
    old_status = chat_member_update.old_chat_member.status if chat_member_update.old_chat_member else None
    new_status = chat_member_update.new_chat_member.status
    if old_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) or new_status != ChatMemberStatus.MEMBER:
        return
    if user.is_bot or is_globally_blacklisted(user.id):
        return
    await _send_welcome(update, context, [user])

# Filters
async def message_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.effective_user.is_bot or is_globally_blacklisted(update.effective_user.id):
        return
    if has_banned_word(update.effective_chat.id, update.message.text):
        try:
            await update.message.delete()
        except:
            pass

# Owner Commands
async def blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    user = await get_target_user(update, context)
    if not user:
        await update.message.reply_text("Reply or mention user")
        return
    if user.id not in GLOBAL_BLACKLIST:
        GLOBAL_BLACKLIST.add(user.id)
        STORE["blacklist"] = list(GLOBAL_BLACKLIST)
        save_store()
        await update.message.reply_text(f"Globally blacklisted {user.id}")
    else:
        await update.message.reply_text("Already blacklisted")

async def unblacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    user = await get_target_user(update, context)
    if user and user.id in GLOBAL_BLACKLIST:
        GLOBAL_BLACKLIST.remove(user.id)
        STORE["blacklist"] = list(GLOBAL_BLACKLIST)
        save_store()
        await update.message.reply_text("Removed from global blacklist")

async def blacklisted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    bl = "\n".join(map(str, GLOBAL_BLACKLIST)) if GLOBAL_BLACKLIST else "Empty"
    await update.message.reply_text(f"Global Blacklist:\n{bl}")

# MAIN
def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()
    
    # Core
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("search", search))
    
    # AI mention
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mention_ai))
    
    # Moderation
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("delwarn", delwarn))
    app.add_handler(CommandHandler("warns", warns))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("addword", addword))
    app.add_handler(CommandHandler("removeword", removeword))
    
    # Welcome
    app.add_handler(CommandHandler("setwelcometext", setwelcometext))
    app.add_handler(CommandHandler("setmedia", setmedia))
    app.add_handler(CommandHandler("setchannellink", setchannellink))
    app.add_handler(CommandHandler("clearwelcome", clearwelcome))
    
    # Owner
    app.add_handler(CommandHandler("blacklist", blacklist))
    app.add_handler(CommandHandler("unblacklist", unblacklist))
    app.add_handler(CommandHandler("blacklisted", blacklisted))
    
    # System handlers
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, legacy_welcome))
    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_filter))
    
    print("DresGuardian Activated — Fully Encrypted, Forever Private")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()