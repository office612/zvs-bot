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
    act = parts[0]
    try:
        row = int(parts[-1])
        grp_mid_str = parts[-2]
        grp_mid = int(grp_mid_str) if grp_mid_str.isdigit() else 0
        if grp_mid > 0:
            sheet_name = ":".join(parts[1:-2])
        else:
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

    # Исходный текст заявки из сообщения директора
    orig_text = call.message.text or ""

    # 1. Убираем кнопки у директора — добавляем статус к исходному тексту
    try:
        await call.message.edit_text(
            orig_text + "\n\n" + emoji + " " + status + "\n" + director + " | " + now,
            reply_markup=None
        )
        logger.info("Director msg edited OK")
    except Exception as e:
        logger.warning(f"edit director: {e}")

    # 2. Обновляем сообщение в ГРУППЕ — показываем исходный текст + статус
    grp_new_text = orig_text + "\n\n" + emoji + " " + status + "\nДиректор: " + director + "\n" + now

    if grp_mid > 0:
        try:
            await bot.edit_message_text(
                chat_id=int(ZVS_GRP),
                message_id=grp_mid,
                text=grp_new_text
            )
            logger.info(f"Group msg {grp_mid} edited OK")
        except Exception as e:
            logger.error(f"edit group: {e}")
            # Запасной вариант — новое сообщение
            try:
                await bot.send_message(chat_id=int(ZVS_GRP), text=grp_new_text)
            except Exception as e2:
                logger.error(f"send group fallback: {e2}")
    else:
        # Старый формат без grpMid — отправляем новое сообщение в группу
        try:
            await bot.send_message(chat_id=int(ZVS_GRP), text=grp_new_text)
            logger.info("Sent new group message (no grpMid)")
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
