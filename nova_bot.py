import os
import re
import zipfile
import shutil
import threading
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests

# ============= CONFIGURATION =============
BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
PORT = int(os.environ.get('PORT', 5000))

# Flask app
app = Flask(__name__)

# Global variables
telegram_bot = None
application = None

# ============= EXTRACTION CLASS =============
class NovaExtractorBot:
    def __init__(self):
        self.extracted_data = {
            "ulp": set(),
            "admin": set(),
            "cc": set(),
            "tokens": set(),
            "cookies": set()
        }
        self.counts = {
            "checked": 0,
            "total": 0,
            "ulp": 0,
            "admin": 0,
            "cc": 0,
            "tokens": 0,
            "cookies": 0
        }
        self.lock = threading.Lock()
    
    def process_text(self, text, filename):
        """Extract data from text content"""
        
        # Extract ULP (URL:Login:Password)
        if any(x in filename.lower() for x in ['pass', 'log', 'combo']):
            # Pattern for URL:Login:Password
            patterns = [
                r'(https?://[^\s]+):([^\s:]+):([^\s]+)',
                r'([a-zA-Z0-9.-]+\.[a-z]{2,}):([^\s:]+):([^\s]+)',
                r'"(url|host|website)":"([^"]+)",".*?(login|user|email)":"([^"]+)",".*?(password|pass)":"([^"]+)"',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if len(match) >= 3:
                        url = match[0] if 'http' in match[0] else f"http://{match[0]}"
                        login = match[1]
                        password = match[2]
                        
                        line = f"{url}:{login}:{password}"
                        with self.lock:
                            if line not in self.extracted_data["ulp"]:
                                self.extracted_data["ulp"].add(line)
                                self.counts["ulp"] += 1
                                
                                # Check if admin panel
                                if any(x in url.lower() for x in ['admin', 'panel', 'dashboard', 'cpanel', 'wp-admin']):
                                    self.extracted_data["admin"].add(line)
                                    self.counts["admin"] += 1
        
        # Extract Credit Cards
        if any(x in filename.lower() for x in ['card', 'cc', 'credit']):
            # CC Pattern: 16 digit number, MM/YY, CVV
            cc_pattern = r'(\d{13,19})[^\d]{0,5}(\d{1,2})[^\d]{0,5}(\d{2,4})[^\d]{0,5}(\d{3,4})'
            for match in re.finditer(cc_pattern, text):
                cc, mm, yy, cvv = match.groups()
                mm = mm.zfill(2)
                if len(yy) == 2:
                    yy = f"20{yy}"
                if 1 <= int(mm) <= 12:
                    line = f"{cc}|{mm}|{yy}|{cvv}"
                    with self.lock:
                        if line not in self.extracted_data["cc"]:
                            self.extracted_data["cc"].add(line)
                            self.counts["cc"] += 1
        
        # Extract Discord Tokens
        if any(x in filename.lower() for x in ['token', 'discord', 'local']):
            token_pattern = r'[\w-]{24}\.[\w-]{6}\.[\w-]{27}|mfa\.[\w-]{84}'
            for token in re.findall(token_pattern, text):
                with self.lock:
                    if token not in self.extracted_data["tokens"]:
                        self.extracted_data["tokens"].add(token)
                        self.counts["tokens"] += 1
        
        # Extract Cookies
        if 'cookie' in filename.lower():
            for line in text.splitlines():
                if 'TRUE' in line or 'FALSE' in line:
                    if any(x in line.lower() for x in ['.', 'domain', 'path']):
                        with self.lock:
                            self.extracted_data["cookies"].add(line[:500])
    
    def process_file(self, file_path, chat_id, bot):
        """Process a single file"""
        try:
            if file_path.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zf:
                    for name in zf.namelist():
                        if name.endswith(('.txt', '.log', '.json')):
                            try:
                                content = zf.read(name).decode('utf-8', errors='ignore')
                                self.process_text(content, name)
                            except:
                                pass
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                self.process_text(content, os.path.basename(file_path))
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
        
        with self.lock:
            self.counts["checked"] += 1
    
    def get_results(self):
        """Get extracted results"""
        return {
            "ulp": list(self.extracted_data["ulp"]),
            "admin": list(self.extracted_data["admin"]),
            "cc": list(self.extracted_data["cc"]),
            "tokens": list(self.extracted_data["tokens"]),
            "cookies": list(self.extracted_data["cookies"])
        }

# ============= TELEGRAM BOT HANDLERS =============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = """🔍 *NOVA CLOUD - MULTI LOG EXTRACTOR* 🔍

╔════════════════════════════════╗
║  Extract valuable data from    ║
║  log files, combos, and dumps  ║
╚════════════════════════════════╝

*WHAT IT EXTRACTS:*
✅ ULP (URL:Login:Password)
✅ Admin Panel Logins  
✅ Credit Cards (CC)
✅ Discord Tokens
✅ Cookies

*COMMANDS:*
/start - Show this menu
/help - Detailed help
/extract - Extract from file
/stats - Show statistics

📁 *Send .txt or .zip file* to extract data

💻 *Powered by NovaCloud*"""

    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_msg = """📖 *NOVA EXTRACTOR HELP*

*HOW TO USE:*

1️⃣ *Single File Extraction*
Send any .txt or .zip file containing:
• Login credentials (email:pass or url:user:pass)
• Credit card details
• Discord tokens
• Cookie files

2️⃣ *Bulk Extraction*
Send multiple files in one message or .zip archive

*SUPPORTED FORMATS:*
• URL:Login:Password
• email@domain.com:password
• CC|MM|YY|CVV
• Discord tokens (any format)
• Netscape cookie files

*EXAMPLES:*
`https://example.com:admin:pass123`
`user@mail.com:password123`
`4111111111111111|12|2025|123`

*OUTPUT:*
Separate files for each data type:
• ULP_All.txt
• Admin_Logins.txt  
• Credit_Cards.txt
• Discord_Tokens.txt
• Cookies.txt

💻 @NovaCloud"""

    await update.message.reply_text(help_msg, parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_msg = """📊 *NOVA EXTRACTOR STATS*

*Features:*
• Multi-threaded extraction
• Pattern recognition
• Duplicate removal
• Auto-categorization

*Supported Data:*
• ULP (URL credentials)
• Admin panel logins
• Credit card details
• Discord authentication tokens
• Browser cookies

*Ready to extract!*
Send any .txt or .zip file to begin

💻 @NovaCloud"""

    await update.message.reply_text(stats_msg, parse_mode="Markdown")

async def extract_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    extract_msg = """🔍 *HOW TO EXTRACT*

1. Send me a `.txt` or `.zip` file
2. I'll automatically scan it for:
   • Login credentials
   • Credit cards
   • Discord tokens
   • Cookies

3. Get back categorized results

*Quick Tip:* 
Send multiple files at once or a .zip archive for bulk extraction!

*Example file content:*