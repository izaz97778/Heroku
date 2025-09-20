import os
import logging
import heroku3
import pymongo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Connection ---
if not MONGO_URI:
    logger.critical("MONGO_URI environment variable not set. Exiting.")
    exit(1)

try:
    client = pymongo.MongoClient(MONGO_URI)
    db = client.get_database("HerokuBotDB")
    user_collection = db.get_collection("users")
    client.admin.command('ping') # Test the connection
    logger.info("Successfully connected to MongoDB.")
except Exception as e:
    logger.critical(f"Could not connect to MongoDB: {e}")
    exit(1)

# --- Conversation Handler States ---
ASK_EMAIL, ASK_API_KEY = range(2)

# --- Helper Functions ---
def get_heroku_conn(api_key: str):
    """Establishes a connection to the Heroku API."""
    try:
        return heroku3.from_key(api_key)
    except Exception:
        return None

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = "Main Menu", message_id: int = None):
    """Displays the main menu buttons."""
    keyboard = [
        [InlineKeyboardButton("🔐 Login to Heroku", callback_data="login")],
        [InlineKeyboardButton("⚙️ Manage Apps", callback_data="manage_apps")],
        [InlineKeyboardButton("🚪 Logout", callback_data="logout")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if message_id:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=message_id, text=text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
         await update.callback_query.edit_message_text(text, reply_markup=reply_markup)

async def show_app_management_menu(query):
    """Shows the app management options."""
    keyboard = [
        [InlineKeyboardButton("🔄 Restart Dynos", callback_data="list_apps_restart")],
        [InlineKeyboardButton("📊 Change Dyno Quantity", callback_data="list_apps_scale")],
        [InlineKeyboardButton("« Back to Main Menu", callback_data="main_menu")],
    ]
    await query.edit_message_text("App Management:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Main Command and Login Flow ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the main menu when the /start command is issued."""
    await show_main_menu(update, context, "Welcome to the Heroku Management Bot! 👋\n\nPlease log in to manage your applications.")

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the login conversation by asking for the email."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please send me your Heroku account email address.\n\n"
        "You can type /cancel to abort."
    )
    return ASK_EMAIL

async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the email and asks for the API Key."""
    context.user_data['heroku_email'] = update.message.text.strip()
    await update.message.reply_text(
        "Great. Now, please send me your Heroku API Key.\n\n"
        "⚠️ **Warning**: Your API key grants full access to your account."
    )
    return ASK_API_KEY

async def get_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives, validates, and saves the Heroku API Key."""
    user_id = update.message.from_user.id
    api_key = update.message.text.strip()
    
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete API key message: {e}")

    await update.message.reply_text("Authenticating...")
    heroku_conn = get_heroku_conn(api_key)

    if heroku_conn:
        user_collection.update_one(
            {"_id": user_id},
            {"$set": {"heroku_api_key": api_key}},
            upsert=True
        )
        await update.message.reply_text("✅ **Login successful!** Your credentials have been saved.")
        await show_main_menu(update, context, "What would you like to do next?")
    else:
        await update.message.reply_text("❌ **Authentication failed!** The API key seems invalid.")
        await show_main_menu(update, context)
        
    if 'heroku_email' in context.user_data:
        del context.user_data['heroku_email']
        
    return ConversationHandler.END

async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the login conversation."""
    if 'heroku_email' in context.user_data:
        del context.user_data['heroku_email']
    await update.message.reply_text("Login cancelled.")
    await show_main_menu(update, context)
    return ConversationHandler.END

# --- Button Handler and Core Logic ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline button presses."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "logout":
        await logout_user(query)
        return

    user_doc = user_collection.find_one({"_id": user_id})
    if data != "main_menu" and (not user_doc or "heroku_api_key" not in user_doc):
        await query.edit_message_text(
            "You are not logged in. Please login first.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Login", callback_data="login")]])
        )
        return

    # --- Routing ---
    if data == "manage_apps":
        await show_app_management_menu(query)
    elif data == "main_menu":
        await show_main_menu(update, context, message_id=query.message.message_id)
    elif data == "list_apps_restart":
        await list_apps(query, "restart")
    elif data.startswith("select_app_restart_"):
        app_name = data.replace("select_app_restart_", "")
        await confirm_restart(query, app_name)
    elif data.startswith("confirm_restart_"):
        app_name = data.replace("confirm_restart_", "")
        await restart_dyno(query, user_id, app_name)
    elif data == "list_apps_scale":
        await list_apps(query, "scale")
    elif data.startswith("select_app_scale_"):
        app_name = data.replace("select_app_scale_", "")
        await show_scale_options(query, user_id, app_name)
    elif data.startswith("scale_dyno_"):
        _, app_name, dyno_type, quantity = data.split("_", 3)
        await scale_dyno(query, user_id, app_name, dyno_type, int(quantity))

async def logout_user(query: Update.callback_query):
    """Logs the user out and displays the main menu."""
    user_id = query.from_user.id
    result = user_collection.delete_one({"_id": user_id})
    
    if result.deleted_count > 0:
        text = "✅ You have been successfully logged out."
    else:
        text = "You were not logged in."
        
    keyboard = [
        [InlineKeyboardButton("🔐 Login to Heroku", callback_data="login")],
        [InlineKeyboardButton("⚙️ Manage Apps", callback_data="manage_apps")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def list_apps(query, action_type: str):
    """Fetches and lists user's apps as buttons."""
    user_id = query.from_user.id
    user_doc = user_collection.find_one({"_id": user_id})
    api_key = user_doc.get("heroku_api_key")

    if not api_key:
        await query.edit_message_text("Could not find your API key. Please login again.")
        return

    await query.edit_message_text("⏳ Fetching your apps...")
    heroku_conn = get_heroku_conn(api_key)
    try:
        apps = heroku_conn.apps()
        if not apps:
            await query.edit_message_text("You don't have any Heroku apps.",
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="manage_apps")]]))
            return

        keyboard = []
        for app in apps:
            callback_data = f"select_app_{action_type}_{app.name}"
            keyboard.append([InlineKeyboardButton(app.name, callback_data=callback_data)])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="manage_apps")])
        
        prompt = "Select an app to restart its dynos:" if action_type == "restart" else "Select an app to scale its dynos:"
        await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Failed to fetch apps: {e}")
        await query.edit_message_text(f"An error occurred while fetching your apps. Details: {e}")

# --- Dyno Actions ---
async def confirm_restart(query, app_name: str):
    """Asks for confirmation before restarting."""
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Restart", callback_data=f"confirm_restart_{app_name}")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data="list_apps_restart")]
    ]
    await query.edit_message_text(f"Are you sure you want to restart all dynos for **{app_name}**?",
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def restart_dyno(query, user_id: int, app_name: str):
    """Restarts all dynos for a specific app."""
    await query.edit_message_text(f"🔄 Restarting dynos for **{app_name}**...", parse_mode="Markdown")
    user_doc = user_collection.find_one({"_id": user_id})
    api_key = user_doc.get("heroku_api_key")
    if not api_key:
        await query.edit_message_text("Could not find credentials. Please login again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="manage_apps")]]))
        return
        
    heroku_conn = get_heroku_conn(api_key)
    try:
        app = heroku_conn.apps[app_name]
        app.restart()
        await query.edit_message_text(f"✅ Successfully restarted all dynos for **{app_name}**.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_restart")]]),
                                      parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to restart dyno for {app_name}: {e}")
        await query.edit_message_text(f"❌ Failed to restart dynos for {app_name}. Error: {e}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_restart")]]))

async def show_scale_options(query, user_id: int, app_name: str):
    """Shows current dyno count and scaling options."""
    user_doc = user_collection.find_one({"_id": user_id})
    api_key = user_doc.get("heroku_api_key")
    if not api_key:
        await query.edit_message_text("Could not find credentials. Please login again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="manage_apps")]]))
        return
        
    heroku_conn = get_heroku_conn(api_key)
    try:
        app = heroku_conn.apps[app_name]
        web_dynos = [d for d in app.dynos() if d.type == 'web']
        current_quantity = len(web_dynos)
        text = f"App: **{app_name}**\n" \
               f"Current 'web' dynos: **{current_quantity}**\n\n" \
               "Select a new quantity for the 'web' dyno:"
        keyboard = [
            [
                InlineKeyboardButton("0 (Turn Off)", callback_data=f"scale_dyno_{app_name}_web_0"),
                InlineKeyboardButton("1 (Turn On)", callback_data=f"scale_dyno_{app_name}_web_1"),
            ],
            [InlineKeyboardButton("« Back to Apps", callback_data="list_apps_scale")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to get dyno info for {app_name}: {e}")
        await query.edit_message_text(f"❌ Failed to get dyno info for {app_name}. Error: {e}")

async def scale_dyno(query, user_id: int, app_name: str, dyno_type: str, quantity: int):
    """Changes the dyno quantity for an app."""
    await query.edit_message_text(f"📊 Scaling **{dyno_type}** dyno for **{app_name}** to **{quantity}**...", parse_mode="Markdown")
    user_doc = user_collection.find_one({"_id": user_id})
    api_key = user_doc.get("heroku_api_key")
    if not api_key:
        await query.edit_message_text("Could not find credentials. Please login again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="manage_apps")]]))
        return
        
    heroku_conn = get_heroku_conn(api_key)
    try:
        app = heroku_conn.apps[app_name]
        app.scale_dyno(dyno_type, quantity)
        await query.edit_message_text(f"✅ Successfully scaled **{dyno_type}** dyno for **{app_name}** to **{quantity}**.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_scale")]]),
                                      parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to scale dyno for {app_name}: {e}")
        await query.edit_message_text(f"❌ Failed to scale dyno for {app_name}. Error: {e}",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Apps", callback_data="list_apps_scale")]]))

# --- Main Application Setup ---
def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
        exit(1)
        
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    login_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_start, pattern="^login$")],
        states={
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            ASK_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_api_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel_login)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(login_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
