const urlParams = new URLSearchParams(window.location.hash.slice(1));
const tgWebAppData = urlParams.get('tgWebAppData');

// Константы
const TIMEOUT = 10000;
const DEFAULT_PLAYLIST = { name: "Любимое", tracks: [] };

// Состояние приложения
const state = {
    userId: null,
    playlists: [DEFAULT_PLAYLIST],
    currentPlaylistIndex: 0,
    currentTrackIndex: 0,
    isShuffle: false,
    repeatMode: 'none',
    isQuietMode: false
};

// DOM элементы
const elements = {
    app: document.getElementById('app'),
    playButton: document.getElementById('play'),
    shuffleButton: document.getElementById('shuffle'),
    repeatButton: document.getElementById('repeat'),
    progressContainer: document.querySelector('.progress-container'),
    progressBar: document.querySelector('.progress-bar'),
    shareButton: document.getElementById('share-btn'),
    quietButton: document.getElementById('quiet-btn'),
    loader: document.getElementById('loader'),
    title: document.getElementById('title'),
    artist: document.getElementById('artist'),
    cover: document.getElementById('cover')
};

// Инициализация аудио
const audio = new Audio();

async function fetchWithTimeout(url, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {})
    };
    
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), TIMEOUT);
        
        const response = await fetch(url, { 
            ...options, 
            headers, 
            signal: controller.signal 
        });
        
        clearTimeout(timeoutId);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error(`Ошибка запроса к ${url}:`, error);
        throw error;
    }
}

async function preloadCovers() {
    const preloadContainer = document.createElement('div');
    preloadContainer.className = 'preload-images';
    state.playlists.forEach(playlist => {
        playlist.tracks.forEach(track => {
            const img = document.createElement('img');
            img.src = track.cover || '/static/css/standart.png';
            preloadContainer.appendChild(img);
        });
    });
    document.body.appendChild(preloadContainer);
}

async function initPlayer() {
    const overlay = document.createElement('div');
    overlay.className = 'overlay';
    document.body.appendChild(overlay);

    elements.loader.classList.add('active');
    
    try {
        console.log("Запрос авторизации...");
        const authData = await fetchWithTimeout('/auth', {
            method: 'POST',
            body: JSON.stringify({ tgWebAppData })
        });
        
        state.userId = authData.user_id;
        console.log("Авторизация успешна, user_id:", state.userId);

        console.log("Запрос плейлистов...");
        const playlistData = await fetchWithTimeout('/playlists', {
            method: 'POST',
            body: JSON.stringify({ user_id: state.userId })
        });
        
        state.playlists = playlistData.playlists || [DEFAULT_PLAYLIST];
        console.log("Плейлисты получены:", state.playlists);

        await preloadCovers();

        if (state.playlists[state.currentPlaylistIndex].tracks.length > 0) {
            await loadTrack(state.currentTrackIndex);
        } else {
            showEmptyPlaylistMessage();
        }

        elements.loader.classList.remove('active');
        overlay.className = 'overlay hidden';
        overlay.addEventListener('transitionend', () => overlay.remove(), { once: true });
    } catch (error) {
        console.error('Ошибка инициализации плеера:', error);
        elements.loader.classList.remove('active');
        elements.title.textContent = "Ошибка загрузки";
        elements.artist.textContent = "Проверьте подключение к серверу";
    }
}

function showEmptyPlaylistMessage() {
    const title = document.getElementById('title');
    const artist = document.getElementById('artist');
    const coverImg = document.getElementById('cover');
    title.textContent = "Этот плейлист пуст";
    artist.textContent = "Добавьте треки через бота!";
    coverImg.src = '/static/css/standart.png';
    audio.pause();
    elements.playButton.innerHTML = '<i class="fas fa-play"></i>';
    elements.playButton.classList.remove('playing');
    title.classList.remove('exit');
    title.classList.add('active');
    artist.classList.remove('exit');
    artist.classList.add('active');
    coverImg.classList.remove('exit-next', 'exit-prev');
    coverImg.classList.add('active');
}

async function loadTrack(index, direction = 'next') {
    try {
        const tracks = state.playlists[state.currentPlaylistIndex].tracks;
        if (!tracks || tracks.length === 0) {
            showEmptyPlaylistMessage();
            return;
        }

        state.currentTrackIndex = index;
        const track = tracks[index];
        const coverImg = document.getElementById('cover');
        const title = document.getElementById('title');
        const artist = document.getElementById('artist');

        coverImg.classList.remove('active');
        coverImg.classList.add(direction === 'next' ? 'exit-next' : 'exit-prev');
        title.classList.remove('active');
        title.classList.add('exit');
        artist.classList.remove('active');
        artist.classList.add('exit');

        setTimeout(() => {
            coverImg.src = track.cover || '/static/css/standart.png';
            coverImg.classList.remove('exit-next', 'exit-prev');
            coverImg.classList.add('active');
            title.textContent = track.title;
            artist.textContent = track.artist;
            title.classList.remove('exit');
            title.classList.add('active');
            artist.classList.remove('exit');
            artist.classList.add('active');
        }, 300);

        audio.pause();
        audio.src = track.file;
        audio.muted = state.isQuietMode;

        await new Promise((resolve) => {
            audio.addEventListener('loadedmetadata', resolve, { once: true });
        });

        await audio.play();

        elements.playButton.innerHTML = '<i class="fas fa-pause"></i>';
        elements.playButton.classList.add('playing');
    } catch (error) {
        console.error('Ошибка загрузки трека:', error);
        elements.playButton.innerHTML = '<i class="fas fa-play"></i>';
        elements.playButton.classList.remove('playing');
    }
}

async function shuffleTracks() {
    const tracks = state.playlists[state.currentPlaylistIndex].tracks;
    if (!tracks || tracks.length === 0) return;
    return new Promise((resolve) => {
        setTimeout(() => {
            for (let i = tracks.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [tracks[i], tracks[j]] = [tracks[j], tracks[i]];
            }
            state.currentTrackIndex = 0;
            resolve();
        }, 0);
    });
}

function toggleQuietMode() {
    state.isQuietMode = !state.isQuietMode;
    audio.muted = state.isQuietMode;
    elements.quietButton.classList.toggle('active', state.isQuietMode);
}

function updateProgress(e) {
    const { duration, currentTime } = e.srcElement;
    const progressPercent = (currentTime / duration) * 100;
    elements.progressBar.style.width = `${progressPercent}%`;
}

async function setProgress(e) {
    const width = elements.progressContainer.clientWidth;
    const clickX = e.type.includes('touch') ? e.touches[0].clientX - elements.progressContainer.getBoundingClientRect().left : e.offsetX;
    const duration = audio.duration || 0;
    audio.currentTime = (clickX / width) * duration;
}

async function dragProgress(e) {
    e.preventDefault();
    const width = elements.progressContainer.clientWidth;
    const rect = elements.progressContainer.getBoundingClientRect();
    const offsetX = e.type.includes('touch') ? e.touches[0].clientX - rect.left : e.clientX - rect.left;
    const progressPercent = Math.max(0, Math.min(1, offsetX / width));
    const duration = audio.duration || 0;
    audio.currentTime = progressPercent * duration;
    elements.progressBar.style.width = `${progressPercent * 100}%`;
}

function toggleRepeat() {
    const repeatModes = ['none', 'one', 'all'];
    state.repeatMode = repeatModes[(repeatModes.indexOf(state.repeatMode) + 1) % repeatModes.length];
    
    // Меняем иконку в зависимости от режима повтора
    if (state.repeatMode === 'none') {
        elements.repeatButton.innerHTML = '<i class="fas fa-arrow-right"></i>';
    } else if (state.repeatMode === 'one') {
        elements.repeatButton.innerHTML = '<i class="fas fa-repeat"></i><span style="font-size: 10px; font-weight: bold; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); pointer-events: none;">1</span>';
    } else {
        elements.repeatButton.innerHTML = '<i class="fas fa-repeat"></i>';
    }
}

async function toggleShuffle() {
    state.isShuffle = !state.isShuffle;
    
    // Меняем иконку в зависимости от состояния шафла
    if (state.isShuffle) {
        elements.shuffleButton.innerHTML = '<i class="fas fa-random"></i>';
    } else {
        elements.shuffleButton.innerHTML = '<i class="fas fa-bars"></i>';
    }
    
    if (state.isShuffle) {
        await shuffleTracks();
        await loadTrack(state.currentTrackIndex);
    }
}

async function nextTrack() {
    const tracks = state.playlists[state.currentPlaylistIndex].tracks;
    if (tracks.length === 0) return;
    if (state.repeatMode === 'one') {
        audio.currentTime = 0;
        await audio.play();
        return;
    }
    if (state.isShuffle) {
        state.currentTrackIndex = Math.floor(Math.random() * tracks.length);
    } else {
        state.currentTrackIndex = (state.currentTrackIndex + 1) % tracks.length;
    }
    await loadTrack(state.currentTrackIndex, 'next');
}

async function prevTrack() {
    const tracks = state.playlists[state.currentPlaylistIndex].tracks;
    if (tracks.length === 0) return;
    if (state.repeatMode === 'one') {
        audio.currentTime = 0;
        await audio.play();
        return;
    }
    state.currentTrackIndex = (state.currentTrackIndex - 1 + tracks.length) % tracks.length;
    await loadTrack(state.currentTrackIndex, 'prev');
}

let isDragging = false;

elements.progressContainer.addEventListener('mousedown', async (e) => {
    isDragging = true;
    await dragProgress(e);
});

document.addEventListener('mousemove', async (e) => {
    if (isDragging) {
        await dragProgress(e);
    }
});

document.addEventListener('mouseup', () => {
    isDragging = false;
});

elements.progressContainer.addEventListener('touchstart', async (e) => {
    isDragging = true;
    await dragProgress(e);
}, { passive: false });

document.addEventListener('touchmove', async (e) => {
    if (isDragging) {
        await dragProgress(e);
    }
}, { passive: false });

document.addEventListener('touchend', () => {
    isDragging = false;
});

elements.playButton.addEventListener('click', async () => {
    try {
        if (audio.paused || audio.ended) {
            await audio.play();
            elements.playButton.innerHTML = '<i class="fas fa-pause"></i>';
            elements.playButton.classList.add('playing');
        } else {
            audio.pause();
            elements.playButton.innerHTML = '<i class="fas fa-play"></i>';
            elements.playButton.classList.remove('playing');
        }
    } catch (error) {
        console.error('Ошибка управления:', error);
    }
});

elements.shuffleButton.addEventListener('click', toggleShuffle);
elements.repeatButton.addEventListener('click', toggleRepeat);
document.getElementById('next').addEventListener('click', nextTrack);
document.getElementById('prev').addEventListener('click', prevTrack);
elements.progressContainer.addEventListener('click', setProgress);
audio.addEventListener('timeupdate', updateProgress);

audio.addEventListener('ended', async () => {
    if (state.repeatMode === 'one') {
        audio.currentTime = 0;
        await audio.play();
    } else {
        await nextTrack();
    }
});

elements.shareButton.addEventListener('click', async () => {
    const tracks = state.playlists[state.currentPlaylistIndex].tracks;
    if (tracks.length === 0) return;
    const track = tracks[state.currentTrackIndex];
    const shareData = {
        title: track.title,
        text: `Слушаю "${track.title}" от ${track.artist}`,
        url: "https://t.me/MusicPlayerApp_bot"
    };
    try {
        if (navigator.share) {
            await navigator.share(shareData);
        } else {
            await navigator.clipboard.writeText(`${shareData.text} - ${shareData.url}`);
            alert('Ссылка на трек скопирована в буфер обмена!');
        }
    } catch (error) {
        console.error('Ошибка при шеринге:', error);
    }
});

elements.quietButton.addEventListener('click', toggleQuietMode);

initPlayer();