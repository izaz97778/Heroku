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
        [InlineKeyboardButton("⚙️ Manage Dynos", callback_data="list_apps_manage")],
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
    parts = data.split('_')

    # --- Routing ---
    if data == "manage_apps":
        await show_app_management_menu(query)
    elif data == "main_menu":
        await show_main_menu(update, context)
    elif data == "list_apps_restart":
        await list_apps(query, "restart")
    elif data == "list_apps_manage":
        await list_apps(query, "manage")
    elif data.startswith("select_app_restart_"):
        app_name = data.replace("select_app_restart_", "")
        await confirm_restart(query, app_name)
    elif data.startswith("confirm_restart_"):
        app_name = data.replace("confirm_restart_", "")
        await restart_dyno(query, app_name)
    elif data.startswith("select_app_manage_"):
        app_name = data.replace("select_app_manage_", "")
        await show_dyno_management_options(query, app_name)
    elif data.startswith("resize_dyno_"):
        # Robust parsing for app names that might contain underscores
        app_name = '_'.join(parts[2:-2])
        dyno_type = parts[-2]
        size = parts[-1]
        await resize_dyno(query, app_name, dyno_type, size)
    elif data.startswith("scale_dyno_"):
        app_name = '_'.join(parts[2:-2])
        dyno_type = parts[-2]
        quantity = parts[-1]
        await scale_dyno(query, app_name, dyno_type, int(quantity))

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
    await query.message.edit_text(f"Are you sure you want to restart all dynos for `{app_name}`?",
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")

async def restart_dyno(query, app_name: str):
    """Restarts all dynos for a specific app."""
    await query.message.edit_text(f"🔄 Restarting dynos for `{app_name}`...", parse_mode="MarkdownV2")
    heroku_conn = get_heroku_conn(HEROKU_API_KEY)
    try:
        app = heroku_conn.apps()[app_name]
        app.restart()
        await query.message.edit_text(f"✅ Successfully restarted all dynos for `{app_name}`.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_restart")]]),
                                      parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Failed to restart dyno for {app_name}: {e}")
        await query.message.edit_text(f"❌ Failed to restart dynos. Error: {e}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_restart")]]))

async def show_dyno_management_options(query, app_name: str):
    """Shows current dyno status and options to change size or quantity."""
    heroku_conn = get_heroku_conn(HEROKU_API_KEY)
    try:
        app = heroku_conn.apps()[app_name]
        web_formation = app.process_formation().get('web')

        if not web_formation:
            await query.message.edit_text(f"No 'web' dyno formation found for `{app_name}`.", parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="manage_apps")]]))
            return
            
        current_size = web_formation.size
        current_quantity = web_formation.quantity

        text = (f"App: `{app_name}`\n"
                f"Current Formation: `web` dyno\n"
                f" ┣ Size: `{current_size}`\n"
                f" ┗ Quantity: `{current_quantity}`\n\n"
                f"Select an action:")

        keyboard = [
            [InlineKeyboardButton("Change Size (Type)", callback_data="noop")],
            [
                InlineKeyboardButton("Eco", callback_data=f"resize_dyno_{app_name}_web_eco"),
                InlineKeyboardButton("Standard-1X", callback_data=f"resize_dyno_{app_name}_web_standard-1x"),
                InlineKeyboardButton("Standard-2X", callback_data=f"resize_dyno_{app_name}_web_standard-2x"),
            ],
            [InlineKeyboardButton("Change Quantity", callback_data="noop")],
            [
                InlineKeyboardButton("0", callback_data=f"scale_dyno_{app_name}_web_0"),
                InlineKeyboardButton("1", callback_data=f"scale_dyno_{app_name}_web_1"),
                InlineKeyboardButton("2", callback_data=f"scale_dyno_{app_name}_web_2"),
            ],
            [InlineKeyboardButton("« Back to App List", callback_data="list_apps_manage")]
        ]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Failed to get dyno info for {app_name}: {e}")
        await query.message.edit_text(f"❌ Failed to get dyno info. Error: {e}")

async def resize_dyno(query, app_name: str, dyno_type: str, size: str):
    """Changes the dyno size (e.g., to standard-1x)."""
    await query.message.edit_text(f"Resizing `{dyno_type}` dyno for `{app_name}` to `{size}`...", parse_mode="MarkdownV2")
    heroku_conn = get_heroku_conn(HEROKU_API_KEY)
    try:
        app = heroku_conn.apps()[app_name]
        formation = app.process_formation()[dyno_type]
        formation.update(size=size)
        await query.message.edit_text(f"✅ Successfully resized `{dyno_type}` dyno to `{size}`.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"« Back to {app_name}", callback_data=f"select_app_manage_{app_name}")]]),
                                      parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Failed to resize dyno for {app_name}: {e}")
        await query.message.edit_text(f"❌ Failed to resize dyno. Error: {e}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"« Back to {app_name}", callback_data=f"select_app_manage_{app_name}")]]))


async def scale_dyno(query, app_name: str, dyno_type: str, quantity: int):
    """Changes the dyno quantity for an app (horizontal scaling)."""
    await query.message.edit_text(f"📊 Scaling `{dyno_type}` dyno for `{app_name}` to `{quantity}`...", parse_mode="MarkdownV2")
    heroku_conn = get_heroku_conn(HEROKU_API_KEY)
    try:
        app = heroku_conn.apps()[app_name]
        formation = app.process_formation()[dyno_type]
        formation.update(quantity=quantity)
        await query.message.edit_text(f"✅ Successfully scaled `{dyno_type}` dyno for `{app_name}` to `{quantity}`.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"« Back to {app_name}", callback_data=f"select_app_manage_{app_name}")]]),
                                      parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Failed to scale dyno for {app_name}: {e}")
        await query.message.edit_text(f"❌ Failed to scale dyno. Error: {e}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"« Back to {app_name}", callback_data=f"select_app_manage_{app_name}")]]))

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
