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

sent_rows = set()
cb_store = {}
cb_counter = 0

# Столбцы таблицы (0-indexed):
# A(0)=#  B(1)=№  C(2)=Дата  D(3)=Отделение  E(4)=Сотрудник
# F(5)=Ситуация  G(6)=на что  H(7)=Ссылки  I(8)=Фото  J(9)=Решение
# K(10)=Сумма  L(11)=Одобрено ЗАВ
COL_NUM = 1
COL_DATE = 2
COL_DEPT = 3
COL_EMPLOYEE = 4
COL_SITUATION = 5
COL_PURPOSE = 6
COL_LINK = 7
COL_SUMMA = 10
COL_APPROVED = 11
COL_APPROVED_1BASED = 12


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
    return client.open_by_key(ZVS_SID).worksheets()


def safe_get(row, idx):
    return row[idx].strip() if len(row) > idx else ""


@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("ZVS Bot v3 active")


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

            num = safe_get(row, COL_NUM)
            date = safe_get(row, COL_DATE)
            has_data = num or date

            approved = safe_get(row, COL_APPROVED)
            summa = safe_get(row, COL_SUMMA)

            if not has_data or approved:
                if approved:
                    sent_rows.add((sheet_name, row_num))
                continue

            if not summa:
                continue

            dept = safe_get(row, COL_DEPT)
            employee = safe_get(row, COL_EMPLOYEE)
            situation = safe_get(row, COL_SITUATION)
            purpose = safe_get(row, COL_PURPOSE)
            link = safe_get(row, COL_LINK)

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

            grp_mid = 0
            try:
                grp_msg = await bot.send_message(
                    chat_id=int(ZVS_GRP),
                    text=text + "\n\nOzhidaet",
                    disable_web_page_preview=True,
                )
                grp_mid = grp_msg.message_id
                logger.info(f"GRP ok: {sheet_name} r={row_num}")
            except Exception as e:
                logger.error(f"send grp: {e}")

            global cb_counter
            cid = cb_counter
            cb_counter += 1
            cb_store[cid] = {
                "sheet": sheet_name,
                "row": row_num,
                "grp_mid": grp_mid,
            }

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
                logger.info(f"DIR ok: {sheet_name} r={row_num} cid={cid}")
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
            (call.message.text or "") + "\n\nBot restarted, wait for new msg",
            reply_markup=None,
        )
        return

    sheet_name = info["sheet"]
    row = info["row"]
    grp_mid = info["grp_mid"]

    if act == "ap":
        status, dec = "ODOBRENO", "Одобрено"
    elif act == "rj":
        status, dec = "OTKLONENO", "Отклонено"
    else:
        status, dec = "NA DORABOTKU", "На доработку"

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    director = call.from_user.full_name
    orig_text = call.message.text or ""

    try:
        await call.message.edit_text(
            orig_text + f"\n\n{status}\n{director} | {now}",
            reply_markup=None,
            disable_web_page_preview=True,
        )
        logger.info("Dir edited")
    except Exception as e:
        logger.warning(f"edit dir: {e}")

    grp_text = orig_text + f"\n\n{status}\nDirector: {director}\n{now}"
    if grp_mid > 0:
        try:
            await bot.edit_message_text(
                chat_id=int(ZVS_GRP),
                message_id=grp_mid,
                text=grp_text,
                disable_web_page_preview=True,
            )
            logger.info(f"Grp edited")
        except Exception as e:
            logger.error(f"edit grp: {e}")
            try:
                await bot.send_message(chat_id=int(ZVS_GRP), text=grp_text, disable_web_page_preview=True)
            except Exception as e2:
                logger.error(f"grp fb: {e2}")
    else:
        try:
            await bot.send_message(chat_id=int(ZVS_GRP), text=grp_text, disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"send grp: {e}")

    if GOOGLE_CREDS_JSON:
        try:
            sh = get_sheet(sheet_name)
            existing = sh.cell(row, COL_APPROVED_1BASED).value
            if not existing:
                sh.update_cell(row, COL_APPROVED_1BASED, dec)
                logger.info(f"Sheet ok: {dec} r={row}")
            else:
                logger.info(f"Sheet exists: {existing}")
        except Exception as e:
            logger.error(f"sheet: {e}")
