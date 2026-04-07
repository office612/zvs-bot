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

# In-memory set: (sheet_name, row_num) уже отправленных заявок
sent_rows = set()


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
    await message.answer("✅ ЗВС Бот активен!\n\nЯ автоматически проверяю таблицу и отправляю новые заявки на согласование.")


async def check_new_rows(bot: Bot):
    """Проверяет все вкладки таблицы на новые строки без решения (столбец K пустой)."""
    if not GOOGLE_CREDS_JSON:
        return

    try:
        worksheets = get_all_sheets()
    except Exception as e:
        logger.error(f"get_all_sheets error: {e}")
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

        # Столбцы (0-indexed): A=0(#), B=1(Дата), C=2(Отделение), D=3(Сотрудник),
        # E=4(Ситуация), F=5(на что), G=6(Ссылки), H=7(Фото), I=8(Решение),
        # J=9(Сумма), K=10(Одобрено ЗАВ)
        for i, row in enumerate(all_values):
            if i == 0:
                continue  # заголовок

            row_num = i + 1  # 1-based row number

            # Пропускаем если уже отправляли
            if (sheet_name, row_num) in sent_rows:
                continue

            # Проверяем: есть данные (номер или дата) и столбец K пустой
            has_data = len(row) > 1 and (row[0].strip() or row[1].strip())
            col_k = row[10].strip() if len(row) > 10 else ""

            if not has_data or col_k:
                # Если K уже заполнен — добавляем в sent чтобы не проверять повторно
                if col_k:
                    sent_rows.add((sheet_name, row_num))
                continue

            # Есть сумма? Без суммы не отправляем
            summa = row[9].strip() if len(row) > 9 else ""
            if not summa:
                continue

            # Формируем сообщение
            num = row[0].strip() if len(row) > 0 else ""
            date = row[1].strip() if len(row) > 1 else ""
            dept = row[2].strip() if len(row) > 2 else ""
            employee = row[3].strip() if len(row) > 3 else ""
            situation = row[4].strip() if len(row) > 4 else ""
            purpose = row[5].strip() if len(row) > 5 else ""
            link = row[6].strip() if len(row) > 6 else ""

            text = (
                f"📋 <b>ЗВС #{num}</b>\n"
                f"📅 Дата: {date}\n"
                f"🏢 Отделение: {dept}\n"
                f"👤 Сотрудник: {employee}\n"
                f"📝 Ситуация: {situation}\n"
                f"🎯 На что: {purpose}\n"
                f"💰 Сумма: {summa}\n"
                f"📎 Лист: {sheet_name}"
            )
            if link:
                text += f"\n🔗 <a href=\"{link}\">Документ</a>"

            # Сначала отправляем в группу (получаем message_id)
            grp_mid = 0
            try:
                grp_msg = await bot.send_message(
                    chat_id=int(ZVS_GRP),
                    text=text + "\n\n⏳ Ожидает согласования",
                    disable_web_page_preview=True,
                )
                grp_mid = grp_msg.message_id
                logger.info(f"Group msg sent: sheet={sheet_name} row={row_num} mid={grp_mid}")
            except Exception as e:
                logger.error(f"send group: {e}")

            # Кнопки для директора
            # Формат callback: act:sheet_name:grp_mid:row
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Одобрить", callback_data=f"ap:{sheet_name}:{grp_mid}:{row_num}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rj:{sheet_name}:{grp_mid}:{row_num}"),
                ],
                [
                    InlineKeyboardButton(text="🔄 На доработку", callback_data=f"rw:{sheet_name}:{grp_mid}:{row_num}"),
                ],
            ])

            try:
                await bot.send_message(
                    chat_id=int(ZVS_DIR),
                    text=text,
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                logger.info(f"Director msg sent: sheet={sheet_name} row={row_num}")
            except Exception as e:
                logger.error(f"send director: {e}")

            sent_rows.add((sheet_name, row_num))


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
        grp_mid = int(parts[-2])
        sheet_name = ":".join(parts[1:-2])
    except Exception as e:
        logger.error(f"Parse error: {e} data={data}")
        return

    logger.info(f"act={act} sheet={sheet_name} grpMid={grp_mid} row={row}")

    if act == "ap":
        status, dec, emoji = "ОДОБРЕНО", "Одобрено", "✅"
    elif act == "rj":
        status, dec, emoji = "ОТКЛОНЕНО", "Отклонено", "❌"
    else:
        status, dec, emoji = "НА ДОРАБОТКУ", "На доработку", "🔄"

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    director = call.from_user.full_name

    # Исходный текст заявки
    orig_text = call.message.text or ""

    # 1. Убираем кнопки у директора — добавляем статус
    try:
        await call.message.edit_text(
            orig_text + f"\n\n{emoji} {status}\n{director} | {now}",
            reply_markup=None,
            disable_web_page_preview=True,
        )
        logger.info("Director msg edited OK")
    except Exception as e:
        logger.warning(f"edit director: {e}")

    # 2. Обновляем сообщение в группе
    grp_new_text = orig_text + f"\n\n{emoji} {status}\nДиректор: {director}\n{now}"

    if grp_mid > 0:
        try:
            await bot.edit_message_text(
                chat_id=int(ZVS_GRP),
                message_id=grp_mid,
                text=grp_new_text,
                disable_web_page_preview=True,
            )
            logger.info(f"Group msg {grp_mid} edited OK")
        except Exception as e:
            logger.error(f"edit group: {e}")
            try:
                await bot.send_message(chat_id=int(ZVS_GRP), text=grp_new_text, disable_web_page_preview=True)
            except Exception as e2:
                logger.error(f"send group fallback: {e2}")
    else:
        try:
            await bot.send_message(chat_id=int(ZVS_GRP), text=grp_new_text, disable_web_page_preview=True)
            logger.info("Sent new group message (no grpMid)")
        except Exception as e:
            logger.error(f"send group: {e}")

    # 3. Записываем в таблицу столбец K
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
