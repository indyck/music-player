import os
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import json
import logging
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

# Состояния для создания и удаления плейлиста
class PlaylistStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_audio = State()
    waiting_for_confirmation = State()
    waiting_for_delete_confirmation = State()


# Получение плейлистов с сервера с обработкой ошибок
async def fetch_playlists(user_id: int) -> dict:
    """Получает плейлисты пользователя с сервера."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SERVER_URL}/playlists",
                json={"user_id": user_id},
                timeout=TIMEOUT
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Получены плейлисты для user_{user_id}: {data}")
                    return data
                logger.error(f"Ошибка получения плейлистов: {response.status} - {await response.text()}")
                return {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}  # Возвращаем дефолтный плейлист при ошибке
    except Exception as e:
        logger.error(f"Ошибка при запросе плейлистов: {e}")
        return {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}  # Возвращаем дефолтный плейлист при сбое

# Создание плейлиста на сервере
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

# Удаление плейлиста на сервере
async def delete_playlist(user_id: int, playlist_name: str) -> bool:
    """Удаляет плейлист на сервере."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SERVER_URL}/delete_playlist",
                json={"user_id": user_id, "playlist_name": playlist_name},
                timeout=TIMEOUT
            ) as response:
                return response.status == 200
    except Exception as e:
        logger.error(f"Ошибка при удалении плейлиста: {e}")
        return False

# Обновление клавиатуры
def update_keyboard(playlists, current_playlist=None):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    for playlist in playlists:
        button_text = f"Выбрать {playlist['name']}" if playlist['name'] != current_playlist else f"✓ {playlist['name']}"
        keyboard.add(KeyboardButton(button_text))
    keyboard.add(KeyboardButton("Создать плейлист"))
    keyboard.add(KeyboardButton("Удалить плейлист"))
    return keyboard



async def on_startup(_):
    logger.info("Бот запущен")



# Команда /start
@dp.message_handler(commands=['start'])
async def start(message: types.Message, state: FSMContext):
    logger.info(f"Команда /start от user_{message.from_user.id}")
    await state.reset_state()
    user_id = message.from_user.id
    
    playlists_data = await fetch_playlists(user_id)
    if not playlists_data or not playlists_data.get("playlists"):
        playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
    
    await state.update_data(playlists=playlists_data, user_id=user_id, current_playlist=DEFAULT_PLAYLIST)
    playlists = playlists_data.get("playlists", [])
    keyboard = update_keyboard(playlists, DEFAULT_PLAYLIST)
    await message.reply("🎵 Выберите плейлист или отправьте аудиофайл в 'Любимое':", reply_markup=keyboard)

# Обработчик аудиофайлов
@dp.message_handler(content_types=['audio'], state='*')
async def handle_audio(message: types.Message, state: FSMContext):
    logger.info(f"Получен аудиофайл от user_{message.from_user.id}")
    try:
        audio = message.audio
        data = await state.get_data()
        user_id = data.get('user_id')
        if not user_id:
            user_id = message.from_user.id
            await state.update_data(user_id=user_id)
        current_playlist = data.get("current_playlist", DEFAULT_PLAYLIST)

        track_data = {
            "user_id": user_id,
            "file_id": audio.file_id,
            "title": audio.title or "Без названия",
            "artist": audio.performer or "Неизвестный исполнитель",
            "playlist_name": current_playlist
        }
        
        file = await bot.get_file(audio.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as file_response:
                if file_response.status != 200:
                    await message.reply("❌ Не удалось скачать аудиофайл", reply_markup=await get_current_keyboard(message, state))
                    return
                file_bytes = await file_response.read()

            form_data = aiohttp.FormData()
            form_data.add_field("track_data", json.dumps(track_data), content_type="application/json")
            form_data.add_field("file", file_bytes, filename=audio.file_name or "track.mp3", content_type="audio/mpeg")

            async with session.post(
                f"{SERVER_URL}/add_track",
                data=form_data,
                timeout=TIMEOUT
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ошибка добавления трека: {error_text}")
                    await message.reply(f"❌ Ошибка: {error_text}", reply_markup=await get_current_keyboard(message, state))
                    return
                response_json = await response.json()
                if response_json.get("status") != "success":
                    await message.reply("❌ Ошибка при добавлении трека", reply_markup=await get_current_keyboard(message, state))
                    return
                # Обновляем плейлисты после добавления трека
                playlists_data = await fetch_playlists(user_id)
                if not playlists_data or not playlists_data.get("playlists"):
                    playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
                await state.update_data(playlists=playlists_data)
                await message.reply(
                    f"✅ Трек '{track_data['title']}' добавлен в '{current_playlist}'!",
                    reply_markup=update_keyboard(playlists_data.get("playlists", []), current_playlist)
                )
    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {e}")
        playlists_data = await fetch_playlists(user_id)
        if not playlists_data or not playlists_data.get("playlists"):
            playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
        await state.update_data(playlists=playlists_data)
        await message.reply(f"❌ Ошибка: {e}", reply_markup=update_keyboard(playlists_data.get("playlists", []), current_playlist))

# Выбор плейлиста
@dp.message_handler(lambda message: message.text.startswith("Выбрать "))
async def select_playlist(message: types.Message, state: FSMContext):
    logger.info(f"Выбор плейлиста от user_{message.from_user.id}")
    playlist_name = message.text.replace("Выбрать ", "").replace("✓ ", "")
    await state.update_data(current_playlist=playlist_name, user_id=message.from_user.id)
    playlists_data = await fetch_playlists(message.from_user.id)
    if not playlists_data or not playlists_data.get("playlists"):
        playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
    await state.update_data(playlists=playlists_data)
    playlists = playlists_data.get("playlists", [])
    await message.reply(
        f"✅ Выбран плейлист '{playlist_name}'. Теперь отправьте аудиофайл для добавления!",
        reply_markup=update_keyboard(playlists, playlist_name)
    )

# Создание нового плейлиста
@dp.message_handler(lambda message: message.text == "Создать плейлист")
async def create_playlist_prompt(message: types.Message, state: FSMContext):
    logger.info(f"Создание плейлиста от user_{message.from_user.id}")
    await message.reply("Введите название нового плейлиста:", reply_markup=ReplyKeyboardRemove())
    await PlaylistStates.waiting_for_name.set()

# Обработка названия нового плейлиста
@dp.message_handler(state=PlaylistStates.waiting_for_name)
async def handle_playlist_name(message: types.Message, state: FSMContext):
    logger.info(f"Название плейлиста от user_{message.from_user.id}: {message.text}")
    name = message.text.strip()
    if not name:
        await message.reply("Название не может быть пустым. Попробуйте снова:", reply_markup=ReplyKeyboardRemove())
        return

    user_id = message.from_user.id
    success = await create_playlist(user_id, name)
    if success:
        playlists_data = await fetch_playlists(user_id)
        if not playlists_data or not playlists_data.get("playlists"):
            playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
        playlists = playlists_data.get("playlists", [])
        await state.update_data(current_playlist=name, playlists=playlists_data)
        await message.reply(
            f"✅ Плейлист '{name}' создан! Теперь выберите его и отправьте аудиофайл:",
            reply_markup=update_keyboard(playlists, name)
        )
    else:
        await message.reply("❌ Ошибка создания плейлиста", reply_markup=ReplyKeyboardRemove())
    
    await state.finish()

# Удаление плейлиста
@dp.message_handler(lambda message: message.text == "Удалить плейлист")
async def delete_playlist_prompt(message: types.Message, state: FSMContext):
    logger.info(f"Запрос на удаление плейлиста от user_{message.from_user.id}")
    data = await state.get_data()
    current_playlist = data.get("current_playlist", DEFAULT_PLAYLIST)
    user_id = data.get("user_id")
    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True,
        keyboard=[
            [KeyboardButton("Да")],
            [KeyboardButton("Нет")]
        ]
    )
    await message.reply(
        f"⚠️ Вы уверены, что хотите удалить плейлист '{current_playlist}'? Это действие необратимо!",
        reply_markup=keyboard
    )
    await PlaylistStates.waiting_for_delete_confirmation.set()

# Подтверждение удаления плейлиста
@dp.message_handler(lambda message: message.text == "Да", state=PlaylistStates.waiting_for_delete_confirmation)
async def confirm_delete_playlist(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_playlist = data.get("current_playlist", DEFAULT_PLAYLIST)
    user_id = data.get("user_id")

    success = await delete_playlist(user_id, current_playlist)
    if success:
        playlists_data = await fetch_playlists(user_id)
        if not playlists_data or not playlists_data.get("playlists"):
            playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
        playlists = playlists_data.get("playlists", [])
        new_current = playlists[0]["name"] if playlists else DEFAULT_PLAYLIST
        await state.update_data(current_playlist=new_current, playlists=playlists_data)
        await message.reply(
            f"✅ Плейлист '{current_playlist}' удален! Выбран новый плейлист: '{new_current}'. Отправьте аудиофайл!",
            reply_markup=update_keyboard(playlists, new_current)
        )
    else:
        await message.reply("❌ Ошибка при удалении плейлиста", reply_markup=await get_current_keyboard(message, state))
    
    await state.finish()

# Отмена удаления плейлиста
@dp.message_handler(lambda message: message.text == "Нет", state=PlaylistStates.waiting_for_delete_confirmation)
async def cancel_delete_playlist(message: types.Message, state: FSMContext):
    await message.reply("❌ Удаление отменено", reply_markup=await get_current_keyboard(message, state))
    await state.finish()

# Получение текущей клавиатуры
async def get_current_keyboard(message, state):
    data = await state.get_data()
    user_id = data.get('user_id', message.from_user.id)
    playlists_data = await fetch_playlists(user_id)
    if not playlists_data or not playlists_data.get("playlists"):
        playlists_data = {"playlists": [{"name": DEFAULT_PLAYLIST, "tracks": []}]}
    await state.update_data(playlists=playlists_data)
    playlists = playlists_data.get("playlists", [])
    current_playlist = data.get("current_playlist", DEFAULT_PLAYLIST)
    return update_keyboard(playlists, current_playlist)

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)