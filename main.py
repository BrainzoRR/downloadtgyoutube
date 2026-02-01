import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.memory import MemoryStorage
import yt_dlp

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_API_URL = os.getenv("BOT_API_URL") # Например: http://telegram-bot-api:8081

if not BOT_TOKEN or not BOT_API_URL:
    exit("Error: ENV variables missing")

logging.basicConfig(level=logging.INFO)

# --- НАСТРОЙКА ЛОКАЛЬНОГО СЕРВЕРА ---
session = AiohttpSession(api=TelegramAPIServer.from_base(BOT_API_URL))
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher(storage=MemoryStorage())

# --- YT-DLP CONFIG ---
BASE_OPTS = {
    'quiet': True,
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'web'],
        }
    },
    'socket_timeout': 60,
}

async def download_content(url, type_fmt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_sync, url, type_fmt)

def _download_sync(url, type_fmt):
    filename = f"temp_{os.urandom(8).hex()}"
    opts = BASE_OPTS.copy()
    
    opts['outtmpl'] = f"{filename}.%(ext)s"

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
        # ТЕПЕРЬ МЫ МОЖЕМ КАЧАТЬ ВСЁ ЧТО УГОДНО (до 2 ГБ)
        opts.update({
            # Качаем лучшее видео и аудио, но склеиваем в MP4
            'format': 'bestvideo+bestaudio/best', 
            'merge_output_format': 'mp4',
        })
        final_ext = '.mp4'

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video')
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
    await message.answer("🚀 Я работаю через локальный сервер!\nЛимит файлов: **2000 МБ**.\nКидай ссылку.")

@dp.message(F.text.contains("http"))
async def get_link(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 MP3", callback_data=f"dl_mp3")],
        [InlineKeyboardButton(text="🎬 Макс. качество", callback_data=f"dl_mp4")]
    ])
    await message.reply("Выбери формат:", reply_markup=kb)

@dp.callback_query(F.data.startswith("dl_"))
async def callback_dl(call: types.CallbackQuery):
    fmt = call.data.split("_")[1]
    if not call.message.reply_to_message or not call.message.reply_to_message.text:
        await call.answer("Ссылка устарела", show_alert=True)
        return

    url = call.message.reply_to_message.text
    await call.message.edit_text(f"⏳ Качаю... (Файлы до 2ГБ могут обрабатываться долго)")

    path, title = await download_content(url, fmt)

    if path:
        try:
            await call.message.edit_text("📤 Отправляю файл...")
            
            # FSInputFile автоматически корректно работает с aiogram 3
            file = FSInputFile(path)
            
            if fmt == 'mp3':
                await call.message.answer_audio(file, caption=title)
            else:
                await call.message.answer_video(file, caption=title, supports_streaming=True)
                
            await call.message.delete()
        except Exception as e:
            await call.message.edit_text(f"Ошибка при отправке: {e}")
        finally:
            if os.path.exists(path):
                os.remove(path)
    else:
        await call.message.edit_text("❌ Ошибка скачивания.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
