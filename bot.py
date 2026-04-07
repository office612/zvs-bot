import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import ZVS_TOKEN
from handlers import zvs

logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60  # секунд между проверками таблицы


async def sheet_checker(bot: Bot):
        """Background task: проверяет таблицу на новые заявки каждые CHECK_INTERVAL секунд."""
        await asyncio.sleep(5)  # подождать пока бот стартует
    logger.info("Sheet checker started")
    while True:
                try:
                                await zvs.check_new_rows(bot)
except Exception as e:
            logger.error(f"sheet_checker error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def main():
        bot = Bot(
                    token=ZVS_TOKEN,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(zvs.router)
        logger.info("ZVS Bot started")

    # Запускаем фоновую проверку таблицы
        checker_task = asyncio.create_task(sheet_checker(bot))

    try:
                await bot.delete_webhook(drop_pending_updates=True)
                await dp.start_polling(bot, allowed_updates=["callback_query", "message"])
finally:
            checker_task.cancel()
            await bot.session.close()

if __name__ == "__main__":
        asyncio.run(main())
