import { useEffect, useState } from "react";
import { api } from "../api/client.js";

const roleColors = ["#0f766e", "#2563eb", "#9333ea", "#dc2626", "#ca8a04"];

const emptyEvent = { name: "", description: "" };
const emptyRole = {
  name: "",
  description: "",
  ai_prompt: "",
  color: roleColors[0],
  can_see_confidential: false,
};
const emptyZone = { name: "", description: "" };
const emptyStaff = {
  name: "",
  telegram_id: "",
  telegram_username: "",
  role_id: "",
  zone_id: "",
  is_admin: false,
};

function nullable(value) {
  const next = value.trim();
  return next ? next : null;
}

function toOptionalId(value) {
  return value ? Number(value) : null;
}

function Section({ children, title }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-950">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function EventSetup({ event, onChanged, onEventCreated, staff }) {
  const [catalogError, setCatalogError] = useState("");
  const [eventForm, setEventForm] = useState(emptyEvent);
  const [formError, setFormError] = useState("");
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [roleForm, setRoleForm] = useState(emptyRole);
  const [roles, setRoles] = useState([]);
  const [success, setSuccess] = useState("");
  const [staffForm, setStaffForm] = useState(emptyStaff);
  const [zoneForm, setZoneForm] = useState(emptyZone);
  const [zones, setZones] = useState([]);

  useEffect(() => {
    if (!event?.id) {
      setRoles([]);
      setZones([]);
      return;
    }

    let isActive = true;
    setCatalogError("");
    setIsLoadingCatalog(true);

    Promise.all([api.getRoles(event.id), api.getZones(event.id)])
      .then(([roleItems, zoneItems]) => {
        if (isActive) {
          setRoles(roleItems);
          setZones(zoneItems);
        }
      })
      .catch((error) => {
        if (isActive) {
          setCatalogError(error.message);
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoadingCatalog(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [event?.id]);

  const save = async (callback, message) => {
    setFormError("");
    setSuccess("");
    setIsSaving(true);

    try {
      await callback();
      setSuccess(message);
      onChanged?.();
    } catch (error) {
      setFormError(error.message);
    } finally {
      setIsSaving(false);
    }
  };

  const createEvent = (submitEvent) => {
    submitEvent.preventDefault();
    const name = eventForm.name.trim();

    if (!name) {
      return;
    }

    save(async () => {
      const created = await api.createEvent({
        name,
        description: nullable(eventForm.description),
      });
      setEventForm(emptyEvent);
      onEventCreated(created);
    }, "Мероприятие создано");
  };

  const createRole = (submitEvent) => {
    submitEvent.preventDefault();

    if (!event?.id || !roleForm.name.trim()) {
      return;
    }

    save(async () => {
      const created = await api.createRole(event.id, {
        name: roleForm.name.trim(),
        description: nullable(roleForm.description),
        ai_prompt: nullable(roleForm.ai_prompt),
        color: roleForm.color,
        can_see_confidential: roleForm.can_see_confidential,
      });
      setRoleForm(emptyRole);
      setRoles((items) => [...items, created]);
    }, "Роль добавлена");
  };

  const createZone = (submitEvent) => {
    submitEvent.preventDefault();

    if (!event?.id || !zoneForm.name.trim()) {
      return;
    }

    save(async () => {
      const created = await api.createZone(event.id, {
        name: zoneForm.name.trim(),
        description: nullable(zoneForm.description),
      });
      setZoneForm(emptyZone);
      setZones((items) => [...items, created]);
    }, "Зона добавлена");
  };

  const createStaff = (submitEvent) => {
    submitEvent.preventDefault();

    if (!event?.id || !staffForm.name.trim()) {
      return;
    }

    save(async () => {
      await api.createStaff(event.id, {
        name: staffForm.name.trim(),
        telegram_id: nullable(staffForm.telegram_id),
        telegram_username: nullable(staffForm.telegram_username),
        role_id: toOptionalId(staffForm.role_id),
        zone_id: toOptionalId(staffForm.zone_id),
        is_admin: staffForm.is_admin,
      });
      setStaffForm(emptyStaff);
    }, "Сотрудник добавлен");
  };

  return (
    <div className="space-y-4">
      {formError ? (
        <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{formError}</p>
      ) : null}
      {catalogError ? (
        <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
          {catalogError}
        </p>
      ) : null}
      {success ? (
        <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">
          {success}
        </p>
      ) : null}

      <Section title="Мероприятие">
        <form className="space-y-3" onSubmit={createEvent}>
          <input
            className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="ICPC Semifinal"
            value={eventForm.name}
            onChange={(changeEvent) =>
              setEventForm((form) => ({ ...form, name: changeEvent.target.value }))
            }
          />
          <textarea
            className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600"
            placeholder="Короткое описание для штаба"
            value={eventForm.description}
            onChange={(changeEvent) =>
              setEventForm((form) => ({
                ...form,
                description: changeEvent.target.value,
              }))
            }
          />
          <button
            className="h-11 w-full rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
            disabled={isSaving || !eventForm.name.trim()}
            type="submit"
          >
            Создать событие
          </button>
        </form>
      </Section>

      {!event?.id ? (
        <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="text-sm text-slate-600">
            Создай или выбери мероприятие, чтобы добавить роли, зоны и людей.
          </p>
        </section>
      ) : (
        <>
          <Section title="Роли">
            <form className="space-y-3" onSubmit={createRole}>
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
                placeholder="Регистрация"
                value={roleForm.name}
                onChange={(changeEvent) =>
                  setRoleForm((form) => ({ ...form, name: changeEvent.target.value }))
                }
              />
              <textarea
                className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600"
                placeholder="Что делает роль и как Алисе выбирать исполнителей"
                value={roleForm.ai_prompt}
                onChange={(changeEvent) =>
                  setRoleForm((form) => ({
                    ...form,
                    ai_prompt: changeEvent.target.value,
                  }))
                }
              />
              <div className="grid grid-cols-[1fr_auto] items-center gap-3">
                <div className="flex gap-2">
                  {roleColors.map((color) => (
                    <button
                      aria-label={color}
                      className={`h-8 w-8 rounded-full border-2 ${
                        roleForm.color === color
                          ? "border-slate-950"
                          : "border-transparent"
                      }`}
                      key={color}
                      style={{ backgroundColor: color }}
                      type="button"
                      onClick={() => setRoleForm((form) => ({ ...form, color }))}
                    />
                  ))}
                </div>
                <label className="flex items-center gap-2 text-xs text-slate-600">
                  <input
                    checked={roleForm.can_see_confidential}
                    type="checkbox"
                    onChange={(changeEvent) =>
                      setRoleForm((form) => ({
                        ...form,
                        can_see_confidential: changeEvent.target.checked,
                      }))
                    }
                  />
                  confidential
                </label>
              </div>
              <button
                className="h-11 w-full rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
                disabled={isSaving || !roleForm.name.trim()}
                type="submit"
              >
                Добавить роль
              </button>
            </form>
            <div className="mt-4 flex flex-wrap gap-2">
              {roles.map((role) => (
                <span
                  className="rounded-full px-3 py-1 text-xs font-medium text-white"
                  key={role.id}
                  style={{ backgroundColor: role.color || "#0f766e" }}
                >
                  {role.name}
                </span>
              ))}
            </div>
          </Section>

          <Section title="Зоны">
            <form className="space-y-3" onSubmit={createZone}>
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
                placeholder="Вход"
                value={zoneForm.name}
                onChange={(changeEvent) =>
                  setZoneForm((form) => ({ ...form, name: changeEvent.target.value }))
                }
              />
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
                placeholder="Описание зоны"
                value={zoneForm.description}
                onChange={(changeEvent) =>
                  setZoneForm((form) => ({
                    ...form,
                    description: changeEvent.target.value,
                  }))
                }
              />
              <button
                className="h-11 w-full rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
                disabled={isSaving || !zoneForm.name.trim()}
                type="submit"
              >
                Добавить зону
              </button>
            </form>
            <div className="mt-4 flex flex-wrap gap-2">
              {zones.map((zone) => (
                <span
                  className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600"
                  key={zone.id}
                >
                  {zone.name}
                </span>
              ))}
            </div>
          </Section>

          <Section title="Люди">
            <form className="space-y-3" onSubmit={createStaff}>
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
                placeholder="Анна Иванова"
                value={staffForm.name}
                onChange={(changeEvent) =>
                  setStaffForm((form) => ({ ...form, name: changeEvent.target.value }))
                }
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="h-11 min-w-0 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
                  inputMode="numeric"
                  placeholder="Telegram ID"
                  value={staffForm.telegram_id}
                  onChange={(changeEvent) =>
                    setStaffForm((form) => ({
                      ...form,
                      telegram_id: changeEvent.target.value,
                    }))
                  }
                />
                <input
                  className="h-11 min-w-0 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
                  placeholder="username"
                  value={staffForm.telegram_username}
                  onChange={(changeEvent) =>
                    setStaffForm((form) => ({
                      ...form,
                      telegram_username: changeEvent.target.value,
                    }))
                  }
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <select
                  className="h-11 min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-teal-600"
                  value={staffForm.role_id}
                  onChange={(changeEvent) =>
                    setStaffForm((form) => ({
                      ...form,
                      role_id: changeEvent.target.value,
                    }))
                  }
                >
                  <option value="">Роль</option>
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
                <select
                  className="h-11 min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-teal-600"
                  value={staffForm.zone_id}
                  onChange={(changeEvent) =>
                    setStaffForm((form) => ({
                      ...form,
                      zone_id: changeEvent.target.value,
                    }))
                  }
                >
                  <option value="">Зона</option>
                  {zones.map((zone) => (
                    <option key={zone.id} value={zone.id}>
                      {zone.name}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  checked={staffForm.is_admin}
                  type="checkbox"
                  onChange={(changeEvent) =>
                    setStaffForm((form) => ({
                      ...form,
                      is_admin: changeEvent.target.checked,
                    }))
                  }
                />
                Администратор
              </label>
              <button
                className="h-11 w-full rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
                disabled={isSaving || !staffForm.name.trim()}
                type="submit"
              >
                Добавить человека
              </button>
            </form>
            <p className="mt-4 text-xs text-slate-500">
              Сейчас в событии: {staff.length} участников
            </p>
          </Section>
        </>
      )}

      {isLoadingCatalog ? (
        <p className="text-sm text-slate-500">Обновляем справочники...</p>
      ) : null}
    </div>
  );
}
