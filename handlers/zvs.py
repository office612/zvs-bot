import logging
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from config import ZVS_SID, GOOGLE_CREDS_JSON, ZVS_GRP, ZVS_DIR

logger = logging.getLogger(__name__)
router = Router()

# In-memory: уже отправленные заявки
sent_rows = set()

# Маппинг короткий id -> {sheet_name, row, grp_mid} для callback_data
cb_store = {}
cb_counter = 0


def get_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)


def get_sheet(sheet_name):
    client = get_client()
    return client.open_by_key(ZVS_SID).worksheet(sheet_name)


def get_all_sheets():
    client = get_client()
    spreadsheet = client.open_by_key(ZVS_SID)
    return spreadsheet.worksheets()


@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("ZVS Bot v2 active")


async def check_new_rows(bot: Bot):
    if not GOOGLE_CREDS_JSON:
        return

    try:
        worksheets = get_all_sheets()
    except Exception as e:
        logger.error(f"get_all_sheets: {e}")
        return

    for ws in worksheets:
        sheet_name = ws.title
        try:
            all_values = ws.get_all_values()
        except Exception as e:
            logger.error(f"read sheet '{sheet_name}': {e}")
            continue

        if len(all_values) < 2:
            continue

        for i, row in enumerate(all_values):
            if i == 0:
                continue

            row_num = i + 1

            if (sheet_name, row_num) in sent_rows:
                continue

            has_data = len(row) > 1 and (row[0].strip() or row[1].strip())
            col_k = row[10].strip() if len(row) > 10 else ""

            if not has_data or col_k:
                if col_k:
                    sent_rows.add((sheet_name, row_num))
                continue

            summa = row[9].strip() if len(row) > 9 else ""
            if not summa:
                continue

            num = row[0].strip() if len(row) > 0 else ""
            date = row[1].strip() if len(row) > 1 else ""
            dept = row[2].strip() if len(row) > 2 else ""
            employee = row[3].strip() if len(row) > 3 else ""
            situation = row[4].strip() if len(row) > 4 else ""
            purpose = row[5].strip() if len(row) > 5 else ""
            link = row[6].strip() if len(row) > 6 else ""

            text = (
                f"<b>ZVS #{num}</b>\n"
                f"Data: {date}\n"
                f"Otdel: {dept}\n"
                f"Sotrudnik: {employee}\n"
                f"Situaciya: {situation}\n"
                f"Na chto: {purpose}\n"
                f"Summa: {summa}\n"
                f"List: {sheet_name}"
            )
            if link:
                text += f'\n<a href="{link}">Doc</a>'

            # Отправляем в группу
            grp_mid = 0
            try:
                grp_msg = await bot.send_message(
                    chat_id=int(ZVS_GRP),
                    text=text + "\n\nOzhidaet",
                    disable_web_page_preview=True,
                )
                grp_mid = grp_msg.message_id
                logger.info(f"GRP sent: {sheet_name} r={row_num} mid={grp_mid}")
            except Exception as e:
                logger.error(f"send grp: {e}")

            # Сохраняем данные под коротким ID
            global cb_counter
            cid = cb_counter
            cb_counter += 1
            cb_store[cid] = {
                "sheet": sheet_name,
                "row": row_num,
                "grp_mid": grp_mid,
            }

            # Callback: act:cid (максимум ~10 символов)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="OK", callback_data=f"ap:{cid}"),
                    InlineKeyboardButton(text="NO", callback_data=f"rj:{cid}"),
                ],
                [
                    InlineKeyboardButton(text="REDO", callback_data=f"rw:{cid}"),
                ],
            ])

            try:
                await bot.send_message(
                    chat_id=int(ZVS_DIR),
                    text=text,
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                logger.info(f"DIR sent: {sheet_name} r={row_num} cid={cid}")
            except Exception as e:
                logger.error(f"send dir: {e}")

            sent_rows.add((sheet_name, row_num))


@router.callback_query(
    F.data.startswith("ap:") | F.data.startswith("rj:") | F.data.startswith("rw:")
)
async def zvs_button_handler(call: CallbackQuery, bot: Bot):
    await call.answer()
    data = call.data
    logger.info(f"CB: {data}")

    parts = data.split(":")
    act = parts[0]

    try:
        cid = int(parts[1])
    except Exception as e:
        logger.error(f"Parse cid: {e} data={data}")
        return

    info = cb_store.get(cid)
    if not info:
        logger.error(f"Unknown cid: {cid}")
        await call.message.edit_text(
            (call.message.text or "") + "\n\nBot was restarted, please wait for new message",
            reply_markup=None,
        )
        return

    sheet_name = info["sheet"]
    row = info["row"]
    grp_mid = info["grp_mid"]

    logger.info(f"act={act} sheet={sheet_name} row={row} grp_mid={grp_mid}")

    if act == "ap":
        status, dec, emoji = "ODOBRENO", "Одобрено", "V"
    elif act == "rj":
        status, dec, emoji = "OTKLONENO", "Отклонено", "X"
    else:
        status, dec, emoji = "NA DORABOTKU", "На доработку", "R"

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    director = call.from_user.full_name
    orig_text = call.message.text or ""

    # 1. Убираем кнопки у директора
    try:
        await call.message.edit_text(
            orig_text + f"\n\n{emoji} {status}\n{director} | {now}",
            reply_markup=None,
            disable_web_page_preview=True,
        )
        logger.info("Dir edited OK")
    except Exception as e:
        logger.warning(f"edit dir: {e}")

    # 2. Обновляем в группе
    grp_text = orig_text + f"\n\n{emoji} {status}\nDirector: {director}\n{now}"

    if grp_mid > 0:
        try:
            await bot.edit_message_text(
                chat_id=int(ZVS_GRP),
                message_id=grp_mid,
                text=grp_text,
                disable_web_page_preview=True,
            )
            logger.info(f"Grp {grp_mid} edited OK")
        except Exception as e:
            logger.error(f"edit grp: {e}")
            try:
                await bot.send_message(chat_id=int(ZVS_GRP), text=grp_text, disable_web_page_preview=True)
            except Exception as e2:
                logger.error(f"send grp fb: {e2}")
    else:
        try:
            await bot.send_message(chat_id=int(ZVS_GRP), text=grp_text, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"send grp: {e}")

    # 3. Записываем в таблицу K
    if GOOGLE_CREDS_JSON:
        try:
            sh = get_sheet(sheet_name)
            existing = sh.cell(row, 11).value
            if not existing:
                sh.update_cell(row, 11, dec)
                logger.info(f"Sheet OK: {dec} r={row}")
            else:
                logger.info(f"Sheet exists: {existing}")
        except Exception as e:
            logger.error(f"sheet: {e}")
