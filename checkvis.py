from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import sqlite3
import logging
import requests
from bs4 import BeautifulSoup

# Constants
SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(SCRIPT_DIRECTORY, "bot-token.txt")
DB_PATH = os.path.join(SCRIPT_DIRECTORY, "data.db")

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_bot_token():
    try:
        with open(TOKEN_PATH, 'r') as file:
            return file.readline().strip()
    except FileNotFoundError:
        logger.error(f"The file '{TOKEN_PATH}' does not exist.")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
    return None

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Welcome to the Case Analysis Bot! Please send me a case number.")

def analyze_case(case_number: int) -> str:
    url = f"https://infovisa.ibz.be/ResultNl.aspx?place=THR&visumnr={case_number}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        dossiernr_element = soup.find(id="dossiernr")

        if dossiernr_element:
            return f"{case_number}: Your search returned no result in DVZ database."

        table = soup.find('table')

        if table:
            table_text = "\n"
            for row in table.find_all('tr'):
                cells = row.find_all(['th', 'td'])
                row_text = f'*{cells[0].get_text(strip=True)}*'
                row_text += (f'\n_{cells[1].get_text(strip=True)}_' if cells[1].get_text(strip=True) else "")
                table_text += row_text + '\n'
            return table_text
        else:
            return f"{case_number}: Error."
    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving data from DVZ: {str(e)}")
        return "Error retrieving data from DVZ."

def define(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    args = context.args

    if len(args) != 2:
        update.message.reply_text("Usage: /define <word> <case_number>")
        return

    word, case_number = args[0], args[1]

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_commands (user_id, word, case_number) VALUES (?, ?, ?)", (user_id, word, case_number))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {str(e)}")
    finally:
        conn.close()

    update.message.reply_text(f"Defined: {word} => {case_number}")

def get_association(update: Update, word: str) -> None:
    user_id = update.message.from_user.id

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT case_number FROM user_commands WHERE user_id = ? AND word = ?", (user_id, word))
        result = cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {str(e)}")
    finally:
        conn.close()

    if result:
        case_number = result[0]
        update.message.reply_text(f"The case number for '{word}' is: {case_number}")
    else:
        update.message.reply_text(f"No association found for '{word}'")

def check_message(update: Update, context: CallbackContext) -> None:
    msg_text = update.message.text.strip()

    if msg_text.isdigit():
        analysis_result = analyze_case(msg_text)
        update.message.reply_text(analysis_result, parse_mode="Markdown")
    else:
        get_association(update=update, word=msg_text)

def main():
    bot_token = get_bot_token()
    if not bot_token:
        logger.error("Bot token not found. Exiting.")
        return

    updater = Updater(bot_token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("define", define, pass_args=True))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, check_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
