from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import requests
from bs4 import BeautifulSoup
import os
import sqlite3

# Get the absolute path of the directory containing the script
script_directory = os.path.dirname(os.path.abspath(__file__))
token_path = os.path.join(script_directory, "bot-token.txt")
db_path = os.path.join(script_directory, "data.db")

try:
    with open(token_path, 'r') as file:
        BOT_TOKEN = file.readline().strip()
except FileNotFoundError:
    print(f"The file '{token_path}' does not exist.")
except Exception as e:
    print("An error occurred:", str(e))


def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Welcome to the Case Analysis Bot! Please send me a case number.")

def analyze_case(case_number: int) -> str:
    url = f"https://infovisa.ibz.be/ResultNl.aspx?place=THR&visumnr={case_number}"
    
    response = requests.get(url)
    if response.status_code != 200:
        analysis_result = "Error retrieving state from DVZ."

    soup = BeautifulSoup(response.content, 'html.parser')

    # Check if the "dossiernr" element exists
    dossiernr_element = soup.find(id="dossiernr")

    if dossiernr_element:
        analysis_result = f"{case_number}: Your search returned no result in DVZ database."
    else:
        # Extract table data if it exists
        table = soup.find('table')
        if table:
            table_text = "\n"
            for row in table.find_all('tr'):
                cells = row.find_all(['th', 'td'])
                row_text = f'*{cells[0].get_text(strip=True)}*'
                row_text += (f'\n_{cells[1].get_text(strip=True)}_' if cells[1].get_text(strip=True) else "")
                table_text += row_text + '\n'
            analysis_result = f'{table_text}'
        else:
            # No table found on the page!
            analysis_result = f"{case_number}: Error."

    return analysis_result


def define(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    args = context.args

    if len(args) != 2:
        update.message.reply_text("Usage: /define <word> <case_number>")
        return

    word, case_number = args[0], args[1]

    # Insert the association into the database (replace if it already exists)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO user_commands (user_id, word, case_number) VALUES (?, ?, ?)", (user_id, word, case_number))
    conn.commit()
    conn.close()

    update.message.reply_text(f"Defined: {word} => {case_number}")


def get_association(update: Update, word: str) -> None:
    user_id = update.message.from_user.id

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT case_number FROM user_commands WHERE user_id = ? AND word = ?", (user_id, word))
    result = cursor.fetchone()
    conn.close()

    if result:
        case_number = result[0]
        update.message.reply_text(f"The case number for '{word}' is: {case_number}")
    else:
        update.message.reply_text(f"No association found for '{word}'")

def check_message(update: Update, context: CallbackContext) -> None:
    msg_text = update.message.text.strip()

    # Check if the entered message is a valid number
    if msg_text.isdigit():
        analysis_result = analyze_case(msg_text)
        update.message.reply_text(analysis_result, parse_mode="Markdown")
    else:
        get_association(update=update, word=msg_text)

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("define", define, pass_args=True))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, check_message))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
