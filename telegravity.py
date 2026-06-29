import asyncio
import os
import re
import sys
import subprocess
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_exception_message

# IMPORT OFFICIAL SDK
from google.antigravity import Agent, LocalAgentConfig

# --- CONFIGURATION ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))

SKILLS_DIR = "skills"
os.makedirs(SKILLS_DIR, exist_ok=True)
pending_actions = {}

async def run_shell_command(command: str):
    """Executes shell commands on the local machine."""
    return f"COMMAND_READY:{command}"

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_message(message="503")
)
async def safe_agent_chat(agent, prompt):
    return await agent.chat(prompt)

# --- ASYNC WORKER PATTERN (The True Solution for Context) ---
class AgentWorker:
    """
    Holds the Antigravity Agent inside a perpetual 'async with' block.
    Communicates with the Telegram Bot via Async Queues to preserve SDK memory.
    """
    def __init__(self, user_id):
        self.user_id = user_id
        self.in_queue = asyncio.Queue()
        self.out_queue = asyncio.Queue()
        self.running = True
        
        # System instructions
        self.config = LocalAgentConfig(
            model="gemini-3.1-flash-lite",
            disable_default_policy=True,
            tools=[run_shell_command],
            system_instructions=(
                "You are Telegravity, a secure Concierge Agent with Linux terminal access. "
                "Follow these CRITICAL DIRECTIVES strictly: "
                "1. NO RANDOM SCANNING: Do not list or read files in the root workspace unless explicitly requested. If the user just greets you (e.g., 'hi'), reply briefly WITHOUT calling any tools. "
                "2. KNOWLEDGE BASE FIRST: Before suggesting or executing a solution for a technical task, you MUST autonomously check the 'skills/' directory for relevant previously learned workarounds. "
                "3. NO PERMISSION QUESTIONS: NEVER ask the user for permission to run a command in your text response. If a command is needed, explain why and IMMEDIATELY output it wrapped strictly in <EXECUTE>command</EXECUTE>. The external system handles user approval."
            )
        )
        # Start the persistent background loop
        self.task = asyncio.create_task(self._agent_loop())

    async def _agent_loop(self):
        logger.info(f"Starting persistent Antigravity session for user {self.user_id}")
        try:
            # THIS is the magic. The block stays open forever.
            async with Agent(self.config) as agent:
                while self.running:
                    # Wait for a message from Telegram
                    prompt = await self.in_queue.get()
                    
                    try:
                        # Agent natively remembers everything before this prompt!
                        #response = await agent.chat(prompt)
                        response = await safe_agent_chat(agent, prompt)
                        reply_text = await response.text()
                        await self.out_queue.put(reply_text)
                    except Exception as e:
                        logger.error(f"Agent error: {e}")
                        await self.out_queue.put(f"⚠️ Internal Agent Error: {str(e)}")
                        
                    self.in_queue.task_done()
        except Exception as e:
            logger.critical(f"Agent loop crashed: {e}")

# Global storage for background workers
workers = {}

def get_worker(user_id: int) -> AgentWorker:
    """Lazily instantiate the worker in the active event loop."""
    if user_id not in workers:
        workers[user_id] = AgentWorker(user_id)
    return workers[user_id]

# --- COMPONENT 1: SECURITY PIPELINE ---
async def security_audit(command: str, user_context: str) -> tuple[bool, str]:
    dangerous_patterns = [r"rm\s+-rf\s+/", r"dd\s+if=", r"mkfs", r">\s*/dev/sda", r"chmod\s+-R\s+777\s+/"]
    for pattern in dangerous_patterns:
        if re.search(pattern, command):
            return False, "🛑 BLOCKED BY STATIC ANALYZER: Critical Threat Pattern."

    # The Judge is stateless, so a temporary agent is perfectly fine here.
    judge_config = LocalAgentConfig(
        model="gemini-3.1-flash-lite",
         system_instructions=(
            "You are a pragmatic Linux Security Auditor for a developer workspace. "
            "Analyze the bash command and user intent. "
            "CRITICAL POLICY CHANGE: Do NOT block commands just because they use debugging or "
            "development flags (such as '--no-sandbox', '--remote-debugging-port', or 'nohup'). "
            "If the user explicitly asked to run a browser, tools, or scripts for debugging/testing purposes, "
            "and the command does NOT threaten host root directories or private credentials, reply with 'PASS'. "
            "Only reply with 'BLOCK: <reason>' if there is a clear intent of data exfiltration or host OS destruction."
        )
    )
    async with Agent(judge_config) as judge:
        response = await judge.chat(f"Context: {user_context}\nEvaluate: `{command}`")
        audit_result = await response.text()
    
    if audit_result.strip().startswith("BLOCK"):
        return False, f"🛡️ BLOCKED BY AI AUDITOR:\n{audit_result}"
    return True, "PASSED"

# --- MAIN TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID: return
    
    # Reset session by recreating the worker
    if user_id in workers:
        workers[user_id].running = False
        workers[user_id].task.cancel()
        del workers[user_id]
        
    get_worker(user_id) # Initialize new session
    await update.message.reply_text("🛰️ **Telegravity Bridge Online.**\nPersistent Antigravity session initialized.", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID: return

    user_text = update.message.text
    status_msg = await update.message.reply_text("⏳ Antigravity is reasoning...")

    # Route message to the persistent background agent
    worker = get_worker(user_id)
    await worker.in_queue.put(user_text)
    
    # Wait for the agent to finish thinking
    agent_text = await worker.out_queue.get()

    # Intercept tool calls
    match = re.search(r"<EXECUTE>(.*?)</EXECUTE>", agent_text, re.DOTALL)
    if match:
        command_to_run = match.group(1).strip()
        explanation = agent_text.replace(match.group(0), "").strip()
        
        is_safe, sec_msg = await security_audit(command_to_run, user_text)
        if not is_safe:
            await status_msg.edit_text(f"{explanation}\n\n{sec_msg}")
            return
            
        pending_actions[user_id] = command_to_run
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data="approve"), InlineKeyboardButton("❌ Deny", callback_data="deny")]]
        await status_msg.edit_text(
            f"🤖 **Reasoning:**\n{explanation}\n\n⚠️ **Action Required (HitL):**\n`{command_to_run}`",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    else:
        await status_msg.edit_text(agent_text)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ALLOWED_USER_ID: return
    await query.answer()
    
    command = pending_actions.pop(user_id, None)
    worker = get_worker(user_id)

    if not command:
        await query.edit_message_text("Session expired.")
        return

    if query.data == "approve":
        await query.edit_message_text(f"🚀 Executing:\n`{command}`...", parse_mode="Markdown")
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            output = result.stdout if result.stdout else result.stderr
            if not output: output = "Success (No Output)."
            
            if len(output) > 3500:
                with open("/tmp/tg_output.log", "w") as f: f.write(output)
                await query.message.reply_document(document=open("/tmp/tg_output.log", "rb"), caption="Output too large.")
            else:
                await query.message.reply_text(f"✅ **Result:**\n```bash\n{output}\n```", parse_mode="Markdown")
            
            # Feed the terminal output directly back into the live agent session!
            await worker.in_queue.put(f"System Output from last command:\n{output}")
            # We don't await the out_queue here, we just let the agent process it silently
            
        except Exception as e:
            await query.message.reply_text(f"❌ **Error:**\n{str(e)}", parse_mode="Markdown")
            await worker.in_queue.put(f"System Error:\n{str(e)}")
            
    elif query.data == "deny":
        await query.edit_message_text("🚫 **Execution Denied by User.**", parse_mode="Markdown")
        await worker.in_queue.put("User denied execution for safety reasons.")

def main():
    # FIX: Loud explicit error messages if variables are missing
    if not TELEGRAM_BOT_TOKEN:
        print("❌ CRITICAL ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        sys.exit(1)
        
    if ALLOWED_USER_ID == 0:
        print("❌ CRITICAL ERROR: ALLOWED_USER_ID is missing or set to 0 in .env. Security check failed.")
        sys.exit(1)
        
    print("✅ Configuration loaded successfully. Starting bot...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("🛰️ Telegravity Bridge started.")
    app.run_polling()

if __name__ == "__main__":
    main()
