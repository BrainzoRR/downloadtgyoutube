import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
import yt_dlp

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    exit("Error: BOT_TOKEN not found")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- YT-DLP CONFIG ---
BASE_OPTS = {
    'quiet': True,
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'web'], # Маскируемся под iOS
        }
    },
    'socket_timeout': 30,
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
        # ХИТРОСТЬ:
        # Мы просим лучшее видео, но не больше 1080p.
        # Если видео короткое (<5 мин), 1080p может влезть.
        # Если длинное, yt-dlp часто сам выберет битрейт поменьше.
        opts.update({
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
        })
        final_ext = '.mp4'

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Сначала получаем инфу без скачивания
            info_dict = ydl.extract_info(url, download=False)
            duration = info_dict.get('duration', 0)
            
            # Если видео длиннее 15 минут, есть риск не влезть в лимит
            if duration > 900 and type_fmt == 'mp4': 
                # Для длинных видео принудительно ставим качество похуже (480p), чтоб влезло
                opts['format'] = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

            # Теперь скачиваем
            ydl.download([url])
            
            title = info_dict.get('title', 'Video')
            expected_file = filename + final_ext
            
            if os.path.exists(expected_file):
                return expected_file, title, duration
            return None, None, 0
    except Exception as e:
        logging.error(f"Download error: {e}")
        return None, None, 0

# --- HANDLERS ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("👋 Привет! Отправь ссылку на YouTube видео.\n⚠️ Лимит для обычных ботов: 50 МБ (это примерно 5-7 минут в HD).")

@dp.message(F.text.contains("http"))
async def get_link(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎵 MP3 (Аудио)", callback_data=f"dl_mp3")],
        [InlineKeyboardButton(text="🎬 MP4 (Видео)", callback_data=f"dl_mp4")]
    ])
    await message.reply("В каком формате скачать?", reply_markup=kb)

@dp.callback_query(F.data.startswith("dl_"))
async def callback_dl(call: types.CallbackQuery):
    fmt = call.data.split("_")[1]
    if not call.message.reply_to_message or not call.message.reply_to_message.text:
        await call.answer("Ссылка устарела", show_alert=True)
        return

    url = call.message.reply_to_message.text
    await call.message.edit_text(f"⏳ Качаю {'аудио' if fmt == 'mp3' else 'видео'}... Подожди немного.")

    path, title, duration = await download_content(url, fmt)

    if path:
        try:
            file_size = os.path.getsize(path)
            file_size_mb = file_size / (1024 * 1024)

            if file_size_mb > 49.5:
                await call.message.edit_text(
                    f"❌ Файл получился слишком большим: **{file_size_mb:.1f} МБ**.\n"
                    f"Телеграм запрещает ботам отправлять файлы > 50 МБ.\n"
                    f"Попробуй видео покороче."
                )
            else:
                await call.message.edit_text("📤 Отправляю файл...")
                file = FSInputFile(path)
                
                if fmt == 'mp3':
                    await call.message.answer_audio(file, caption=title)
                else:
                    await call.message.answer_video(
                        file, 
                        caption=f"{title}\n📊 Размер: {file_size_mb:.1f} MB",
                        width=1280, height=720, # Подсказка телеграму, что это HD
                        supports_streaming=True
                    )
                await call.message.delete()
                
        except Exception as e:
            await call.message.edit_text(f"Ошибка при отправке: {e}")
        finally:
            if os.path.exists(path):
                os.remove(path)
    else:
        await call.message.edit_text("❌ Ошибка скачивания. Возможно видео недоступно или 18+.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
