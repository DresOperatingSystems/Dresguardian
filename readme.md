A powerful, fully self hosted Telegram bot that puts your privacy first. No logs, no tracking, no third-party data collection just pure encrypted functionality.

Forever Free • Open Source • Zero Compromises on Privacy

Built by DresOS — because your data belongs to you.

# What It Does

DresGuardian combines advanced group moderation with a privacy respecting AI assistant:

# AI & Private Search (Available to Everyone)
- `/ask <question>` — Chat with a powerful AI powered by Cerebras Llama 3.3-70B (no OpenAI, no data harvesting)
- `/search <query>` — Fully anonymized and encrypted web search via DuckDuckGo:
  - Your real IP is never sent — replaced with a fake static IP (`203.0.113.42`)
  - Custom headers: fake User-Agent, Do-Not-Track (`DNT: 1`), and spoofed forwarding IPs (`X-Forwarded-For`, `X-Real-IP`, `Client-IP`)
  - No cookies, no trackers, no referrers
  - All requests made over HTTPS with short timeouts
  - IP-related queries (e.g., "what is my IP") are automatically blocked to prevent accidental leaks
  - Results returned cleanly in HTML with safe links
- Mention the bot directly (e.g., `@YourBot`, "hey dres", "yo dres") — triggers AI response
- Built-in per-user rate limiting (1.5s cooldown) to prevent spam and abuse

# Full Group Moderation (Admin Only)
- Warn System: `/warn` → adds a warn. At 3 warns, user is automatically muted for 1 hour (warns reset after punishment)
- `/delwarn`, `/warns` — remove or check warns
- `/kick`, `/ban`, `/unban`
- `/mute 10m`, `/mute 2h`, `/mute 1d` — timed mutes with flexible duration
- `/unmute`
- Banned Words Filter: `/addword <phrase>` — any message containing the word/phrase is auto-deleted
- `/removeword` — remove from banned list

# Custom Welcome Messages (Admin Only)
- `/setwelcometext <message>` — supports placeholders:
  - `{first}` → user's first name
  - `{mention}` → clickable mention
  - `{username}` → @username or name if none
  - `{id}` → user ID
- `/setmedia` — reply to a photo, GIF, or video to set welcome media
- `/setchannellink <url>` — adds a "Join Channel" button
- `/clearwelcome` — remove welcome entirely
- Welcomes trigger on new members (supports both legacy and new chat member updates)

# Owner-Only Features
- `/blacklist` — globally blacklist a user from the bot
- `/unblacklist`, `/blacklisted` — manage and view the global blacklist

# Data Storage
- All settings (welcomes, banned words, warns, global blacklist) are stored locally in a single file: `dresguardian_store.json`
- No database required
- No cloud sync
- Easy to backup or migrate — just copy the JSON file
- Data is loaded on startup and saved automatically after changes
- File is written with proper encoding and indentation — human-readable if needed

# Privacy & Encryption Guarantees
- Zero logging of messages, queries, or user activity
- No analytics or external tracking
- Sensitive credentials (bot token, API keys) loaded securely from `.env` — never hardcoded
- AI requests go only to Cerebras (privacy-respecting provider) over encrypted connections
- Search requests are fully anonymized and protected as described above
- End-to-end handling: Messages processed in memory only — nothing persisted beyond configuration
- You control the server — full data sovereignty and encryption at rest (depends on your filesystem)

---

# Requirements

- Debian/ubuntu
- Python 3.8+
- Telegram account
- Cerebras API key (free tier available)

---

# Getting Your Keys & Tokens

1. Telegram Bot Token
   - Chat with [@BotFather](https://t.me/BotFather)
   - Send `/newbot`
   - Follow instructions → receive your bot token

2. Your Telegram User ID (for OWNER_ID)
   - Chat with [@userinfobot](https://t.me/userinfobot)
   - It will instantly reply with your numeric ID

3. Cerebras API Key (free and secure)
   - Visit [https://cerebras.ai](https://cerebras.ai)
   - Sign up / log in
   - Go to API section → generate a key (starts with `csk-`)

---

# Setup Instructions

1. Clone the repo
```bash   
sudo apt update && sudo apt full-uprgrade -y
```
```bash 
sudo apt install git
```
```bash
sudo apt install python3
```
```bash
git clone https://github.com/DresOperatingSystems/Dresguardian
```
```bash
cd Dresguardian
```
                  
3. create a venv (this is for self hosting and so we dont run into issues)
```bash
sudo apt update
```
```bash
sudo apt install python3-venv
```
```bash
python3 -m venv .venv && source .venv/bin/activate
```    
   
5. after install the dependencies
```bash
pip install -r requirements.txt
``` 

7. set up tbe .env file
 ```bash
sudo apt install nano
```
```bash
cp .env-sample .env
```
```bash
nano .env
```
input your variables     
   
9. self host   
```bash
sudo apt install nohup
```
```bash   
nohup python dresguardian.py &
```   
```bash
deactivate
```
```bash  
exit
```
now your bot is being self hosted for extra backend security install and start tor along with setting up mac randomization and run your machine through a vpn/proxy service

anyways we hope you like this one and we wish you a merry christmas from the entire Dres team
