from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import requests
from bs4 import BeautifulSoup
import os

# Get the absolute path of the directory containing the script
script_directory = os.path.dirname(os.path.abspath(__file__))
token_path = os.path.join(script_directory, "bot-token.txt")

try:
    with open(token_path, 'r') as file:
        BOT_TOKEN = file.readline().strip()
except FileNotFoundError:
    print(f"The file '{token_path}' does not exist.")
except Exception as e:
    print("An error occurred:", str(e))


def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("Welcome to the Case Analysis Bot! Please send me a case number.")

def analyze_case(update: Update, context: CallbackContext) -> None:
    case_number = update.message.text

    # Check if the entered message is a valid number
    if not case_number.isdigit():
        update.message.reply_text("Please enter a valid case number (a numeric value).")
        return

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

    update.message.reply_text(analysis_result, parse_mode="Markdown")

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, analyze_case))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
