from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import os
import sqlite3
import logging
import requests
from bs4 import BeautifulSoup
import random
import time
from datetime import datetime
import pytz
from unidecode import unidecode
import re

# Constants
SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(SCRIPT_DIRECTORY, "bot-token.txt")
DB_PATH = os.path.join(SCRIPT_DIRECTORY, "data.db")
MAX_CASES = 4

# Specify the timezone
bru_timezone = pytz.timezone("Europe/Brussels")

# Define the dictionary for translations
status_translations = {
    "in behandeling": "Processing 📝",
    "aanvullende documenten": "Additional documents required 📎",
    "aanvaarding": "Approved ✅",
    "akkoord": "Approved ✅",
    "weigering": "Rejected ❌",
    "toekenning visum op voorlegging bijkomende stukken.": "Visa granted upon submission of additional documents 📎",
}

# Define the dictionary for encoding status
status_codes = {
    "in behandeling": 1,
    "aanvullende documenten": 2,
    "aanvaarding": 3,
    "akkoord": 4,
    "weigering": 5,
    "toekenning visum op voorlegging bijkomende stukken.": 6,
}

row_titles = [
    "Visumaanvraagnummer:",
    "ReferenceNummer:",
    "Diplomatic Post:",
    "Datum visumaanvraag:",
    "Datum registratie visumaanvraag door Dienst Vreemdelingenzaken:",
    "Beslissing/Status Dossier:",
    "Datum beslissing/Status Dossier:",
    "extra info1:",
    "extra info2:" 
    ]

extra_info1 = "Indien een dossier nog in behandeling is of indien het dossier nog niet behandeld is omdat gewacht wordt op de verzending per diplomatieke valies van de documenten die de visumaanvraag ondersteunen, verschijnt als datum, de datum waarop de visumaanvraag geregistreerd werd door de Dienst Vreemdelingenzaken."
extra_info2 = "In principe wordt de beslissing verzonden op de dag dat ze getroffen wordt. Het kan echter soms enkele dagen duren voordat de diplomatieke of consulaire post de beslissing effectief ontvangt."

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def to_english_digits(text) -> str:
    return unidecode(text)

def escape_markdownv2_special_chars(text):
    # Define a list of special characters in MarkdownV2
    special_chars = ['*', '_', '~', '`', '|', '>', '#', '+', '-', '=', '{', '}', '(', ')', '[', ']', '.', '!']

    # Escape the special characters using regular expressions
    for char in special_chars:
        text = re.sub(re.escape(char), '\\' + char, text)

    return text

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the Belgian Visa Check bot! Please send me a case number or use commands from the menu.")

def date_string_to_bytearray(date_str):
    # Parse the date string into a datetime object
    date_obj = datetime.strptime(date_str, "%b %d %Y")
    
    # Extract the month, day, and year as integers
    month = date_obj.month
    day = date_obj.day
    year = date_obj.year % 100  # Get the last two digits of the year
    
    # Create a byte array with the extracted values
    byte_array = bytearray([month, day, year])
    
    return byte_array

# Summurizes case info so that it fits in reply markup's callback data (max 64 bytes!)
def encode_result_table(rows, case_number: str) -> str:
    if not len(rows) == 9:
        return ""
    
    payload = ""
    # Visumaanvraagnummer
    value = rows[0][1]
    value = value[:-len(str(case_number))]
    pattern = r'(0+)$'  # A regular expression pattern to match trailing zeros
    trailing_zeros = len(re.search(pattern, value).group(0))
    prefix = value[:-trailing_zeros]
    payload += prefix + '\x00' + chr(trailing_zeros) + '\x00'

    # ReferenceNummer
    value = rows[1][1]
    payload += value + '\x00'

    # Diplomatic Post
    value = rows[2][1]
    payload += value + '\x00'

    # Datum visumaanvraag
    value = rows[3][1]
    if value:
        payload += ''.join(chr(byte_value) for byte_value in date_string_to_bytearray(value)) + '\x00'
    else:
        payload += chr(13) + '\x00'

    # Datum registratie visumaanvraag door Dienst Vreemdelingenzaken
    value = rows[4][1]
    if value:
        payload += ''.join(chr(byte_value) for byte_value in date_string_to_bytearray(value)) + '\x00'
    else:
        payload += chr(13) + '\x00'

    # Beslissing/Status Dossier
    value = rows[5][1]
    code = status_codes.get(value.lower(), 100)
    payload += chr(code) + '\x00'

    # Datum beslissing/Status Dossier
    value = rows[6][1]
    if value:
        payload += ''.join(chr(byte_value) for byte_value in date_string_to_bytearray(value)) + '\x00'
    else:
        payload += chr(13) + '\x00'

    # extra info1
    global extra_info1
    value = rows[7][1]
    if value:
        extra_info1 = value
        payload += 't' + '\x00'
    else:
        payload += 'f' + '\x00'

    # extra info2
    global extra_info2
    value = rows[8][1]
    if value:
        extra_info2 = value
        payload += 't' + '\x00'
    else:
        payload += 'f' + '\x00'

    return payload

def decode_result_table(encoded_result: str, case_number: str) -> list:
    rows = []
    index = 0

    # Function to extract a null-terminated string from the encoded result
    def extract_string():
        nonlocal index
        result = ""
        while index < len(encoded_result) and encoded_result[index] != '\x00':
            result += encoded_result[index]
            index += 1
        index += 1  # Skip the null-terminator
        return result

    # Visumaanvraagnummer
    prefix = extract_string()
    trailing_zeros = ord(extract_string())
    full_case_number = prefix + '0' * trailing_zeros + str(case_number)
    rows.append(["Visumaanvraagnummer:", full_case_number])

    # ReferenceNummer
    reference_number = extract_string()
    rows.append(["ReferenceNummer:", reference_number])

    # Diplomatic Post
    diplomatic_post = extract_string()
    rows.append(["Diplomatic Post:", diplomatic_post])

    # Datum visumaanvraag
    date_visumaanvraag = extract_string()
    date_str = ''.join([str(ord(char)).zfill(2) for char in date_visumaanvraag])
    date_visumaanvraag = "" if date_str == "13" else datetime.strptime(date_str, "%m%d%y").strftime("%b %d %Y")
    rows.append(["Datum visumaanvraag:", date_visumaanvraag])

    # Datum registratie visumaanvraag door Dienst Vreemdelingenzaken
    date_registratie = extract_string()
    date_str = ''.join([str(ord(char)).zfill(2) for char in date_registratie])
    date_registratie = "" if date_str == "13" else datetime.strptime(date_str, "%m%d%y").strftime("%b %d %Y")
    rows.append(["Datum registratie visumaanvraag door Dienst Vreemdelingenzaken:", date_registratie])

    # Beslissing/Status Dossier
    status_code = ord(extract_string())
    for key, value in status_codes.items():
        if value == status_code:
            status_dossier = key
            break
    else:
        status_dossier = "Unknown"
    rows.append(["Beslissing/Status Dossier:", status_dossier])

    # Datum beslissing/Status Dossier
    date_beslissing = extract_string()
    date_str = ''.join([str(ord(char)).zfill(2) for char in date_beslissing])
    date_beslissing = "" if date_str == "13" else datetime.strptime(date_str, "%m%d%y").strftime("%b %d %Y")
    rows.append(["Datum beslissing/Status Dossier:", date_beslissing])

    # extra info1
    extra_info1_exists = extract_string() == 't'
    rows.append(["extra info1:", extra_info1 if extra_info1_exists else ""])

    # extra info2
    extra_info2_exists = extract_string() == 't'
    rows.append(["extra info2:", extra_info2 if extra_info2_exists else ""])

    return rows

def form_brief_answer(rows: list) -> str:
    # Hard coded row number of case state: 5
    case_state = rows[5][1]
    case_state_en = status_translations.get(case_state.lower(), case_state)
    case_state_en = escape_markdownv2_special_chars(case_state_en)

    # Hard coded row number of case date: 6 if rows[6][1] else 4
    case_date = rows[6][1] if rows[6][1] else rows[4][1]
    case_date = escape_markdownv2_special_chars(case_date)

    # Return with Markdown V2 format:
    return f"Status: *{case_state_en}*\n\(Update: _{case_date}_\)"

def form_long_answer(rows: list) -> str:
    long_answer = "\n"
    for row in rows:
        title = escape_markdownv2_special_chars(row[0])
        value = escape_markdownv2_special_chars(row[1])
        row_text = f'*{title}*'
        row_text += (f'\n_{value}_' if value else "")
        long_answer += row_text + '\n'

    return long_answer

def analyze_case(case_number: int) -> (str, str):
    url = f"https://infovisa.ibz.be/ResultNl.aspx?place=THR&visumnr={case_number}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error retrieving data from DVZ: {str(e)}")
        return "Error retrieving data from DVZ\.", ""
    
    soup = BeautifulSoup(response.content, 'html.parser')
    dossiernr_element = soup.find(id="dossiernr")
    if dossiernr_element:
        return f"Your search returned no result in DVZ database\.", ""

    table = soup.find('table')
    if not table:
        return f"Result could not be resolved\. Please manually check in DVZ website\.", ""
    
    html_rows = table.find_all('tr')
    rows = []
    for row in html_rows:
        cells = row.find_all(['th', 'td'])
        title = cells[0].get_text(strip=True)
        value = cells[1].get_text(strip=True)
        rows.append([title, value])

    encoded_answer = encode_result_table(rows, case_number)
    # Indicate a brief answer because brief_answer will be returned:
    # ('b' for brief answer, 'l' for long answer)
    encoded_answer += 'b'
    
    brief_answer = form_brief_answer(rows)
    # long_answer = form_long_answer(rows)

    return brief_answer, encoded_answer

async def define(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args

    # Check usage
    if len(args) != 2:
        await update.message.reply_text("Usage: /define <word> <case_number>")
        return

    word, case_number = args[0], to_english_digits(args[1])

    # Check if the word starts with an alphabetic character
    if not word[0].isalpha():
        await update.message.reply_text("The word should start with an alphabetic character.")
        return

    # Check if case_number contains only digits
    if not case_number.isdigit():
        await update.message.reply_text("The case number should contain only digits.")
        return

    # Check if maximum number of saved cases for the user has reached
    user_id = update.message.from_user.id
    cases = get_user_word_case_pairs(user_id)
    num_cases = len(cases)
    if num_cases >= MAX_CASES:
        await update.message.reply_text(f"Maximum number of cases reached. Consider removing ones you don't need first.")
        return

    if write_to_db(user_id, word, case_number):
        await update.message.reply_text(f"Learned: {word} => {case_number}")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    args = context.args

    # Check usage
    if len(args) != 1:
        await update.message.reply_text("Usage: /remove <word>")
        return

    word_to_remove = args[0]

    # Check if the word starts with an alphabetic character
    if not word_to_remove[0].isalpha():
        await update.message.reply_text("The word should start with an alphabetic character.")
        return

    # Check if the word exists in the database for the user
    current_word = read_from_db(user_id, word_to_remove)

    if current_word:
        if remove_from_db(user_id, word_to_remove):
            await update.message.reply_text(f"'{word_to_remove}' was removed from your dictionary.")
        else:
            await update.message.reply_text(f"Could not remove '{word_to_remove}' from your dictionary.")
    else:
        await update.message.reply_text(f"'{word_to_remove}' was not found in your dictionary.")

def add_header_and_footer(header: str, body: str, footer: str = '') -> str:
    current_time = datetime.now(bru_timezone).strftime("%d/%m/%Y %H:%M:%S")
    time_str = escape_markdownv2_special_chars(f"Retrieved on: {current_time}")
    footer = footer if footer else time_str

    return f"{header}\n{body}\n{footer}"

async def refresh_case(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE) -> (str,str):
    current_answer = query.message.text
    header = escape_markdownv2_special_chars(current_answer.splitlines()[0])
    case_number = re.sub(r'\D', '', header)

    brief_result, encoded_result = analyze_case(case_number)
    answer = add_header_and_footer(header, brief_result)
    
    return (answer, encoded_result)

async def toggle_answer(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE) -> (str,str):
    current_answer = query.message.text
    footer = escape_markdownv2_special_chars(current_answer.splitlines()[-1])
    header = escape_markdownv2_special_chars(current_answer.splitlines()[0])
    case_number = re.sub(r'\D', '', header)

    encoded_data = query.data[1:]
    is_brief = encoded_data[-1] == 'b'
    rows = decode_result_table(encoded_data, case_number)

    if is_brief:
        new_answer = add_header_and_footer(header, form_long_answer(rows), footer)
        encoded_data = encoded_data[:-1] + 'l'
    else:
        new_answer = add_header_and_footer(header, form_brief_answer(rows), footer)
        encoded_data = encoded_data[:-1] + 'b'

    return (new_answer, encoded_data)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    current_message = escape_markdownv2_special_chars(query.message.text)
    pressed_button = query.data[0]
    if pressed_button == '\x00':
        new_answer, encoded_data = await toggle_answer(query, context)
    elif pressed_button == '\x01':
        await query.edit_message_text(text=f'||{current_message}||', parse_mode="MarkdownV2")
        new_answer, encoded_data = await refresh_case(query, context)

    await edit_with_reply_markup(update, new_answer, encoded_data)

def build_reply_markup(encoded_data: str) -> InlineKeyboardMarkup:
    detail_button = InlineKeyboardButton("🔍", callback_data=f"\x00{encoded_data}")
    refresh_button = InlineKeyboardButton("🔄", callback_data=f"\x01")

    markup_first_line = []
    if encoded_data:
        markup_first_line.append(detail_button)
    markup_first_line.append(refresh_button)
    
    keyboard = [markup_first_line]
    return InlineKeyboardMarkup(keyboard)

async def respond_with_reply_markup(update: Update, answer: str, encoded_data: str):
    reply_markup = build_reply_markup(encoded_data)

    await update.message.reply_text(text=answer, reply_markup=reply_markup, parse_mode="MarkdownV2")

async def edit_with_reply_markup(update: Update, new_answer: str, encoded_data: str):
    query = update.callback_query

    reply_markup = build_reply_markup(encoded_data)

    await query.edit_message_text(text=new_answer, reply_markup=reply_markup, parse_mode="MarkdownV2")

async def retrieve_all_states(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    cases = get_user_word_case_pairs(user_id)

    for row in cases:
        word, case_number = row
        if case_number:
            brief_result, encoded_result = analyze_case(case_number)
            answer = add_header_and_footer(f"{word} \({case_number}\)", brief_result)
            await respond_with_reply_markup(update, answer, encoded_result)
            await asyncio.sleep(random.uniform(0.2, 1.2))

async def get_association(update: Update, word: str) -> None:
    user_id = update.message.from_user.id
    case_number = read_from_db(user_id, word)

    if case_number:
        brief_result, encoded_result = analyze_case(case_number)
        answer = add_header_and_footer(f"{word} \({case_number}\)", brief_result)
        await respond_with_reply_markup(update, answer, encoded_result)
    else:
        await update.message.reply_text(f"No association found for '{word}'")

async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg_text = update.message.text.strip()

    if msg_text.isdigit():
        case_number = to_english_digits(msg_text)
        brief_result, encoded_result = analyze_case(case_number)
        answer = add_header_and_footer(str(case_number), brief_result)
        await respond_with_reply_markup(update, answer, encoded_result)
    else:
        await get_association(update=update, word=msg_text)

def main():
    bot_token = get_bot_token()
    if not bot_token:
        logger.error("Bot token not found. Exiting.")
        return

    application = Application.builder().token(bot_token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("define", define))
    application.add_handler(CommandHandler("remove", remove))
    application.add_handler(CommandHandler("all", retrieve_all_states))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_message))
    application.add_handler(CallbackQueryHandler(callback_query_handler))

    application.run_polling()

if __name__ == '__main__':
    main()

