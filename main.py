import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
import yt_dlp

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN") # Переменная окружения
if not BOT_TOKEN:
    exit("Error: BOT_TOKEN not found")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- YT-DLP CONFIG ---
# Базовые настройки с маскировкой под Android
BASE_OPTS = {
    'quiet': True,
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'], # Имитация Android
            'player_skip': ['webpage', 'configs', 'js'],
        }
    },
    'socket_timeout': 10,
    # User-Agent для надежности
    'user_agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
}

async def download_content(url, type_fmt):
    """Скачивание в отдельном потоке"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_sync, url, type_fmt)

def _download_sync(url, type_fmt):
    filename = f"temp_{os.urandom(8).hex()}"
    opts = BASE_OPTS.copy()
    
    # Настройки путей
    out_path = f"{filename}.%(ext)s"
    opts['outtmpl'] = out_path

    if type_fmt == 'mp3':
        opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
        final_ext = '.mp3'
    else:
        # Лимит 1080p чтобы не качать 4к (Telegram не пропустит большие файлы)
        opts.update({
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
        })
        final_ext = '.mp4'

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
            # yt-dlp может добавить расширение само, ищем файл
            expected_file = filename + final_ext
            if os.path.exists(expected_file):
                return expected_file, title
            return None, None
    except Exception as e:
        logging.error(f"Download error: {e}")
        return None, None

# --- HANDLERS ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Кидай ссылку на YouTube.")

@dp.message(F.text.contains("http"))
async def get_link(message: types.Message):
    # Простая клавиатура
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 MP3", callback_data=f"dl_mp3")],
        [InlineKeyboardButton(text="🎬 MP4", callback_data=f"dl_mp4")]
    ])
    # Сохраняем ссылку как ответ на сообщение (Reply), чтобы не хранить стейты (stateless)
    await message.reply("Выбери формат:", reply_markup=kb)

@dp.callback_query(F.data.startswith("dl_"))
async def callback_dl(call: types.CallbackQuery):
    fmt = call.data.split("_")[1]
    # Берем ссылку из сообщения, на которое ответил бот
    if not call.message.reply_to_message or not call.message.reply_to_message.text:
        await call.answer("Ссылка устарела", show_alert=True)
        return

    url = call.message.reply_to_message.text
    await call.message.edit_text("⏳ Скачиваю... (до 1 мин)")

    path, title = await download_content(url, fmt)

    if path:
        try:
            file = FSInputFile(path)
            if fmt == 'mp3':
                await call.message.answer_audio(file, caption=title)
            else:
                await call.message.answer_video(file, caption=title)
            await call.message.delete()
        except Exception as e:
            await call.message.edit_text(f"Ошибка отправки (возможно файл > 50МБ): {e}")
        finally:
            if os.path.exists(path):
                os.remove(path)
    else:
        await call.message.edit_text("Ошибка при скачивании.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
