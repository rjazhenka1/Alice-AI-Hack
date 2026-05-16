#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ADMIN_TELEGRAM_ID="${ADMIN_TELEGRAM_ID:-111111111}"
ADMIN_NAME="${ADMIN_NAME:-Coordinator}"
ADMIN_TELEGRAM_USERNAME="${ADMIN_TELEGRAM_USERNAME:-BellatorHonoris}"
VOLUNTEER_TELEGRAM_ID="${VOLUNTEER_TELEGRAM_ID:-222222222}"
VOLUNTEER_NAME="${VOLUNTEER_NAME:-Максим Альжанов}"
VOLUNTEER_USERNAME="${VOLUNTEER_USERNAME:-rjazhenka1}"
VOLUNTEER_ROLE_NAME="${VOLUNTEER_ROLE_NAME:-Регистрация}"
VOLUNTEER_ZONE_NAME="${VOLUNTEER_ZONE_NAME:-Вход}"
EVENT_NAME="${EVENT_NAME:-ICPC Semifinal}"
EVENT_DESCRIPTION="${EVENT_DESCRIPTION:-Clean dev smoke test}"

if [[ ! -f backend/.env ]]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env from backend/.env.example. Fill external keys there when needed."
fi

if [[ ! -f frontend/.env ]]; then
  cp frontend/.env.example frontend/.env
  echo "Created frontend/.env from frontend/.env.example."
fi

echo "This will remove the project docker containers and named volumes for a clean local start."
echo "Project: $ROOT_DIR"
echo

if [[ "${EVENTOPS_RESET_YES:-}" != "1" ]]; then
  read -r -p "Continue? Type yes: " answer
  if [[ "$answer" != "yes" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

echo "Stopping and deleting containers, networks, and volumes..."
docker compose down -v --remove-orphans

echo "Building and starting stack..."
docker compose up -d --build

echo "Waiting for backend healthcheck..."
for _ in {1..90}; do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
  echo "Backend did not become healthy. Recent backend logs:"
  docker compose logs --tail=120 backend
  exit 1
fi

echo "Running migrations..."
docker compose exec -T backend alembic upgrade head

echo "Seeding clean event, admin, volunteer, role, and zone..."
docker compose exec -T \
  -e ADMIN_TELEGRAM_ID="$ADMIN_TELEGRAM_ID" \
  -e ADMIN_NAME="$ADMIN_NAME" \
  -e ADMIN_TELEGRAM_USERNAME="$ADMIN_TELEGRAM_USERNAME" \
  -e VOLUNTEER_TELEGRAM_ID="$VOLUNTEER_TELEGRAM_ID" \
  -e VOLUNTEER_NAME="$VOLUNTEER_NAME" \
  -e VOLUNTEER_USERNAME="$VOLUNTEER_USERNAME" \
  -e VOLUNTEER_ROLE_NAME="$VOLUNTEER_ROLE_NAME" \
  -e VOLUNTEER_ZONE_NAME="$VOLUNTEER_ZONE_NAME" \
  -e EVENT_NAME="$EVENT_NAME" \
  -e EVENT_DESCRIPTION="$EVENT_DESCRIPTION" \
  backend python - <<'SEED_PY'
import asyncio
import os

from app.database import SessionLocal
from app.models import Event, Role, Staff, StaffStatus, Zone


async def main():
    admin_telegram_id = os.environ["ADMIN_TELEGRAM_ID"]
    admin_name = os.environ["ADMIN_NAME"]
    admin_telegram_username = os.environ["ADMIN_TELEGRAM_USERNAME"].strip().lstrip("@").lower()
    volunteer_telegram_id = os.environ["VOLUNTEER_TELEGRAM_ID"]
    volunteer_name = os.environ["VOLUNTEER_NAME"]
    volunteer_username = os.environ["VOLUNTEER_USERNAME"]
    volunteer_role_name = os.environ["VOLUNTEER_ROLE_NAME"]
    volunteer_zone_name = os.environ["VOLUNTEER_ZONE_NAME"]
    event_name = os.environ["EVENT_NAME"]
    event_description = os.environ["EVENT_DESCRIPTION"]

    async with SessionLocal() as db:
        event = Event(name=event_name, description=event_description)
        db.add(event)
        await db.flush()

        role = Role(
            event_id=event.id,
            name=volunteer_role_name,
            description="Демо-роль для задач у входа и регистрации",
            ai_prompt="Отвечает за регистрацию участников, очереди и помощь на входе.",
            color="#7c3aed",
        )
        db.add(role)
        await db.flush()

        zone = Zone(
            event_id=event.id,
            name=volunteer_zone_name,
            description="Демо-зона для входа и регистрации",
        )
        db.add(zone)
        await db.flush()

        admin = Staff(
            event_id=event.id,
            name=admin_name,
            telegram_id=admin_telegram_id,
            telegram_username=admin_telegram_username,
            is_admin=True,
            status=StaffStatus.free,
        )
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
        db.add_all([admin, volunteer])
        await db.commit()

        print(f"EVENT_ID={event.id}")
        print(f"EVENT_NAME={event.name}")
        print(f"ADMIN_ID={admin.id}")
        print(f"ADMIN_TELEGRAM_ID={admin.telegram_id}")
        print(f"ADMIN_TELEGRAM_USERNAME=@{admin.telegram_username}")
        print(f"VOLUNTEER_ID={volunteer.id}")
        print(f"VOLUNTEER_TELEGRAM_ID={volunteer.telegram_id}")
        print(f"VOLUNTEER_ROLE={role.name}")
        print(f"VOLUNTEER_ZONE={zone.name}")
        print("RESET_SEED_STATUS=ready")


asyncio.run(main())
SEED_PY

echo
echo "Clean dev stack is ready."
echo "Frontend: http://localhost:5173"
echo "API docs: http://localhost:8000/docs"
echo "Admin login Telegram username: @$ADMIN_TELEGRAM_USERNAME"
echo "Volunteer login Telegram username: @$VOLUNTEER_USERNAME"
echo
echo "Useful commands:"
echo "  docker compose logs -f backend"
echo "  docker compose logs -f frontend"
echo "  docker compose down"
