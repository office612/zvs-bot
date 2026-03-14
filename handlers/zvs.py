import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.filters import CommandStart
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from config import ZVS_SID, GOOGLE_CREDS_JSON, ZVS_GRP

logger = logging.getLogger(__name__)
router = Router()

@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("✅ ЗВС Бот активен!")

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
    await call.answer()
    data = call.data
    logger.info(f"CALLBACK: {data}")

    parts = data.split(":")
    # Новый формат: act:sheetName:grpMid:row  (4+ частей, последние 2 - цифры)
    # Старый формат: act:sheetName:row  (3 части, последняя - цифра)
    act = parts[0]
    try:
        row = int(parts[-1])
        grp_mid_str = parts[-2]
        grp_mid = int(grp_mid_str) if grp_mid_str.isdigit() else 0
        if grp_mid > 0:
            # Новый формат: sheetName между act и grpMid
            sheet_name = ":".join(parts[1:-2])
        else:
            # Старый формат или grpMid=0
            sheet_name = ":".join(parts[1:-1])
            grp_mid = 0
    except Exception as e:
        logger.error(f"Parse error: {e} data={data}")
        return

    logger.info(f"act={act} sheet={sheet_name} grpMid={grp_mid} row={row}")

    if act == "ap":
        status, dec, emoji = "ОДОБРЕНО", "Одобрено", "\u2705"
    elif act == "rj":
        status, dec, emoji = "ОТКЛОНЕНО", "Отклонено", "\u274c"
    else:
        status, dec, emoji = "НА ДОРАБОТКУ", "На доработку", "\U0001f504"

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    director = call.from_user.full_name

    # 1. Убираем кнопки у директора
    try:
        orig = call.message.text or ""
        await call.message.edit_text(
            orig + "\n\n" + emoji + " " + status + "\n" + director + " | " + now,
            reply_markup=None
        )
        logger.info("Director msg edited OK")
    except Exception as e:
        logger.warning(f"edit director: {e}")

    # 2. Редактируем сообщение в ГРУППЕ
    if grp_mid > 0:
        try:
            grp_chat = int(ZVS_GRP)
            # Сначала пробуем получить текст исходного сообщения
            new_grp_text = emoji + " " + status + "\nДиректор: " + director + "\n" + now
            await bot.edit_message_text(
                chat_id=grp_chat,
                message_id=grp_mid,
                text=new_grp_text
            )
            logger.info(f"Group msg {grp_mid} edited OK")
        except Exception as e:
            logger.error(f"edit group: {e}")
            # Если редактировать не получилось — отправляем новое сообщение
            try:
                await bot.send_message(
                    chat_id=int(ZVS_GRP),
                    text=emoji + " " + status + " (ЗВС #" + str(row) + " | " + sheet_name + ")\n" + director + " | " + now
                )
                logger.info("Sent new group message as fallback")
            except Exception as e2:
                logger.error(f"send group fallback: {e2}")
    else:
        logger.warning(f"grpMid=0, sending new message to group")
        try:
            await bot.send_message(
                chat_id=int(ZVS_GRP),
                text=emoji + " " + status + " (ЗВС #" + str(row) + " | " + sheet_name + ")\n" + director + " | " + now
            )
        except Exception as e:
            logger.error(f"send group: {e}")

    # 3. Записываем в таблицу
    if GOOGLE_CREDS_JSON:
        try:
            sh = get_sheet(sheet_name)
            existing = sh.cell(row, 11).value
            if not existing:
                sh.update_cell(row, 11, dec)
                logger.info(f"Sheet OK: {dec} row={row}")
            else:
                logger.info(f"Sheet already: {existing}")
        except Exception as e:
            logger.error(f"sheet: {e}")
