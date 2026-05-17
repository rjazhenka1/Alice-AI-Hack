# Eventful

Eventful — сервис для координации команды во время мероприятия. Координатор пишет или диктует проблему, а Алиса анализирует контекст, находит релевантных людей, создаёт тикеты, отвечает по базе знаний и отправляет уведомления участникам через Telegram-бота.

Проект сделан как единый веб-сервис: React frontend, FastAPI backend, PostgreSQL с pgvector, интеграции с Yandex AI Studio/SpeechKit/OCR и Telegram Bot API.

## AI-управленческое ядро

Ключевая часть проекта — Алиса как управленческое ядро мероприятия. Это не отдельный чат поверх интерфейса, а слой, который связывает операционные данные: людей, роли, задачи, документы, базу знаний и Telegram-коммуникации.

ИИ используется в нескольких местах:

- **Разбор неструктурированных команд.** Координатор может написать или сказать обычной фразой: `На регистрации очередь, нужны люди`. Алиса определяет намерение: создать задачу, уточнить детали, закрыть тикет, сделать рассылку или ответить по базе знаний.
- **Маршрутизация задач.** Алиса сопоставляет запрос с ролями и участниками: например, понимает, что проблема “на входе из регистрации” относится к роли регистрации, а не к абстрактной группе людей.
- **Function calling / agent orchestration.** Модель не просто отвечает текстом, а выбирает действие: создать тикет, назначить исполнителей, отправить уведомления, найти свободных людей, сделать рассылку или запросить уточнение.
- **RAG по базе знаний.** Загруженные документы, PDF и изображения превращаются в chunks, индексируются в PostgreSQL через pgvector, а Алиса отвечает только на основе найденных фрагментов.
- **OCR для документов и картинок.** Фото расписаний, таблиц и инструкций распознаются через Vision OCR и становятся частью базы знаний.
- **Голосовые сценарии.** Голосовые команды из Web UI и Telegram проходят через SpeechKit STT, сохраняются с транскриптом и обрабатываются как обычные команды Алисе.
- **Структурирование результата.** Ответ модели приводится к строгому контракту: тип запроса, действие, заголовок задачи, описание, исполнители, статус, keywords для RAG.
- **Контроль безопасности.** Backend серверно фильтрует `visibility` для тикетов, сообщений, ответов и базы знаний; `confidentiality rules` передаются Алисе как policy-контекст для безопасной формулировки ответа.
- **Извлечение знаний из коммуникаций.** Ответы организаторов в тикетах могут анализироваться моделью: если в разговоре появилась полезная инструкция, она добавляется в базу знаний и индексируется.

За счёт этого Алиса работает как координатор: не просто генерирует текст, а помогает принимать управленческие решения и сразу превращает их в действия в системе.

## Основные возможности

- управление мероприятиями, ролями, зонами и участниками;
- создание, назначение и закрытие задач;
- ответы и документы внутри тикетов;
- чат с Алисой: текстовые и голосовые команды;
- Telegram-интеграция: входящие сообщения, голосовые, документы, фото, уведомления и рассылки;
- база знаний с загрузкой документов/картинок/PDF и RAG-поиском через pgvector;
- OCR для изображений и документов;
- хранение контекста диалога до 20 сообщений;
- правила видимости: `public`, `role_only`, `confidential`;
- рассылки через бота: всем, по роли или конкретным участникам.

## Архитектура

```text
[React Frontend :5173]
        |
        | REST API
        v
[FastAPI Backend :8000]
    |-- api/          REST-ручки
    |-- agent/        Алиса, промпты, router, RAG orchestration
    |-- notifier.py   очередь уведомлений в Telegram
    |-- rag.py        чанкинг, OCR, embeddings, поиск
    |-- models.py     SQLAlchemy-модели
        |
        v
[PostgreSQL + pgvector :5432]

External:
- Yandex AI Studio / YandexGPT
- Yandex SpeechKit
- Yandex Vision OCR
- Telegram Bot API
```

Backend — один FastAPI-процесс. Отдельных worker-сервисов, Kafka и сложной авторизации нет.

## Стек

Backend:
- Python 3.12
- FastAPI
- SQLAlchemy 2.0 async
- Alembic
- PostgreSQL + pgvector
- httpx
- Yandex AI Studio SDK
- pytest

Frontend:
- React 18
- Vite
- TailwindCSS
- Zustand

Инфраструктура:
- Docker Compose
- Telegram Bot API
- Yandex AI Studio / SpeechKit / Vision OCR

## Структура проекта

```text
eventops/
├── backend/
│   ├── app/
│   │   ├── api/              # REST routers
│   │   ├── agent/            # Alice planner/router/prompts
│   │   ├── main.py           # FastAPI app
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── schemas.py        # Pydantic/OpenAPI schemas
│   │   ├── rag.py            # knowledge base, OCR, embeddings
│   │   └── notifier.py       # Telegram notifications
│   ├── alembic/              # migrations
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   ├── package.json
│   └── Dockerfile
└── docker-compose.yml
```

## Переменные окружения

Создайте backend env:

```bash
cd eventops
cp backend/.env.example backend/.env
```

`backend/.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/eventops
ALICE_API_KEY=<your_ai_studio_api_key>
ALICE_FOLDER_ID=<your_yandex_cloud_folder_id>
ALICE_MODEL=aliceai-llm
ALICE_API_URL=https://llm.api.cloud.yandex.net/foundationModels/v1/completion
ADMIN_TELEGRAM_USERNAME=@your_admin_username
TELEGRAM_BOT_TOKEN=<your_telegram_bot_token>
SECRET_KEY=<random_jwt_secret>
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_VOICE_DIR=storage/telegram_voice
```

Создайте frontend env:

```bash
cp frontend/.env.example frontend/.env
```

`frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

Не коммитьте реальные `.env` и токены.

## Запуск локально

```bash
cd eventops
docker compose up --build
```

После запуска:

- frontend: http://localhost:5173
- backend API: http://localhost:8000
- Swagger/OpenAPI: http://localhost:8000/docs
- Postgres с хоста: `localhost:5433`

Применить миграции:

```bash
docker compose exec backend alembic upgrade head
```

Проверить, что сервисы живы:

```bash
docker compose ps
docker compose logs backend
```

## Telegram webhook

Для локальной разработки нужен публичный HTTPS URL, например через ngrok:

```bash
ngrok http 8000
```

Затем зарегистрируйте webhook у Telegram:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<public-url>/integrations/telegram/webhook"
```

Проверить текущий webhook:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

Важно: пока webhook активен, `getUpdates` будет возвращать конфликт `409`. Это нормальное поведение Telegram.

## Как пользоваться

1. Откройте frontend: http://localhost:5173.
2. Создайте мероприятие.
3. Добавьте роли, зоны и участников.
4. Привяжите участникам `telegram_id` или `telegram_username`.
5. Напишите Алисе команду, например:

```text
На регистрации очередь, нужны люди
```

Алиса должна уточнить недостающие детали или предложить задачу.

Примеры команд:

```text
Создай задачу: принести удлинители в Live-зону
```

```text
Какие актуальные задачи сейчас?
```

```text
Выведи список всех волонтеров, которые обедают в 12:30
```

```text
Напиши всем: общий сбор у штаба через 10 минут
```

## Основные API-ручки

Auth:

```text
POST /auth/login
```

Events:

```text
GET  /events
POST /events
GET  /events/{event_id}/summary
```

Staff, roles, zones:

```text
GET  /events/{event_id}/staff
POST /events/{event_id}/staff
GET  /events/{event_id}/roles
POST /events/{event_id}/roles
GET  /events/{event_id}/zones
POST /events/{event_id}/zones
```

Tickets:

```text
GET   /events/{event_id}/tickets
POST  /events/{event_id}/tickets
PATCH /events/{event_id}/tickets/{ticket_id}
POST  /events/{event_id}/tickets/{ticket_id}/replies
POST  /events/{event_id}/tickets/{ticket_id}/documents
POST  /events/{event_id}/tickets/{ticket_id}/assign
```

Messages and broadcast:

```text
GET  /events/{event_id}/messages
POST /events/{event_id}/messages
POST /events/{event_id}/messages/broadcast
```

Knowledge base:

```text
GET  /events/{event_id}/knowledge
POST /events/{event_id}/knowledge
POST /events/{event_id}/knowledge/upload
GET  /events/{event_id}/knowledge/search?q=<query>
```

Agent:

```text
POST /events/{event_id}/agent/command
POST /events/{event_id}/agent/transcribe
POST /events/{event_id}/agent/confirm
```

Telegram:

```text
POST /integrations/telegram/webhook
GET  /integrations/staff/by-contact
```

Полный контракт доступен в Swagger: http://localhost:8000/docs.

## База знаний и RAG

Документы загружаются через backend или Telegram. После загрузки backend:

1. сохраняет файл в `backend/storage/documents`;
2. извлекает текст напрямую или через OCR;
3. режет текст на chunks;
4. получает embeddings;
5. сохраняет chunks в `document_chunks`;
6. ищет по ним через keyword fallback и pgvector.

Для PostgreSQL используется расширение `vector` и HNSW-индекс.

## Тесты

Backend:

```bash
cd eventops
docker compose exec backend pytest -q
```

Frontend build:

```bash
cd eventops
docker compose exec frontend npm run build
```

Точечный запуск тестов:

```bash
docker compose exec backend pytest tests/test_agent_api.py -q
docker compose exec backend pytest tests/test_auth_roles_tickets_webhook.py -q
```

## Демо-сценарий на 1 минуту

1. Показать мероприятие с ролями и участниками.
2. В чате написать или надиктовать: `На регистрации очередь, нужны люди`.
3. Показать, что Алиса создаёт/уточняет задачу и предлагает исполнителей.
4. Подтвердить назначение.
5. Показать Telegram-уведомление исполнителю.
6. Загрузить фото/документ в базу знаний.
7. Спросить: `Кто обедает в 12:30?`.
8. Показать ответ из RAG по распознанному документу.
9. Отправить рассылку: `Напиши всем: общий сбор у штаба через 10 минут`.

## Ограничения

- Telegram webhook требует публичный HTTPS URL.
- Для Yandex AI/SpeechKit/OCR нужны валидные ключи и folder id.
- Без AI-ключей часть логики работает через fallback, но качество ответов ниже.
- Реальные `.env`, токены и локальные файлы хранилища не должны попадать в Git.
