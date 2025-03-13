import os
import json
import logging
import requests
import urllib.parse
import shutil
from flask import Flask, render_template, send_from_directory, request, jsonify
from concurrent.futures import ThreadPoolExecutor
import traceback
import signal
import sys

def signal_handler(sig, frame):
    print("Завершение бота...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Константы
PATH = "static/DB"
DEFAULT_PLAYLIST = "Любимое"
DEFAULT_COVER = "static/css/standart.png"
TIMEOUT = 10
MAX_WORKERS = 5

# Инициализация Flask
app = Flask(__name__, static_folder='static', template_folder='templates')
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def download_cover(artist: str, track_title: str, save_path: str) -> None:
    """Скачивает обложку трека с iTunes API или использует стандартную при ошибке."""
    try:
        query = urllib.parse.quote(f"{artist} {track_title}")
        search_url = f"https://itunes.apple.com/search?term={query}&entity=song"
        logger.info(f"Запрос к iTunes API: {search_url}")
        
        with requests.get(search_url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            results = response.json().get("results", [])
            
            if not results:
                shutil.copy(DEFAULT_COVER, save_path)
                logger.info(f"Обложка не найдена для '{track_title}' от '{artist}', используется стандартная")
                return
            
            cover_url = results[0].get("artworkUrl100").replace("100x100", "600x600")
            logger.info(f"URL обложки: {cover_url}")
            
            with requests.get(cover_url, timeout=TIMEOUT) as cover_response:
                cover_response.raise_for_status()
                with open(save_path, "wb") as f:
                    f.write(cover_response.content)
                logger.info(f"Обложка сохранена: {save_path}")
    except (requests.RequestException, Exception) as e:
        shutil.copy(DEFAULT_COVER, save_path)
        logger.error(f"Ошибка скачивания обложки для '{track_title}' от '{artist}': {e}")

def extract_user_id(data: str) -> int:
    """Извлекает user_id из переданных данных Telegram."""
    try:
        data_dict = dict(item.split('=') for item in data.split('&'))
        user_data_encoded = data_dict.get('user', '')
        user_data_decoded = urllib.parse.unquote(user_data_encoded)
        user_data = json.loads(user_data_decoded)
        return user_data.get('id')
    except Exception as e:
        logger.error(f"Ошибка извлечения user_id: {e}")
        raise

def load_playlists(user_dir: str, playlists_file: str) -> list:
    """Загружает или инициализирует файл плейлистов."""
    if not os.path.exists(playlists_file):
        default_playlists = [{"name": DEFAULT_PLAYLIST, "tracks": []}]
        with open(playlists_file, "w", encoding="utf-8") as f:
            json.dump(default_playlists, f)
        logger.info(f"Создан начальный файл плейлистов в {user_dir}")
        return default_playlists
    
    try:
        with open(playlists_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Ошибка чтения файла плейлистов: {playlists_file}")
        return [{"name": DEFAULT_PLAYLIST, "tracks": []}]

@app.route('/auth', methods=['POST'])
def auth():
    """Аутентификация пользователя через Telegram Web App."""
    try:
        logger.info(f"Получен запрос к /auth: {request.json}")
        tg_data = request.json.get('tgWebAppData')
        if not tg_data:
            return jsonify({'error': 'Missing tgWebAppData'}), 400
        user_id = extract_user_id(tg_data)
        logger.info(f"Успешная аутентификация пользователя: {user_id}")
        return jsonify({'user_id': user_id}), 200
    except Exception as e:
        logger.error(f"Ошибка аутентификации: {e}")
        return jsonify({'error': 'Something went wrong'}), 403

@app.route('/playlists', methods=['POST'])
def get_playlists():
    """Возвращает все плейлисты пользователя."""
    try:
        logger.info(f"Получен запрос к /playlists: {request.json}")
        user_id = request.json.get("user_id")
        if not user_id:
            return jsonify({'error': 'Missing user_id'}), 400
        
        user_dir = os.path.join(PATH, f"user_{user_id}")
        playlists_file = os.path.join(user_dir, "playlists.json")
        os.makedirs(user_dir, exist_ok=True)
        
        playlists = load_playlists(user_dir, playlists_file)
        
        # Загружаем данные о треках
        track_data_dict = {}
        for track_folder in os.listdir(user_dir):
            if not track_folder.startswith("track_"):
                continue
            track_path = os.path.join(user_dir, track_folder)
            if os.path.isdir(track_path):
                data_file = os.path.join(track_path, "data.txt")
                with open(data_file, "r", encoding="utf-8") as f:
                    track_data = json.load(f)
                track_data_dict[track_folder] = {
                    "title": track_data.get("title", "Без названия").lower(),
                    "artist": track_data.get("artist", "Неизвестный исполнитель"),
                    "file": os.path.join(track_path, "song.mp3"),
                    "cover": os.path.join(track_path, "cover.jpeg")
                }
        
        # Сортируем треки в плейлистах в соответствии с порядком в playlists.json
        for playlist in playlists:
            tracks = []
            for track_entry in playlist.get("tracks", []):
                track_id = track_entry.get("id")
                if track_id in track_data_dict:
                    tracks.append(track_data_dict[track_id])
            playlist["tracks"] = tracks
        
        logger.info(f"Возвращены плейлисты для user_{user_id}: {len(playlists)} плейлистов")
        return jsonify({"playlists": playlists}), 200
    except Exception as e:
        logger.error(f"Ошибка получения плейлистов: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/create_playlist', methods=['POST'])
def create_playlist():
    """Создаёт новый плейлист для пользователя."""
    try:
        logger.info(f"Получен запрос к /create_playlist: {request.json}")
        user_id = request.json.get("user_id")
        playlist = request.json.get("playlist")
        if not user_id or not playlist or not playlist.get("name"):
            return jsonify({'error': 'Missing user_id or playlist data'}), 400
        
        user_dir = os.path.join(PATH, f"user_{user_id}")
        playlists_file = os.path.join(user_dir, "playlists.json")
        os.makedirs(user_dir, exist_ok=True)
        
        playlists = load_playlists(user_dir, playlists_file)
        playlists.append({"name": playlist["name"], "tracks": playlist.get("tracks", [])})
        
        with open(playlists_file, "w", encoding="utf-8") as f:
            json.dump(playlists, f)
        
        logger.info(f"Создан новый плейлист '{playlist['name']}' для user_{user_id}")
        return jsonify({"status": "success", "playlists": playlists}), 200
    except Exception as e:
        logger.error(f"Ошибка создания плейлиста: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/add_track', methods=['POST'])
def add_track():
    """Добавляет новый трек для пользователя и привязывает его к плейлисту."""
    try:
        logger.info(f"Получен запрос к /add_track: form={request.form}, files={request.files}")
        track_data = json.loads(request.form.get("track_data", "{}"))
        file = request.files.get("file")
        
        if not track_data:
            logger.error("Отсутствует track_data в запросе")
            return jsonify({"error": "Missing track_data"}), 400
        if not file:
            logger.error("Отсутствует файл в запросе")
            return jsonify({"error": "Missing file"}), 400
        
        user_id = track_data.get("user_id")
        track_id = track_data.get("file_id")
        playlist_name = track_data.get("playlist_name", DEFAULT_PLAYLIST)
        title = track_data.get("title", "Без названия")
        artist = track_data.get("artist", "Неизвестный исполнитель")
        
        if not user_id or not track_id:
            logger.error(f"Некорректные данные: user_id={user_id}, track_id={track_id}")
            return jsonify({"error": "Invalid track_data: missing user_id or file_id"}), 400
        
        user_dir = os.path.join(PATH, f"user_{user_id}")
        track_dir = os.path.join(user_dir, f"track_{track_id}")
        playlists_file = os.path.join(user_dir, "playlists.json")
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(track_dir, exist_ok=True)
        
        # Сохраняем данные трека
        track_data_path = os.path.join(track_dir, "data.txt")
        with open(track_data_path, "w", encoding="utf-8") as f:
            json.dump({"title": title, "artist": artist}, f)
        logger.info(f"Сохранены данные трека: {track_data_path}")
        
        # Сохраняем аудиофайл
        audio_path = os.path.join(track_dir, "song.mp3")
        file.save(audio_path)
        if not os.path.exists(audio_path):
            logger.error(f"Не удалось сохранить аудиофайл: {audio_path}")
            return jsonify({"error": "Failed to save audio file"}), 500
        
        logger.info(f"Аудиофайл успешно сохранён: {audio_path}")
        
        # Скачиваем обложку асинхронно
        cover_save_path = os.path.join(track_dir, "cover.jpeg")
        executor.submit(download_cover, artist, title, cover_save_path)
        
        # Обновляем плейлисты
        playlists = load_playlists(user_dir, playlists_file)
        playlist_found = False
        for playlist in playlists:
            if playlist["name"] == playlist_name:
                if not any(t["id"] == f"track_{track_id}" for t in playlist["tracks"]):
                    playlist["tracks"].append({"id": f"track_{track_id}", "title": title, "artist": artist})
                playlist_found = True
                break
        if not playlist_found:
            playlists.append({"name": playlist_name, "tracks": [{"id": f"track_{track_id}", "title": title, "artist": artist}]})
            logger.info(f"Создан новый плейлист '{playlist_name}' для трека user_{user_id}")
        
        with open(playlists_file, "w", encoding="utf-8") as f:
            json.dump(playlists, f)
        
        logger.info(f"Трек добавлен в плейлист '{playlist_name}' для user_{user_id}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Ошибка при добавлении трека: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

@app.route('/delete_playlist', methods=['POST'])
def delete_playlist():
    """Удаляет плейлист пользователя."""
    try:
        logger.info(f"Получен запрос к /delete_playlist: {request.json}")
        data = request.get_json()
        user_id = data.get("user_id")
        playlist_name = data.get("playlist_name")

        if not user_id or not playlist_name:
            return jsonify({'error': 'Missing user_id or playlist_name'}), 400

        user_dir = os.path.join(PATH, f"user_{user_id}")
        playlists_file = os.path.join(user_dir, "playlists.json")
        os.makedirs(user_dir, exist_ok=True)

        if not os.path.exists(playlists_file):
            return jsonify({'error': 'Playlists file not found'}), 404

        playlists = load_playlists(user_dir, playlists_file)
        logger.info(f"Удаление плейлиста: '{playlist_name}'")
        logger.info(f"Существующие плейлисты: {[p['name'] for p in playlists]}")
        playlists = [p for p in playlists if not (p["name"] == playlist_name)]
        logger.info(f"Плейлисты после удаления: {[p['name'] for p in playlists]}")

        with open(playlists_file, "w", encoding="utf-8") as f:
            json.dump(playlists, f)

        logger.info(f"Плейлист '{playlist_name}' удален для user_{user_id}")
        return jsonify({"status": "success", "playlists": playlists}), 200
    except Exception as e:
        logger.error(f"Ошибка удаления плейлиста: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

@app.route('/')
def index():
    """Отображает главную страницу."""
    logger.info("Запрос к /")
    return render_template('index.html')

@app.route('/static/<path:path>')
def serve_static(path):
    """Отдает статические файлы."""
    logger.info(f"Запрос к /static/{path}")
    return send_from_directory('static', path)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=True)