#!/bin/bash

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Переменные для PID
SERVER_PID=""
TUNNEL_PID=""
BOT_PID=""

# Папка для логов
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# Проверка, занят ли порт
check_port() {
    local port=$1
    if lsof -i :$port > /dev/null 2>&1; then
        echo -e "${RED}Порт $port занят другим процессом.${NC}"
        echo -e "${BLUE}Попытка найти и завершить процесс...${NC}"
        pid=$(lsof -t -i :$port)
        if [ -n "$pid" ]; then
            kill -9 $pid 2>/dev/null
            sleep 1
            if lsof -i :$port > /dev/null 2>&1; then
                echo -e "${RED}Не удалось освободить порт $port. Попробуйте вручную или используйте другой порт (например, 5003).${NC}"
                exit 1
            else
                echo -e "${GREEN}Порт $port успешно освобожден.${NC}"
            fi
        else
            echo -e "${RED}Не удалось определить PID процесса. Используйте другой порт (например, 5003).${NC}"
            exit 1
        fi
    fi
}

# Проверка наличия необходимых программ и файлов
check_dependencies() {
    echo -e "${BLUE}Проверка зависимостей...${NC}"
    
    # Проверка Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Python3 не установлен. Пожалуйста, установите Python3.${NC}"
        exit 1
    fi
    
    # Проверка pip
    if ! command -v pip3 &> /dev/null; then
        echo -e "${RED}pip3 не установлен. Пожалуйста, установите pip3.${NC}"
        exit 1
    fi
    
    # Проверка npm
    if ! command -v npm &> /dev/null; then
        echo -e "${RED}npm не установлен. Пожалуйста, установите Node.js.${NC}"
        exit 1
    fi
    
    # Проверка localtunnel
    if ! command -v lt &> /dev/null; then
        echo -e "${BLUE}localtunnel не найден. Установка localtunnel...${NC}"
        npm install -g localtunnel
    fi

    # Проверка Server/requirements.txt
    if [ ! -f Server/requirements.txt ]; then
        echo -e "${RED}Файл Server/requirements.txt не найден!${NC}"
        echo -e "${RED}Создайте файл Server/requirements.txt с необходимыми зависимостями, например:${NC}"
        echo -e "${RED}flask==2.3.3${NC}"
        exit 1
    fi

    # Установка зависимостей Python для сервера
    echo -e "${BLUE}Установка зависимостей Python для сервера...${NC}"
    pip3 install -r Server/requirements.txt


    # Проверка package.json
    if [ ! -f package.json ]; then
        echo -e "${RED}Файл package.json не найден!${NC}"
        echo -e "${RED}Создайте файл package.json с необходимыми зависимостями, например:${NC}"
        echo -e "${RED}{\n  \"name\": \"music-player\",\n  \"version\": \"1.0.0\",\n  \"dependencies\": {\n    \"localtunnel\": \"^2.0.2\"\n  }\n}${NC}"
        exit 1
    fi

    # Очистка кэша npm
    echo -e "${BLUE}Очистка кэша npm...${NC}"
    npm cache clean --force

    # Установка зависимостей npm
    echo -e "${BLUE}Установка зависимостей npm...${NC}"
    rm -rf node_modules package-lock.json
    npm install
}

# Запуск туннеля и обновление .env
start_tunnel() {
    echo -e "${BLUE}Запуск локального туннеля...${NC}"
    
    # Создаем временный файл для вывода команды lt
    TEMP_FILE=$(mktemp)
    
    # Запускаем lt в фоне и перенаправляем вывод во временный файл
    lt --port 5002 > "$TEMP_FILE" 2>&1 &
    TUNNEL_PID=$!
    
    # Ждем несколько секунд, чтобы туннель успел запуститься
    sleep 3
    
    # Получаем URL из вывода
    TUNNEL_URL=$(grep -o "https://.*\.loca\.lt" "$TEMP_FILE" | head -n 1)
    
    # Удаляем временный файл
    rm "$TEMP_FILE"
    
    if [ -z "$TUNNEL_URL" ]; then
        echo -e "${RED}Не удалось получить URL туннеля. Попробуйте запустить скрипт еще раз.${NC}"
        cleanup
        exit 1
    fi
    
    # Убиваем процесс temporary lt и запускаем его с нужным URL
    kill $TUNNEL_PID 2>/dev/null
    sleep 1
    
    # Запускаем с правильным субдоменом, извлеченным из URL
    SUBDOMAIN=$(echo "$TUNNEL_URL" | sed 's/https:\/\/\(.*\)\.loca\.lt/\1/')
    
    echo -e "${BLUE}Запуск локального туннеля с субдоменом $SUBDOMAIN...${NC}"
    lt --port 5002 --subdomain "$SUBDOMAIN" > "$LOG_DIR/tunnel.log" 2>&1 &
    TUNNEL_PID=$!
    
    echo -e "${GREEN}Локальный туннель запущен на $TUNNEL_URL (PID: $TUNNEL_PID). Логи: $LOG_DIR/tunnel.log${NC}"
    
    # Обновляем SERVER_URL в .env
    echo -e "${BLUE}Обновление SERVER_URL в .env...${NC}"
    
    # Проверяем существование .env
    if [ ! -f .env ]; then
        echo -e "${BLUE}Файл .env не найден. Создаем новый файл...${NC}"
        echo "SERVER_URL=$TUNNEL_URL" > .env
        echo -e "${RED}ВНИМАНИЕ: Создан новый .env файл. Вам необходимо добавить BOT_TOKEN!${NC}"
        echo -e "${RED}Например: BOT_TOKEN=ваш_токен_бота${NC}"
    else
        # Проверяем, содержит ли .env переменную SERVER_URL
        if grep -q "SERVER_URL=" .env; then
            # Обновляем существующую переменную
            sed -i "s|SERVER_URL=.*|SERVER_URL=$TUNNEL_URL|g" .env
        else
            # Добавляем новую переменную, сохраняя существующие
            echo "SERVER_URL=$TUNNEL_URL" >> .env
        fi
        
        # Проверяем, есть ли BOT_TOKEN
        if ! grep -q "BOT_TOKEN=" .env; then
            echo -e "${RED}ВНИМАНИЕ: В файле .env отсутствует BOT_TOKEN!${NC}"
            echo -e "${RED}Пожалуйста, добавьте строку BOT_TOKEN=ваш_токен_бота в файл .env${NC}"
        fi
    fi
    
    echo -e "${GREEN}SERVER_URL обновлен в .env: $TUNNEL_URL${NC}"
    
    # Даем время туннелю на установление соединения
    sleep 2
}

# Запуск сервера
start_server() {
    echo -e "${BLUE}Запуск сервера...${NC}"
    cd Server
    check_port 5002
    python3 server.py > "../$LOG_DIR/server.log" 2>&1 &
    SERVER_PID=$!
    cd ..
    echo -e "${GREEN}Сервер запущен (PID: $SERVER_PID). Логи: $LOG_DIR/server.log${NC}"
}

# Запуск бота
start_bot() {
    echo -e "${BLUE}Запуск бота...${NC}"
    cd Bot
    python3 bot.py > "../$LOG_DIR/bot.log" 2>&1 &
    BOT_PID=$!
    cd ..
    echo -e "${GREEN}Бот запущен (PID: $BOT_PID). Логи: $LOG_DIR/bot.log${NC}"
}

# Функция мониторинга и перезапуска для каждого процесса
monitor_process() {
    local pid=$1
    local start_func=$2
    local name=$3
    while true; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${RED}$name завершился (PID: $pid). Перезапуск...${NC}"
            $start_func
            pid=$!
            case $name in
                "Сервер")
                    SERVER_PID=$pid
                    ;;
                "Туннель")
                    TUNNEL_PID=$pid
                    ;;
                "Бот")
                    BOT_PID=$pid
                    ;;
            esac
        fi
        sleep 5  # Проверка каждые 5 секунд
    done
}

# Обработка завершения скрипта
cleanup() {
    echo -e "${BLUE}Завершение работы приложения...${NC}"
    
    # Завершение процессов с использованием SIGTERM
    if [ -n "$SERVER_PID" ]; then
        echo -e "${BLUE}Завершение сервера (PID: $SERVER_PID)...${NC}"
        kill $SERVER_PID 2>/dev/null
        sleep 1  # Даем время на завершение
        if kill -0 $SERVER_PID 2>/dev/null; then
            echo -e "${RED}Сервер не завершился, принудительное завершение...${NC}"
            kill -9 $SERVER_PID 2>/dev/null
        fi
    fi
    
    if [ -n "$TUNNEL_PID" ]; then
        echo -e "${BLUE}Завершение туннеля (PID: $TUNNEL_PID)...${NC}"
        kill $TUNNEL_PID 2>/dev/null
        sleep 1  # Даем время на завершение
        if kill -0 $TUNNEL_PID 2>/dev/null; then
            echo -e "${RED}Туннель не завершился, принудительное завершение...${NC}"
            kill -9 $TUNNEL_PID 2>/dev/null
        fi
    fi
    
    if [ -n "$BOT_PID" ]; then
        echo -e "${BLUE}Завершение бота (PID: $BOT_PID)...${NC}"
        kill $BOT_PID 2>/dev/null
        sleep 1  # Даем время на завершение
        if kill -0 $BOT_PID 2>/dev/null; then
            echo -e "${RED}Бот не завершился, принудительное завершение...${NC}"
            kill -9 $BOT_PID 2>/dev/null
        fi
    fi
    
    # Убиваем фоновые процессы мониторинга
    echo -e "${BLUE}Завершение фоновых процессов мониторинга...${NC}"
    kill $(jobs -p) 2>/dev/null
    sleep 1  # Даем время на завершение
    
    # Проверяем, остались ли процессы, связанные с портом 5002
    if lsof -i :5002 > /dev/null 2>&1; then
        echo -e "${RED}Порт 5002 все еще занят. Попытка принудительного завершения...${NC}"
        pid=$(lsof -t -i :5002)
        if [ -n "$pid" ]; then
            kill -9 $pid 2>/dev/null
            sleep 1
            if lsof -i :5002 > /dev/null 2>&1; then
                echo -e "${RED}Не удалось освободить порт 5002. Завершайте процесс вручную.${NC}"
            else
                echo -e "${GREEN}Порт 5002 успешно освобожден.${NC}"
            fi
        fi
    fi
    
    echo -e "${GREEN}Все процессы завершены.${NC}"
    exit 0
}

# Регистрация обработчика сигналов
trap cleanup SIGINT SIGTERM

# Запуск приложения
echo -e "${BLUE}Запуск музыкального приложения...${NC}"

# Проверка зависимостей
check_dependencies

# Сначала запускаем туннель, чтобы получить SERVER_URL
start_tunnel

# Затем запускаем сервер, который будет использовать SERVER_URL
start_server

# Запуск бота
start_bot

# Запуск мониторинга процессов в отдельных фоновых процессах
monitor_process "$TUNNEL_PID" start_tunnel "Туннель" &
monitor_process "$SERVER_PID" start_server "Сервер" &
monitor_process "$BOT_PID" start_bot "Бот" &

echo -e "${GREEN}Приложение запущено! Нажмите Ctrl+C для завершения.${NC}"

# Ожидание завершения
wait