#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ADMIN_TELEGRAM_ID="${ADMIN_TELEGRAM_ID:-111111111}"
ADMIN_NAME="${ADMIN_NAME:-Coordinator}"
EVENT_NAME="${EVENT_NAME:-ICPC Semifinal}"
EVENT_DESCRIPTION="${EVENT_DESCRIPTION:-Smoke test}"

if [[ ! -f backend/.env ]]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env from backend/.env.example. Fill external keys there when needed."
fi

if [[ ! -f frontend/.env ]]; then
  cp frontend/.env.example frontend/.env
  echo "Created frontend/.env from frontend/.env.example."
fi

echo "Starting EventOps docker-compose stack..."
docker compose up -d --build

echo "Waiting for backend healthcheck..."
for _ in {1..60}; do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
  echo "Backend did not become healthy. Recent backend logs:"
  docker compose logs --tail=80 backend
  exit 1
fi

echo "Seeding demo event/admin if missing..."
docker compose exec -T \
  -e ADMIN_TELEGRAM_ID="$ADMIN_TELEGRAM_ID" \
  -e ADMIN_NAME="$ADMIN_NAME" \
  -e EVENT_NAME="$EVENT_NAME" \
  -e EVENT_DESCRIPTION="$EVENT_DESCRIPTION" \
  backend python - <<'PY'
import asyncio
import os

from sqlalchemy import select

from app.database import SessionLocal, init_models
from app.models import Event, Staff, StaffStatus


async def main():
    admin_telegram_id = os.environ["ADMIN_TELEGRAM_ID"]
    admin_name = os.environ["ADMIN_NAME"]
    event_name = os.environ["EVENT_NAME"]
    event_description = os.environ["EVENT_DESCRIPTION"]

    await init_models()
    async with SessionLocal() as db:
        admin = await db.scalar(
            select(Staff).where(Staff.telegram_id == admin_telegram_id)
        )
        if admin is not None:
            event = await db.get(Event, admin.event_id)
            print(f"EVENT_ID={admin.event_id}")
            print(f"EVENT_NAME={event.name if event else 'unknown'}")
            print(f"ADMIN_ID={admin.id}")
            print(f"ADMIN_TELEGRAM_ID={admin.telegram_id}")
            print("SEED_STATUS=already_exists")
            return

        event = await db.scalar(select(Event).where(Event.name == event_name))
        if event is None:
            event = Event(name=event_name, description=event_description)
            db.add(event)
            await db.flush()

        admin = Staff(
            event_id=event.id,
            name=admin_name,
            telegram_id=admin_telegram_id,
            is_admin=True,
            status=StaffStatus.free,
        )
        db.add(admin)
        await db.commit()

        print(f"EVENT_ID={event.id}")
        print(f"EVENT_NAME={event.name}")
        print(f"ADMIN_ID={admin.id}")
        print(f"ADMIN_TELEGRAM_ID={admin.telegram_id}")
        print("SEED_STATUS=created")


asyncio.run(main())
PY

echo
echo "Frontend: http://localhost:5173"
echo "API docs: http://localhost:8000/docs"
echo "Admin login Telegram ID: $ADMIN_TELEGRAM_ID"
echo
echo "Useful commands:"
echo "  docker compose logs -f backend"
echo "  docker compose logs -f frontend"
echo "  docker compose down"
