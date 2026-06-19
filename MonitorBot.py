import logging
import time
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, CallbackContext
import instaloader
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
import pytz  # Import pytz

# Replace with your bot token
TOKEN = 'BOT_TOKEN'

# Replace with your chat ID
CHAT_ID = 'TELE_ID'

# Set up the logger
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Dictionary to hold the list of monitored Instagram accounts
monitored_accounts = {}

# Scheduler setup with timezone set to UTC
scheduler = BackgroundScheduler(jobstores={'default': MemoryJobStore()})
scheduler.configure(timezone=pytz.utc)  # Explicitly set timezone to UTC
scheduler.start()

# Initialize the bot globally
bot_instance = Bot(token=TOKEN)

# Initialize Instaloader instance
L = instaloader.Instaloader()

# Function to check the status of an Instagram account using Instaloader
def check_instagram_status(account):
    try:
        # Try to fetch the profile
        profile = instaloader.Profile.from_username(L.context, account)
        
        # If we can fetch the profile successfully, it's considered "Active"
        return "Active"
    except instaloader.exceptions.ProfileNotExistsException:
        # This exception occurs if the profile doesn't exist (or is banned)
        logger.warning(f"Profile for {account} does not exist or is banned.")
        return "Banned"
    except instaloader.exceptions.ConnectionException as e:
        # This exception occurs if there is a network-related issue
        logger.error(f"Connection error while checking {account}: {str(e)}")
        return "Error accessing Instagram"
    except instaloader.exceptions.QueryReturnedBadRequestException as e:
        # Handle cases when Instagram responds with a bad request
        logger.error(f"Bad request error while checking {account}: {str(e)}")
        return "Error accessing Instagram"
    except Exception as e:
        # Catch any unexpected exceptions and log them
        logger.error(f"Unexpected error while checking {account}: {str(e)}")
        return "Unknown error"

# Function to monitor a specific account and send updates to the user
def monitor_account(account):
    logger.info(f"Checking account: {account}")
    status = check_instagram_status(account)
    
    if account in monitored_accounts:
        previous_status = monitored_accounts[account]["status"]
        
        if previous_status != status:
            monitored_accounts[account]["status"] = status
            current_time = time.time()

            if status == "Active" and previous_status == "Banned":
                time_taken = current_time - monitored_accounts[account]["start_time"]
                hours, remainder = divmod(time_taken, 3600)
                minutes, seconds = divmod(remainder, 60)

                for user_id in monitored_accounts[account]["users"]:
                    bot_instance.send_message(
                        user_id,
                        f"Good news! [@{account}] is Unbanned! 🎉\n"
                        f"It took {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds to recover."
                    )
                logger.info(f"Unban notification sent for account: {account}")

            elif status == "Banned" and previous_status != "Banned":
                time_monitored = current_time - monitored_accounts[account]["start_time"]
                hours, remainder = divmod(time_monitored, 3600)
                minutes, seconds = divmod(remainder, 60)

                for user_id in monitored_accounts[account]["users"]:
                    bot_instance.send_message(
                        user_id,
                        f"[@{account}] is Banned. 🚫\n"
                        f"It was monitored for {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds."
                    )
                logger.info(f"Ban notification sent for account: {account}")

            else:
                for user_id in monitored_accounts[account]["users"]:
                    bot_instance.send_message(
                        user_id,
                        f"Status of Instagram account @{account} has changed to {status}."
                    )
                logger.info(f"Status update notification sent for account: {account}")
        else:
            logger.info(f"No status change for account: {account}")

# Function to start monitoring an account
async def start_monitoring(update: Update, context: CallbackContext):
    user = update.message.from_user
    if len(context.args) == 0:
        await update.message.reply_text(
            "Please provide an Instagram username to monitor. Example: /monitor username"
        )
        return
    
    account = context.args[0]
    if account in monitored_accounts:
        monitored_accounts[account]["users"].add(user.id)
        await update.message.reply_text(f"You're already monitoring {account}.")
    else:
        monitored_accounts[account] = {
            "status": "Checking...",
            "users": {user.id},
            "start_time": time.time()
        }
        scheduler.add_job(
            monitor_account,
            'interval',
            seconds=10,  # Check every 10 seconds
            args=[account],
            id=account,
            replace_existing=True
        )
        logger.info(f"Started monitoring Instagram account: {account}")
        await update.message.reply_text(f"Started monitoring Instagram account: {account}")

# Function to check if an account is banned
async def check_ban(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        await update.message.reply_text(
            "Please provide an Instagram username to check. Example: /ban username"
        )
        return

    account = context.args[0]
    status = check_instagram_status(account)
    if status == "Banned":
        await update.message.reply_text(f"[@{account}] is currently Banned.")
    else:
        await update.message.reply_text(f"[@{account}] is not Banned. Current status: {status}")

# Function to check the status of an Instagram account immediately
async def check_status(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        await update.message.reply_text(
            "Please provide an Instagram username to check. Example: /status username"
        )
        return

    account = context.args[0]
    status = check_instagram_status(account)
    await update.message.reply_text(f"Status of {account}: {status}")

# Function to stop monitoring an Instagram account
async def stop_monitoring(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        await update.message.reply_text(
            "Please provide an Instagram username to remove from monitoring. Example: /remove username"
        )
        return

    account = context.args[0]
    if account in monitored_accounts:
        user_id = update.message.from_user.id
        monitored_accounts[account]["users"].discard(user_id)
        if not monitored_accounts[account]["users"]:
            scheduler.remove_job(account)
            del monitored_accounts[account]
            logger.info(f"Stopped monitoring account: {account}")
            await update.message.reply_text(f"Stopped monitoring Instagram account: {account}")
        else:
            await update.message.reply_text(
                f"You've been removed from monitoring {account}."
            )
    else:
        await update.message.reply_text(f"{account} is not being monitored.")

# Function to list all monitored accounts
async def list_jobs(update: Update, context: CallbackContext):
    jobs = scheduler.get_jobs()
    if jobs:
        job_list = "\n".join([f"{job.id}: {monitored_accounts[job.id]['status']}" for job in jobs])
        await update.message.reply_text(f"Currently monitored accounts:\n{job_list}")
    else:
        await update.message.reply_text("No accounts are currently being monitored.")

# Help function
async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text("""
    /monitor <username> - Start monitoring the specified Instagram account to get unban.
    /status <username> - Check the status of the specified Instagram account immediately.
    /ban <username> - Check if the specified Instagram account is banned.
    /remove <username> - Stop monitoring the specified Instagram account.
    /list_jobs - List all currently monitored accounts.
    /help - Show The Help Settings.
    """)

# Start function to greet users
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("""
    Hello! I'm your Instagram account monitoring bot. I can help you monitor the status of Instagram accounts. Here are the commands you can use:
    - /monitor <username>: Start monitoring an Instagram account.
    - /status <username>: Check the status (Active/Banned) of an Instagram account immediately.
    - /ban <username>: Check if an account is banned.
    - /remove <username>: Stop monitoring an Instagram account.
    - /list_jobs: List all currently monitored accounts.
    - /help: Show The Help Settings.
    """)

# Main function to handle commands
def main():
    application = Application.builder().token(TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("monitor", start_monitoring))
    application.add_handler(CommandHandler("status", check_status))
    application.add_handler(CommandHandler("ban", check_ban))
    application.add_handler(CommandHandler("remove", stop_monitoring))
    application.add_handler(CommandHandler("list_jobs", list_jobs))
    application.add_handler(CommandHandler("help", help_command))

    # Run the bot
    application.run_polling()

# Corrected block to run the script
if __name__ == '__main__':
    main()