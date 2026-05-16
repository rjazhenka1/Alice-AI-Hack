#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ADMIN_TELEGRAM_ID="${ADMIN_TELEGRAM_ID:-111111111}"
ADMIN_NAME="${ADMIN_NAME:-Coordinator}"
VOLUNTEER_TELEGRAM_ID="${VOLUNTEER_TELEGRAM_ID:-222222222}"
VOLUNTEER_NAME="${VOLUNTEER_NAME:-Volunteer}"
VOLUNTEER_USERNAME="${VOLUNTEER_USERNAME:-eventops_volunteer}"
VOLUNTEER_ROLE_NAME="${VOLUNTEER_ROLE_NAME:-Регистрация}"
VOLUNTEER_ZONE_NAME="${VOLUNTEER_ZONE_NAME:-Вход}"
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
  -e VOLUNTEER_TELEGRAM_ID="$VOLUNTEER_TELEGRAM_ID" \
  -e VOLUNTEER_NAME="$VOLUNTEER_NAME" \
  -e VOLUNTEER_USERNAME="$VOLUNTEER_USERNAME" \
  -e VOLUNTEER_ROLE_NAME="$VOLUNTEER_ROLE_NAME" \
  -e VOLUNTEER_ZONE_NAME="$VOLUNTEER_ZONE_NAME" \
  -e EVENT_NAME="$EVENT_NAME" \
  -e EVENT_DESCRIPTION="$EVENT_DESCRIPTION" \
  backend python - <<'PY'
import asyncio
import os

from sqlalchemy import select

from app.database import SessionLocal, init_models
from app.models import Event, Role, Staff, StaffStatus, Zone


async def main():
    admin_telegram_id = os.environ["ADMIN_TELEGRAM_ID"]
    admin_name = os.environ["ADMIN_NAME"]
    volunteer_telegram_id = os.environ["VOLUNTEER_TELEGRAM_ID"]
    volunteer_name = os.environ["VOLUNTEER_NAME"]
    volunteer_username = os.environ["VOLUNTEER_USERNAME"]
    volunteer_role_name = os.environ["VOLUNTEER_ROLE_NAME"]
    volunteer_zone_name = os.environ["VOLUNTEER_ZONE_NAME"]
    event_name = os.environ["EVENT_NAME"]
    event_description = os.environ["EVENT_DESCRIPTION"]

    await init_models()
    async with SessionLocal() as db:
        event = await db.scalar(select(Event).where(Event.name == event_name))
        if event is None:
            event = Event(name=event_name, description=event_description)
            db.add(event)
            await db.flush()

        role = await db.scalar(
            select(Role).where(Role.event_id == event.id, Role.name == volunteer_role_name)
        )
        if role is None:
            role = Role(
                event_id=event.id,
                name=volunteer_role_name,
                description="Демо-роль для задач у входа и регистрации",
                ai_prompt="Отвечает за регистрацию участников, очереди и помощь на входе.",
                color="#0f766e",
            )
            db.add(role)
            await db.flush()

        zone = await db.scalar(
            select(Zone).where(Zone.event_id == event.id, Zone.name == volunteer_zone_name)
        )
        if zone is None:
            zone = Zone(
                event_id=event.id,
                name=volunteer_zone_name,
                description="Демо-зона для входа и регистрации",
            )
            db.add(zone)
            await db.flush()

        admin = await db.scalar(select(Staff).where(Staff.telegram_id == admin_telegram_id))
        if admin is None:
            admin = Staff(
                event_id=event.id,
                name=admin_name,
                telegram_id=admin_telegram_id,
                is_admin=True,
                status=StaffStatus.free,
            )
            db.add(admin)
            await db.flush()
        else:
            admin.event_id = event.id
            admin.name = admin_name
            admin.is_admin = True

        volunteer = await db.scalar(select(Staff).where(Staff.telegram_id == volunteer_telegram_id))
        if volunteer is None:
            volunteer = Staff(
                event_id=event.id,
                name=volunteer_name,
                telegram_id=volunteer_telegram_id,
                telegram_username=volunteer_username,
                role_id=role.id,
                zone_id=zone.id,
                is_admin=False,
                status=StaffStatus.free,
            )
            db.add(volunteer)
            await db.flush()
        else:
            volunteer.event_id = event.id
            volunteer.name = volunteer_name
            volunteer.telegram_username = volunteer_username
            volunteer.role_id = role.id
            volunteer.zone_id = zone.id
            volunteer.is_admin = False
            volunteer.status = StaffStatus.free

        await db.commit()

        print(f"EVENT_ID={event.id}")
        print(f"EVENT_NAME={event.name}")
        print(f"ADMIN_ID={admin.id}")
        print(f"ADMIN_TELEGRAM_ID={admin.telegram_id}")
        print(f"VOLUNTEER_ID={volunteer.id}")
        print(f"VOLUNTEER_TELEGRAM_ID={volunteer.telegram_id}")
        print(f"VOLUNTEER_ROLE={role.name}")
        print(f"VOLUNTEER_ZONE={zone.name}")
        print("SEED_STATUS=ready")


asyncio.run(main())
PY

echo
echo "Frontend: http://localhost:5173"
echo "API docs: http://localhost:8000/docs"
echo "Admin login Telegram ID: $ADMIN_TELEGRAM_ID"
echo "Volunteer login Telegram ID: $VOLUNTEER_TELEGRAM_ID"
echo
echo "Useful commands:"
echo "  docker compose logs -f backend"
echo "  docker compose logs -f frontend"
echo "  docker compose down"
