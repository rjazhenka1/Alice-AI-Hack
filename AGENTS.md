# EventOps AI — AGENTS.md

Этот файл — главный источник истины для всех, кто работает над проектом.
Читай его полностью перед тем как писать код. Обновляй, если меняешь контракт.

---

## Что это за проект

**EventOps AI** — веб-сервис для координации команды во время мероприятия.
Координатор голосом или текстом описывает проблему → Алиса анализирует контекст,
находит свободных людей, создаёт тикет и отправляет уведомление исполнителям в Telegram.

**Главная ценность Алисы:** она не просто чат — она операционный агент.
Понимает неструктурированный текст ("на входе толпа"), сама определяет роль и исполнителей,
вызывает функции, объясняет решение.

---

## Архитектура

```
[React Frontend :5173]
        │  HTTP REST + polling
[FastAPI Backend :8000]
    ├── api/          — роутеры
    ├── agent/        — Алиса, function calling, контекст
    ├── notifier.py   — asyncio.Queue → Telegram Bot API
    └── models.py     — SQLAlchemy
        │
[PostgreSQL :5432]
        │
[Alice AI API]   — YandexGPT, STT (внешний)
[Telegram Bot API]                (внешний)
```

Всё поднимается через `docker-compose up`.
Межсервисного взаимодействия нет — один процесс FastAPI.

---

## Стек

| Слой | Технология |
|---|---|
| Frontend | React 18, Vite, TailwindCSS, shadcn/ui, TanStack Query, Zustand |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic |
| БД | PostgreSQL (asyncpg). На локале можно SQLite через aiosqlite |
| AI | Alice AI REST API (YandexGPT), httpx для вызовов |
| Уведомления | httpx → Telegram Bot API |
| Деплой | docker-compose |

Примечание по SDK: для интеграции с AI Studio и SpeechKit допустимо использовать `yandex-ai-studio-sdk` (актуальная ветка релизов `0.20.x`, рекомендуется pin `>=0.20.0,<0.21.0` для стабильности хакатона).

---

## Структура репозитория

```
eventops/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan, CORS
│   │   ├── database.py          # async engine, get_db dependency
│   │   ├── models.py            # SQLAlchemy модели — НЕ МЕНЯТЬ без согласования
│   │   ├── schemas.py           # Pydantic схемы = OpenAPI контракт
│   │   ├── auth.py              # JWT, get_current_staff dependency
│   │   ├── api/
│   │   │   ├── events.py        # /events
│   │   │   ├── staff.py         # /events/{id}/staff
│   │   │   ├── tickets.py       # /events/{id}/tickets
│   │   │   ├── messages.py      # /events/{id}/messages
│   │   │   └── agent.py         # /events/{id}/agent — ГЛАВНЫЙ эндпоинт
│   │   ├── agent/
│   │   │   ├── alice.py         # HTTP-клиент к Alice AI API
│   │   │   ├── tools.py         # function definitions + handlers
│   │   │   ├── router.py        # оркестрация: принять команду → вызвать tools → ответить
│   │   │   └── prompts.py       # системные промпты
│   │   └── notifier.py          # очередь + Telegram
│   ├── alembic/
│   ├── .env.example
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx    # главная — CommandBar + Staff + Tickets
│   │   │   └── EventSetup.jsx   # настройка мероприятия (роли, люди)
│   │   ├── components/
│   │   │   ├── CommandBar.jsx   # голос/текст → агент
│   │   │   ├── AliceResponse.jsx # ответ с кнопками подтверждения
│   │   │   ├── TicketTable.jsx
│   │   │   ├── StaffGrid.jsx
│   │   │   └── MessageFeed.jsx
│   │   ├── api/
│   │   │   └── client.js        # fetch-обёртки, BASE_URL из env
│   │   └── store/
│   │       └── useAppStore.js   # Zustand: event_id, current_staff, auth token
│   ├── .env.example
│   └── Dockerfile
└── docker-compose.yml
```

---

## Переменные окружения

### backend/.env

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/eventops
ALICE_API_KEY=<ключ от Yandex AI Studio>
ALICE_FOLDER_ID=<folder id Yandex Cloud>
TELEGRAM_BOT_TOKEN=<токен бота>
TELEGRAM_WEBHOOK_SECRET=<опциональный секрет для Telegram webhook-запросов>
TELEGRAM_VOICE_DIR=storage/telegram_voice
SECRET_KEY=<случайная строка для JWT>
```

### frontend/.env

```env
VITE_API_URL=http://localhost:8000
```

---

## API контракт

Базовый URL: `http://localhost:8000`
Аутентификация: `Authorization: Bearer <token>` (кроме /auth/login)

### Auth
```
POST   /auth/login              body: {telegram_id}  → {access_token, staff_id, is_admin}
```

### Events
```
GET    /events                  → Event[]
POST   /events                  body: EventCreate → Event
GET    /events/{id}             → Event
GET    /events/{id}/summary     → EventSummary   (полный контекст для Алисы)
```

### Staff
```
GET    /events/{id}/staff               → Staff[]
POST   /events/{id}/staff               body: StaffCreate → Staff
PATCH  /events/{id}/staff/{sid}         body: StaffUpdate → Staff
GET    /events/{id}/staff/free          → FreeStaffResponse
GET    /events/{id}/staff/{sid}/context → MyContext   (что мне делать, мои вопросы)
```

### Roles & Zones
```
GET    /events/{id}/roles               → Role[]
POST   /events/{id}/roles               body: RoleCreate → Role
GET    /events/{id}/zones               → Zone[]
POST   /events/{id}/zones               body: ZoneCreate → Zone
```

### Tickets
```
GET    /events/{id}/tickets             → Ticket[]   (фильтруется по visibility текущего юзера)
POST   /events/{id}/tickets             body: TicketCreate → Ticket
PATCH  /events/{id}/tickets/{tid}       body: TicketUpdate → Ticket
POST   /events/{id}/tickets/{tid}/assign  body: AssignRequest → Ticket
PATCH  /events/{id}/tickets/{tid}/assignments/{aid}  body: ConfirmAssignmentRequest → TicketAssignment
```

### Messages
```
GET    /events/{id}/messages            → Message[]  (фильтруется по visibility)
POST   /events/{id}/messages            body: MessageCreate → Message
PATCH  /events/{id}/messages/{mid}/read → Message
```

### Telegram integration
```
POST   /integrations/telegram/webhook
```

### Agent (Алиса)
```
POST   /events/{id}/agent/command       body: AgentCommandRequest → AgentCommandResponse
POST   /events/{id}/agent/confirm       body: AgentConfirmRequest → Ticket
```

---

## Видимость данных (Visibility)

Логика фильтрации — в бэкенде, фронт её не реализует:

| Visibility | Кто видит |
|---|---|
| `public` | все участники мероприятия |
| `role_only` | только сотрудники той же роли + admin |
| `confidential` | только admin + роли с `can_see_confidential=True` |

**Важно:** Алиса тоже не должна раскрывать confidential-тикеты тем, у кого нет доступа.
В `agent/router.py` перед формированием промпта фильтруй тикеты по правам текущего сотрудника.

Уточнение по безопасности: допускается, что конфиденциальный контекст может использоваться внутри вызова модели для рассуждения, но запрещено возвращать/показывать confidential-данные пользователям без прав доступа. Критичный контроль — на этапе формирования ответа и выборки данных для текущего staff.

---

## Алиса — как работает агент

Файлы: `backend/app/agent/`

### Флоу команды

```
POST /agent/command
  ↓
router.py: handle_command(text, staff, event_summary)
  ↓
alice.py: chat(messages, tools) → YandexGPT API
  ↓
если tool_call → tools.py: execute(tool_name, args) → результат
  ↓
alice.py: chat(messages + tool_result) → финальный ответ
  ↓
AgentCommandResponse(action, message, suggestion, ticket)
```

### Tools (function calling)

Каждый tool — это функция, которую Алиса может вызвать:

| Tool | Что делает |
|---|---|
| `get_free_staff` | возвращает свободных людей, опционально фильтр по зоне/роли |
| `create_ticket` | создаёт тикет в БД |
| `assign_staff` | назначает людей на тикет |
| `get_ticket_list` | список тикетов (для запросов "что сейчас происходит") |
| `send_notification` | отправляет уведомление через notifier |
| `ask_clarification` | Алиса задаёт вопрос (возвращается фронту без действия) |

### Канонические сценарии поведения агента

Ниже обязательные сценарии, которые должны поддерживаться в `backend/app/agent/` и `api/agent.py`.

1. **Однозначный операционный запрос → точный tool call → создание/назначение задачи**
   - Пример запроса: `"Принеси 36 мониторов в Live-зону, назначь Лёшу Грунского"`
   - Ожидаемое поведение:
     - агент выбирает соответствующий tool chain (`create_ticket` + `assign_staff` + `send_notification` при подтверждённом флоу),
     - создаёт тикет,
     - возвращает человекочитаемый ответ, например:
       `"Создал задачу ‘Принести 36 мониторов’ и назначил Лёшу Грунского."`

2. **Запрос, требующий уточнения/ответа пользователя**
   - Пример запроса: `"Нужны люди на входе"` (непонятно сколько, на сколько времени, какая роль в приоритете)
   - Ожидаемое поведение:
     - агент НЕ угадывает,
     - возвращает `ask_clarification`/`question_asked`,
     - отдаёт человекочитаемый уточняющий вопрос,
     - ждёт следующий пользовательский ввод и продолжает сценарий из диалогового контекста `agent_sessions`.

3. **Непонятный/недостаточный запрос → только человекочитаемый ответ без действий**
   - Пример запроса: `"Ну ты поняла"`
   - Ожидаемое поведение:
     - tool calls не выполняются,
     - тикеты и назначения не создаются,
     - агент отвечает безопасно и полезно, например:
       `"Не понял задачу. Опиши, что случилось, где и сколько людей нужно."`

Критично: при недостатке уверенности агент обязан идти в уточнение, а не создавать потенциально неверные назначения.

### Системный промпт (prompts.py)

В системный промпт подставляется:
- Название и описание мероприятия
- Список ролей с их `ai_prompt`
- Список зон
- Текущее время
- Количество свободных людей

Полный список сотрудников не вставляется в промпт целиком — только через tool `get_free_staff`.

### Контекст диалога

Хранится в таблице `agent_sessions` (поле `context` — JSON).
Максимум 20 последних сообщений — обрезай старые при превышении.

---

## Уведомления (notifier.py)

Использует `asyncio.Queue`. Структура:

```python
{
  "telegram_id": "123456789",
  "message": "Новая задача: помочь на регистрации"
}
```

Воркер в фоне читает очередь и шлёт через Telegram Bot API.
Входящие сообщения принимаются через webhook-эндпоинт `/integrations/telegram/webhook`;
текстовые сообщения сохраняются как `Message.content`, голосовые скачиваются через
Telegram `getFile` в `TELEGRAM_VOICE_DIR`, а в `Message.content` сохраняется ссылка
на локальный файл и базовые метаданные.
если задан `TELEGRAM_WEBHOOK_SECRET`,
клиент должен передавать его в заголовке `X-EventOps-Secret`.
Если Telegram недоступен — логируй ошибку, не падай.

---

## Соглашения

### Общие
- Ветки: `feat/alice-agent`, `feat/api-tickets`, `feat/frontend-dashboard`
- Коммиты на русском или английском, главное — понятно
- Не ломай `models.py` без обсуждения — это влияет на всех троих
- Если меняешь эндпоинт — обнови `schemas.py` и этот файл

### Backend
- Все роутеры возвращают Pydantic-схемы, не ORM-объекты напрямую
- Используй `Depends(get_db)` и `Depends(get_current_staff)` везде
- Visibility-фильтрацию делай на уровне SQL-запроса, не в Python
- Ошибки: `HTTPException` со смысловыми статусами (403 для доступа, 404 для not found)

### Frontend
- Все запросы к API — через `api/client.js`, не через прямой fetch в компонентах
- Автообновление таблицы тикетов: `refetchInterval: 5000` (TanStack Query)
- Статус сотрудника: `free` = зелёный, `busy` = жёлтый, `on_task` = красный
- Голосовой ввод — Web Speech API, `lang: 'ru-RU'`
- Токен хранить в Zustand + localStorage

### Alice
- Не раскрывай confidential-данные в финальном ответе пользователю без прав доступа
- Если Алиса не уверена кому назначить — возвращай `ask_clarification`, не угадывай
- Логируй все вызовы Alice API с временем ответа
- Таймаут на вызов Алисы — 15 секунд

### Prompt safety и guardrails
- Базовый режим оркестрации: two-layer (tool-calling + нормализация ответа в `router.py`).
- Допустимо использовать Guardrails в Yandex AI Studio как policy-слой (правила на естественном языке), чтобы:
  - блокировать утечку закрытых данных в финальный ответ,
  - принудительно переводить неоднозначные запросы в уточнение,
  - ограничивать unsafe-инструкции.
- Допустим двухэтапный LLM-конвейер:
  1) primary LLM генерирует tool calls и draft-ответ,
  2) verifier LLM проверяет соответствие policy/visibility и при нарушении перезаписывает ответ в безопасный формат.
- Guardrails и verifier не заменяют серверные проверки прав: финальная авторизация и visibility-фильтрация остаются в backend.
- Guardrails в AI Studio находятся в стадии Preview: учитывать возможные изменения поведения и fallback на серверные проверки.
- В AI Studio на один инстанс модели применяется одно правило модерации: если подключается пользовательское правило, системное правило для инстанса отключается.
- При срабатывании guardrail возможен `content_filter`/`incomplete`; `router.py` обязан обработать это как безопасный user-facing ответ без падения API.

---

## Как запустить

```bash
# Склонировать и поднять
git clone ...
cd eventops
cp backend/.env.example backend/.env   # заполнить ключи
docker-compose up --build

# Применить миграции
docker-compose exec backend alembic upgrade head

# Открыть
Frontend:    http://localhost:5173
API docs:    http://localhost:8000/docs
```

---

## Демо-сценарий (для презентации)

1. Создать мероприятие "ICPC Semifinal"
2. Добавить роли: Регистрация, Техкомитет, Live, Оргкомитет
3. Добавить 10 сотрудников, раздать роли и зоны
4. Координатор пишет голосом: **"На регистрации очередь, нужны люди"**
5. Алиса отвечает: "Рекомендую Анну и Максима — они свободны и ближе всего к входу"
6. Координатор нажимает "Подтвердить"
7. Анне и Максиму приходит уведомление в Telegram
8. Запросить: **"Что сейчас происходит в Live-зоне?"**
9. Показать таблицу тикетов — горящие наверху

---

## Зоны ответственности

| Кто | Файлы | Не трогает |
|---|---|---|
| **Alice dev** | `agent/`, `api/agent.py` | `api/tickets.py`, фронт, `notifier.py` |
| **API dev** | `api/` (кроме agent), `models.py`, `schemas.py`, `auth.py`, `database.py`, Alembic | `agent/` |
| **Frontend dev** | `frontend/` целиком | бэкенд |

`notifier.py` реализует и сопровождает отдельный backend-разработчик (не Alice dev).

**Точки синхронизации:**
- API dev фиксирует эндпоинт → Alice dev и Frontend dev могут от него зависеть
- Если нужен новый эндпоинт — сначала добавь в `schemas.py` и этот файл, потом реализуй
- Общий канал для блокеров: пишем сразу, не ждём стендапа


Не менять стек посреди хакатона
Не добавлять Kafka
Не делать сложную авторизацию
Не делать 10 экранов
Не делать полноценный календарь
Не делать идеальную карту площадки
Не спорить о красоте архитектуры дольше 15 минут
Не мержить AI-generated код без запуска
