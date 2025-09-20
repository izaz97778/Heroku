import os
import logging
import heroku3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HEROKU_API_KEY = os.getenv("HEROKU_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---
def get_heroku_conn(api_key: str):
    """Establishes a connection to the Heroku API."""
    try:
        return heroku3.from_key(api_key)
    except Exception as e:
        logger.error(f"Failed to connect to Heroku: {e}")
        return None

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = "Main Menu"):
    """Displays the main menu buttons."""
    keyboard = [
        [InlineKeyboardButton("⚙️ Manage Heroku Apps", callback_data="manage_apps")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

async def show_app_management_menu(query):
    """Shows the app management options."""
    keyboard = [
        [InlineKeyboardButton("🔄 Restart Dynos", callback_data="list_apps_restart")],
        [InlineKeyboardButton("« Back to Main Menu", callback_data="main_menu")],
    ]
    await query.message.edit_text("App Management:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Main Command and Button Handler ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the main menu, but only to the owner."""
    if update.effective_user.id != OWNER_ID:
        return

    await show_main_menu(update, context, text="Welcome! This bot is connected to your Heroku account.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline button presses, but only from the owner."""
    query = update.callback_query
    
    if query.from_user.id != OWNER_ID:
        await query.answer("You are not authorized to use this bot.", show_alert=True)
        return

    await query.answer()
    data = query.data

    # --- Routing ---
    if data == "manage_apps":
        await show_app_management_menu(query)
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "list_apps_restart":
        await list_apps(query, "restart")
    elif data.startswith("select_app_restart_"):
        app_name = data.replace("select_app_restart_", "")
        await confirm_restart(query, app_name)
    elif data.startswith("confirm_restart_"):
        app_name = data.replace("confirm_restart_", "")
        await restart_dyno(query, app_name)


async def list_apps(query, action_type: str):
    """Fetches and lists user's apps as buttons."""
    await query.message.edit_text("⏳ Fetching your apps...")
    heroku_conn = get_heroku_conn(HEROKU_API_KEY)
    if not heroku_conn:
        await query.message.edit_text("Failed to connect to Heroku. Please check your API Key.")
        return
        
    try:
        apps = heroku_conn.apps()
        if not apps:
            await query.message.edit_text("You don't have any Heroku apps.",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="manage_apps")]]))
            return

        keyboard = []
        for app in apps:
            callback_data = f"select_app_{action_type}_{app.name}"
            keyboard.append([InlineKeyboardButton(app.name, callback_data=callback_data)])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="manage_apps")])
        
        prompt = f"Select an app to {action_type} its dynos:"
        await query.message.edit_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Failed to fetch apps: {e}")
        await query.message.edit_text(f"An error occurred while fetching your apps.\n\nError: {e}")

# --- Dyno Actions ---
async def confirm_restart(query, app_name: str):
    """Asks for confirmation before restarting."""
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Restart", callback_data=f"confirm_restart_{app_name}")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data="list_apps_restart")]
    ]
    # FIX: Wrap app_name in backticks to prevent Markdown errors
    await query.message.edit_text(f"Are you sure you want to restart all dynos for `{app_name}`?",
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")

async def restart_dyno(query, app_name: str):
    """Restarts all dynos for a specific app."""
    # FIX: Wrap app_name in backticks
    await query.message.edit_text(f"🔄 Restarting dynos for `{app_name}`...", parse_mode="MarkdownV2")
    heroku_conn = get_heroku_conn(HEROKU_API_KEY)
    try:
        app = heroku_conn.apps()[app_name]
        app.restart()
        # FIX: Wrap app_name in backticks
        await query.message.edit_text(f"✅ Successfully restarted all dynos for `{app_name}`.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_restart")]]),
                                      parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Failed to restart dyno for {app_name}: {e}")
        await query.message.edit_text(f"❌ Failed to restart dynos. Error: {e}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_restart")]]))

# --- Main Application Setup ---
def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
        return
    if not HEROKU_API_KEY:
        logger.critical("HEROKU_API_KEY environment variable not set. Exiting.")
        return
    if OWNER_ID == 0:
        logger.critical("OWNER_ID environment variable not set or is invalid. Exiting.")
        return
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info(f"Bot is running... Awaiting commands from owner ({OWNER_ID}).")
    application.run_polling()


if __name__ == "__main__":
    main()
