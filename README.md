# Copart CRM

React-интерфейс + Python-бэкенд. Каждые 10 минут бэкенд открывает ваши поиски Copart и кладёт подходящие авто в CRM. Вход — через Telegram-бота, новые лоты приходят всем, кто включил уведомления.

```
frontend/   React (Vite)   http://127.0.0.1:5173
app.py      FastAPI        http://127.0.0.1:8080
```

## Telegram

1. Создайте бота у [@BotFather](https://t.me/BotFather) и вставьте токен в `.env` как `TELEGRAM_BOT_TOKEN`.
2. Перезапустите `python app.py`.
3. Откройте CRM → **Войти через Telegram** → в боте нажмите **Start**.

Первый вошедший становится администратором. Остальные входят так же: открывают CRM и подтверждают вход в том же боте. Админ на странице **Команда** может отключить человека или выключить ему уведомления.

В боте: `/notify` — вкл/выкл рассылку новых авто.

`TELEGRAM_CHAT_ID` не обязателен. Если задан (личный чат или группа), туда тоже уходят новые лоты.

## Запуск

Два терминала.

**1. Бэкенд**

```powershell
cd "$env:USERPROFILE\Desktop\copart bot"
.\.venv\Scripts\Activate.ps1
python app.py
```

**2. Фронтенд**

```powershell
cd "$env:USERPROFILE\Desktop\copart bot\frontend"
npm install
npm run dev
```

Откройте http://127.0.0.1:5173

Коллеги в той же сети могут открыть `http://<IP-этого-ПК>:5173`.

В CRM добавьте поиск: название + URL с Copart (Vehicle Finder → фильтры → Search → скопировать адрес). Кнопка **Проверить сейчас** сразу обходит Copart. Если сайт покажет капчу, в `.env` должно быть `HEADLESS=false` — откроется Chrome, проверку нужно пройти один раз.
