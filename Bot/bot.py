import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import json
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Константы
BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_URL = os.getenv("SERVER_URL")
DEFAULT_PLAYLIST = "Любимое"
TIMEOUT = 30

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Состояния для создания плейлиста
class PlaylistStates(StatesGroup):
    waiting_for_name = State()

async def fetch_playlists(user_id: int) -> Optional[Dict[str, Any]]:
    """Получает плейлисты пользователя с сервера."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SERVER_URL}/playlists",
                json={"user_id": user_id},
                timeout=TIMEOUT
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.error(f"Ошибка получения плейлистов: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Ошибка при запросе плейлистов: {e}")
        return None

async def create_playlist(user_id: int, playlist_name: str) -> bool:
    """Создает новый плейлист на сервере."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SERVER_URL}/create_playlist",
                json={
                    "user_id": user_id,
                    "playlist": {"name": playlist_name, "tracks": []}
                },
                timeout=TIMEOUT
            ) as response:
                return response.status == 200
    except Exception as e:
        logger.error(f"Ошибка при создании плейлиста: {e}")
        return False

# Обработчик запуска бота
async def on_startup(_):
    logger.info("Бот запущен")

# Команда /start
@dp.message_handler(commands=['start'])
async def start(message: types.Message, state: FSMContext):
    logger.info(f"Команда /start от user_{message.from_user.id}")
    await state.reset_state()
    user_id = message.from_user.id
    
    playlists_data = await fetch_playlists(user_id)
    if not playlists_data:
        await message.reply("❌ Не удалось загрузить плейлисты")
        return
    
    await state.update_data(playlists=playlists_data)
    playlists = playlists_data.get("playlists", [])
    
    keyboard = InlineKeyboardMarkup(row_width=1)
    for i, playlist in enumerate(playlists):
        keyboard.add(InlineKeyboardButton(f"Выбрать '{playlist['name']}'", callback_data=f"select_{i}"))
    keyboard.add(InlineKeyboardButton("Создать новый плейлист", callback_data="create_playlist"))
    
    sent_message = await message.reply("🎵 Выберите плейлист для добавления треков:", reply_markup=keyboard)
    await state.update_data(message_id=sent_message.message_id)

# Обработчик аудиофайлов
@dp.message_handler(content_types=['audio'])
async def handle_audio(message: types.Message, state: FSMContext):
    logger.info(f"Получен аудиофайл от user_{message.from_user.id}")
    try:
        audio = message.audio
        user_id = message.from_user.id
        
        data = await state.get_data()
        playlist_name = data.get("current_playlist", "Любимое")
        logger.info(f"Добавляю трек в '{playlist_name}' для user_{user_id}")
        
        track_data = {
            "user_id": user_id,
            "file_id": audio.file_id,
            "title": audio.title or "Без названия",
            "artist": audio.performer or "Неизвестный исполнитель",
            "playlist_name": playlist_name
        }
        
        file = await bot.get_file(audio.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as file_response:
                if file_response.status != 200:
                    await message.reply("❌ Не удалось скачать аудиофайл")
                    return
                file_bytes = await file_response.read()

            form_data = aiohttp.FormData()
            form_data.add_field("track_data", json.dumps(track_data), content_type="application/json")
            form_data.add_field("file", file_bytes, filename=audio.file_name or "track.mp3", content_type="audio/mpeg")

            async with session.post(
                f"{SERVER_URL}/add_track",
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    await message.reply(f"❌ Ошибка: {await response.text()}")
                    return
                response_json = await response.json()
                if response_json.get("status") != "success":
                    await message.reply("❌ Ошибка при добавлении трека")
                    return
                await message.reply(f"✅ Трек '{track_data['title']}' добавлен в '{playlist_name}'!")
    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {e}")
        await message.reply(f"❌ Ошибка: {e}")

# Выбор плейлиста
@dp.callback_query_handler(lambda c: c.data.startswith("select_"))
async def playlist_selected(callback_query: types.CallbackQuery, state: FSMContext):
    logger.info(f"Callback: {callback_query.data} от user_{callback_query.from_user.id}")
    await bot.answer_callback_query(callback_query.id)

    playlist_index = int(callback_query.data.split("_")[1])
    data = await state.get_data()
    playlists = data.get("playlists", {}).get("playlists", [])

    if playlist_index < len(playlists):
        selected_playlist = playlists[playlist_index]["name"]
        await state.update_data(current_playlist=selected_playlist)
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(InlineKeyboardButton("Открыть плейлист", web_app={"url": SERVER_URL}))
        keyboard.add(InlineKeyboardButton("Выбрать другой плейлист", callback_data="back_to_select"))
        await bot.edit_message_text(
            f"✅ Выбран плейлист '{selected_playlist}'. Отправьте аудиофайл, чтобы добавить его!",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard
        )
    else:
        await bot.edit_message_text(
            "❌ Плейлист не найден",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )

# Создание нового плейлиста
@dp.callback_query_handler(lambda c: c.data == "create_playlist")
async def create_playlist(callback_query: types.CallbackQuery):
    logger.info(f"Создание плейлиста от user_{callback_query.from_user.id}")
    await bot.answer_callback_query(callback_query.id)
    await bot.edit_message_text(
        "Введите название нового плейлиста:",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id
    )
    await PlaylistStates.waiting_for_name.set()

# Возврат к выбору плейлистов
@dp.callback_query_handler(lambda c: c.data == "back_to_select")
async def back_to_select(callback_query: types.CallbackQuery, state: FSMContext):
    logger.info(f"Возврат к выбору плейлистов от user_{callback_query.from_user.id}")
    await bot.answer_callback_query(callback_query.id)
    await show_playlists(callback_query, state)

# Обработка названия нового плейлиста
@dp.message_handler(state=PlaylistStates.waiting_for_name)
async def handle_playlist_name(message: types.Message, state: FSMContext):
    logger.info(f"Название плейлиста от user_{message.from_user.id}: {message.text}")
    name = message.text.strip()
    if not name:
        await message.reply("Название не может быть пустым. Попробуйте снова:")
        return

    user_id = message.from_user.id
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{SERVER_URL}/create_playlist",
            json={"user_id": user_id, "playlist": {"name": name, "tracks": []}},
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status != 200:
                await message.reply(f"❌ Ошибка создания: {await response.text()}")
                return
            
            data = await state.get_data()
            playlists_data = data.get("playlists", {"playlists": []})
            playlists_data["playlists"].append({"name": name, "tracks": []})
            await state.update_data(playlists=playlists_data)

            playlists = playlists_data.get("playlists", [])
            keyboard = InlineKeyboardMarkup(row_width=1)
            for i, playlist in enumerate(playlists):
                keyboard.add(InlineKeyboardButton(f"Выбрать '{playlist['name']}'", callback_data=f"select_{i}"))
            keyboard.add(InlineKeyboardButton("Создать новый плейлист", callback_data="create_playlist"))
            
            await bot.delete_message(chat_id=message.chat.id, message_id=data["message_id"])
            sent_message = await message.reply(f"✅ Плейлист '{name}' создан! Выберите плейлист:", reply_markup=keyboard)
            await state.update_data(message_id=sent_message.message_id)
    
    await state.finish()

# Показ списка плейлистов
async def show_playlists(obj, state: FSMContext):
    if isinstance(obj, types.CallbackQuery):
        user_id = obj.from_user.id
        message_id = obj.message.message_id
        chat_id = obj.message.chat.id
    else:
        return

    data = await state.get_data()
    playlists_data = data.get("playlists")
    if not playlists_data:
        playlists_data = await fetch_playlists(user_id)
        if not playlists_data:
            await bot.edit_message_text("❌ Не удалось загрузить плейлисты", chat_id=chat_id, message_id=message_id)
            return
        await state.update_data(playlists=playlists_data)

    playlists = playlists_data.get("playlists", [])
    keyboard = InlineKeyboardMarkup(row_width=1)
    for i, playlist in enumerate(playlists):
        keyboard.add(InlineKeyboardButton(f"Выбрать '{playlist['name']}'", callback_data=f"select_{i}"))
    keyboard.add(InlineKeyboardButton("Создать новый плейлист", callback_data="create_playlist"))
    
    await bot.edit_message_text(
        "🎵 Выберите плейлист для добавления треков:",
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=keyboard
    )

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)