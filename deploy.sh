#!/bin/bash

# Цвета для вывода
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Проверка наличия необходимых программ
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

  # Установка зависимостей Python для сервера
  echo -e "${BLUE}Установка зависимостей Python для сервера...${NC}"
  pip3 install -r Server/requirements.txt

  # Установка зависимостей Python для бота
  echo -e "${BLUE}Установка зависимостей Python для бота...${NC}"
  pip3 install aiogram python-dotenv

  # Установка зависимостей npm
  echo -e "${BLUE}Установка зависимостей npm...${NC}"
  npm install
}

# Запуск сервера
start_server() {
  echo -e "${BLUE}Запуск сервера...${NC}"
  cd Server
  python3 server.py &
  SERVER_PID=$!
  cd ..
  echo -e "${GREEN}Сервер запущен (PID: $SERVER_PID)${NC}"
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
  lt --port 5002 --subdomain "$SUBDOMAIN" &
  TUNNEL_PID=$!
  
  echo -e "${GREEN}Локальный туннель запущен на $TUNNEL_URL (PID: $TUNNEL_PID)${NC}"
  
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

# Запуск бота
start_bot() {
  echo -e "${BLUE}Запуск бота...${NC}"
  cd Bot
  python3 bot.py &
  BOT_PID=$!
  cd ..
  echo -e "${GREEN}Бот запущен (PID: $BOT_PID)${NC}"
}

# Обработка завершения скрипта
cleanup() {
  echo -e "${BLUE}Завершение работы приложения...${NC}"
  # Завершение процессов
  if [ -n "$SERVER_PID" ]; then
    kill $SERVER_PID 2>/dev/null
  fi
  if [ -n "$TUNNEL_PID" ]; then
    kill $TUNNEL_PID 2>/dev/null
  fi
  if [ -n "$BOT_PID" ]; then
    kill $BOT_PID 2>/dev/null
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

# Запуск туннеля и обновление .env
start_tunnel

# Запуск сервера
start_server

# Запуск бота
start_bot

echo -e "${GREEN}Приложение запущено! Нажмите Ctrl+C для завершения.${NC}"

# Ожидание завершения
wait 