import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from config import ZVS_SID, GOOGLE_CREDS_JSON

logger = logging.getLogger(__name__)
router = Router()


def get_sheet(sheet_name: str):
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(ZVS_SID).worksheet(sheet_name)


@router.callback_query(
    F.data.startswith("ap:") | F.data.startswith("rj:") | F.data.startswith("rw:")
)
async def zvs_button_handler(call: CallbackQuery, bot: Bot):
    # Instantly removes the spinner - CRITICAL
    await call.answer()

    data = call.data
    last_colon = data.rfind(":")
    row = int(data[last_colon + 1:])
    act_sn = data[:last_colon]
    first_colon = act_sn.index(":")
    act = act_sn[:first_colon]
    sheet_name = act_sn[first_colon + 1:]

    if act == "ap":
        status, dec = "ОДОБРЕНО", "Одобрено"
    elif act == "rj":
        status, dec = "ОТКЛОНЕНО", "Отклонено"
    else:
        status, dec = "НА ДОРАБОТКУ", "На доработку"

    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Remove buttons from message
    try:
        await call.message.edit_text(f"{status}\n{now}")
    except Exception as e:
        logger.warning(f"edit_text: {e}")

    # Write decision to Google Sheets col 11
    try:
        sh = get_sheet(sheet_name)
        existing = sh.cell(row, 11).value
        if not existing:
            sh.update_cell(row, 11, dec)
            logger.info(f"ZVS OK: {dec} -> {sheet_name} row={row}")
        else:
            logger.info(f"ZVS already done: {existing}")
    except Exception as e:
        logger.error(f"ZVS sheet error: {e}")
