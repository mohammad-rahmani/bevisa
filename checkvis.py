from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import sqlite3
import logging
import requests
from bs4 import BeautifulSoup
import random
import time
from unidecode import unidecode

# Constants
SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(SCRIPT_DIRECTORY, "bot-token.txt")
DB_PATH = os.path.join(SCRIPT_DIRECTORY, "data.db")
MAX_CASES = 4

# Define the dictionary for translations
status_translations = {
    "in behandeling": "In progress",
    "aanvullende documenten": "Additional documents required",
    "aanvaarding": "Approved",
    "akkoord": "Approved",
    "weigering": "Rejected"
}

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def to_english_digits(text) -> str:
    return unidecode(text)

def write_to_db(user_id: int, word: str, case_number: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_commands (user_id, word, case_number) VALUES (?, ?, ?)", (user_id, word, case_number))
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {str(e)}")
        success = False
    finally:
        conn.close()
    
    return success

def read_from_db(user_id: int, word: str) -> str:
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
        return result[0]
    else:
        return ""

def remove_from_db(user_id: int, word: str) -> bool:
    # Remove the word from the database
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_commands WHERE user_id = ? AND word = ?", (user_id, word))
        conn.commit()
        success = True
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {str(e)}")
        success = False
    finally:
        conn.close()

    return success

def get_user_word_case_pairs(user_id: int) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT word, case_number FROM user_commands WHERE user_id = ?", (user_id,))
        results = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {str(e)}")
        results = []
    finally:
        conn.close()

    return results

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
    update.message.reply_text("Welcome to the Belgian Visa Check bot! Please send me a case number or use commands from the menu.")

def analyze_case(case_number: int) -> (str, str):
    url = f"https://infovisa.ibz.be/ResultNl.aspx?place=THR&visumnr={case_number}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving data from DVZ: {str(e)}")
        return "Error retrieving data from DVZ.", ""
    
    soup = BeautifulSoup(response.content, 'html.parser')
    dossiernr_element = soup.find(id="dossiernr")
    if dossiernr_element:
        return f"Your search returned no result in DVZ database.", ""

    table = soup.find('table')
    if not table:
        return f"{case_number}: Error.", ""
    
    rows = table.find_all('tr')
    row_state = rows[5].find_all(['th', 'td'])
    case_state = row_state[1].get_text(strip=True)
    row_date = rows[6].find_all(['th', 'td'])
    case_date = row_date[1].get_text(strip=True)
    if not case_date:
        row_date = rows[4].find_all(['th', 'td'])
        case_date = row_date[1].get_text(strip=True)
    # Get the English translation using the dictionary
    case_state_en = status_translations.get(case_state.lower(), case_state)
    short_answer = f'Status: *{case_state_en}*\n(Update: _{case_date}_)'
    long_answer = "\n"
    for row in rows:
        cells = row.find_all(['th', 'td'])
        row_text = f'*{cells[0].get_text(strip=True)}*'
        row_text += (f'\n_{cells[1].get_text(strip=True)}_' if cells[1].get_text(strip=True) else "")
        long_answer += row_text + '\n'

    return short_answer, long_answer

def define(update: Update, context: CallbackContext) -> None:
    args = context.args

    # Check usage
    if len(args) != 2:
        update.message.reply_text("Usage: /define <word> <case_number>")
        return

    word, case_number = args[0], to_english_digits(args[1])

    # Check if the word starts with an alphabetic character
    if not word[0].isalpha():
        update.message.reply_text("The word should start with an alphabetic character.")
        return

    # Check if case_number contains only digits
    if not case_number.isdigit():
        update.message.reply_text("The case number should contain only digits.")
        return

    # Check if maximum number of saved cases for the user has reached
    user_id = update.message.from_user.id
    cases = get_user_word_case_pairs(user_id)
    num_cases = len(cases)
    if num_cases >= MAX_CASES:
        update.message.reply_text(f"Maximum number of cases reached. Consider removing ones you don't need first.")
        return

    if write_to_db(user_id, word, case_number):
        update.message.reply_text(f"Learned: {word} => {case_number}")

def remove(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    args = context.args

    # Check usage
    if len(args) != 1:
        update.message.reply_text("Usage: /remove <word>")
        return

    word_to_remove = args[0]

    # Check if the word starts with an alphabetic character
    if not word_to_remove[0].isalpha():
        update.message.reply_text("The word should start with an alphabetic character.")
        return

    # Check if the word exists in the database for the user
    current_word = read_from_db(user_id, word_to_remove)

    if current_word:
        if remove_from_db(user_id, word_to_remove):
            update.message.reply_text(f"'{word_to_remove}' was removed from your dictionary.")
        else:
            update.message.reply_text(f"Could not remove '{word_to_remove}' from your dictionary.")
    else:
        update.message.reply_text(f"'{word_to_remove}' was not found in your dictionary.")

def retrieve_all_states(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    cases = get_user_word_case_pairs(user_id)

    for row in cases:
        word, case_number = row
        if case_number:
            short_result, long_result = analyze_case(case_number)
            short_result = f'{word} ({case_number})\n{short_result}'
            update.message.reply_text(short_result, parse_mode="Markdown")
            time.sleep(random.uniform(0.2, 1.2))

def get_association(update: Update, word: str) -> None:
    user_id = update.message.from_user.id
    case_number = read_from_db(user_id, word)

    if case_number:
        # update.message.reply_text(f"Checking latest information for '{word}' ({case_number})")
        short_result, long_result = analyze_case(case_number)
        short_result = f'{word} ({case_number})\n{short_result}'
        update.message.reply_text(short_result, parse_mode="Markdown")
    else:
        update.message.reply_text(f"No association found for '{word}'")

def check_message(update: Update, context: CallbackContext) -> None:
    msg_text = update.message.text.strip()

    if msg_text.isdigit():
        msg_text = to_english_digits(msg_text)
        short_result, long_result = analyze_case(msg_text)
        short_result = f'{msg_text}\n{short_result}'
        update.message.reply_text(short_result, parse_mode="Markdown")
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
    dp.add_handler(CommandHandler("remove", remove, pass_args=True))
    dp.add_handler(CommandHandler("all", retrieve_all_states))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, check_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
