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
const emptyKnowledgeLink = {
  title: "",
  url: "",
  description: "",
  tags: "",
  visibility: "public",
};
const knowledgeModes = [
  { id: "file", label: "Файл" },
  { id: "link", label: "Ссылка" },
  { id: "text", label: "Текст" },
];
const emptyConfidentialityRule = {
  category: "",
  description: "",
  severity: "medium",
};
const emptyStaff = {
  name: "",
  telegram_id: "",
  telegram_username: "",
  role_id: "",
  zone_id: "",
  is_admin: false,
};

const visibilityOptions = [
  { value: "public", label: "Все" },
  { value: "role_only", label: "Роли" },
  { value: "confidential", label: "Закрыто" },
];

const severityOptions = [
  { value: "low", label: "Низкая" },
  { value: "medium", label: "Средняя" },
  { value: "high", label: "Высокая" },
];

function nullable(value) {
  const next = value.trim();
  return next ? next : null;
}

function toOptionalId(value) {
  return value ? Number(value) : null;
}

function parseTags(value) {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
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
  const [confidentialityRules, setConfidentialityRules] = useState([]);
  const [eventForm, setEventForm] = useState(emptyEvent);
  const [formError, setFormError] = useState("");
  const [importText, setImportText] = useState("");
  const [isLoadingCatalog, setIsLoadingCatalog] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [knowledgeFile, setKnowledgeFile] = useState(null);
  const [knowledgeForm, setKnowledgeForm] = useState(emptyKnowledgeLink);
  const [knowledgeItems, setKnowledgeItems] = useState([]);
  const [knowledgeMode, setKnowledgeMode] = useState("file");
  const [knowledgeText, setKnowledgeText] = useState("");
  const [ruleForm, setRuleForm] = useState(emptyConfidentialityRule);
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
      setKnowledgeItems([]);
      setConfidentialityRules([]);
      return;
    }

    let isActive = true;
    setCatalogError("");
    setIsLoadingCatalog(true);

    Promise.all([
      api.getRoles(event.id),
      api.getZones(event.id),
      api.getKnowledge(event.id),
      api.getConfidentialityRules(event.id).catch(() => []),
    ])
      .then(([roleItems, zoneItems, knowledge, rules]) => {
        if (isActive) {
          setRoles(roleItems);
          setZones(zoneItems);
          setKnowledgeItems(knowledge);
          setConfidentialityRules(rules);
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

  const resetKnowledgeForm = () => {
    setKnowledgeForm(emptyKnowledgeLink);
    setKnowledgeFile(null);
    setKnowledgeText("");
  };

  const addKnowledge = (submitEvent) => {
    submitEvent.preventDefault();

    if (!event?.id) {
      return;
    }

    const title = knowledgeForm.title.trim();
    const description = nullable(knowledgeForm.description);
    const tags = knowledgeForm.tags.trim();
    const visibility = knowledgeForm.visibility;

    if (knowledgeMode === "file" && !knowledgeFile) {
      return;
    }
    if (knowledgeMode !== "file" && !title) {
      return;
    }
    if (knowledgeMode === "link" && !knowledgeForm.url.trim()) {
      return;
    }
    if (knowledgeMode === "text" && !knowledgeText.trim()) {
      return;
    }

    save(async () => {
      let created;

      if (knowledgeMode === "file") {
        const formData = new FormData();
        formData.append("file", knowledgeFile);
        formData.append("title", title || knowledgeFile.name);
        if (description) {
          formData.append("description", description);
        }
        if (tags) {
          formData.append("tags", tags);
        }
        formData.append("visibility", visibility);
        formData.append("is_active", "true");
        created = await api.uploadKnowledgeDocument(event.id, formData);
      } else if (knowledgeMode === "link") {
        created = await api.createKnowledgeLink(event.id, {
          title,
          url: knowledgeForm.url.trim(),
          description,
          tags: parseTags(knowledgeForm.tags),
          visibility,
          is_active: true,
        });
      } else {
        const file = new File([knowledgeText.trim()], `${title}.txt`, {
          type: "text/plain",
        });
        const formData = new FormData();
        formData.append("file", file);
        formData.append("title", title);
        if (description) {
          formData.append("description", description);
        }
        if (tags) {
          formData.append("tags", tags);
        }
        formData.append("visibility", visibility);
        formData.append("is_active", "true");
        created = await api.uploadKnowledgeDocument(event.id, formData);
      }

      setKnowledgeItems((items) => [...items, created]);
      resetKnowledgeForm();
    }, "Материал добавлен в базу знаний");
  };

  const addConfidentialityRule = (submitEvent) => {
    submitEvent.preventDefault();
    const category = ruleForm.category.trim();

    if (!event?.id || !category || !ruleForm.description.trim()) {
      return;
    }

    save(async () => {
      const created = await api.createConfidentialityRule(event.id, {
        category,
        description: ruleForm.description.trim(),
        severity: ruleForm.severity,
        is_active: true,
      });
      setConfidentialityRules((items) => [...items, created]);
      setRuleForm(emptyConfidentialityRule);
    }, "Правило конфиденциальности добавлено");
  };

  const parseImportPreview = () => {
    const value = importText.trim();

    if (!value) {
      return [];
    }

    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed.slice(0, 5) : [];
    } catch {
      return value
        .split("\n")
        .slice(0, 5)
        .map((line) => {
          const [name, telegram_id, role] = line.split(",").map((part) => part.trim());
          return { name, telegram_id, role };
        })
        .filter((item) => item.name);
    }
  };

  const importPreview = parseImportPreview();

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
            className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
            placeholder="ICPC Semifinal"
            value={eventForm.name}
            onChange={(changeEvent) =>
              setEventForm((form) => ({ ...form, name: changeEvent.target.value }))
            }
          />
          <textarea
            className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
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
            className="h-11 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
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
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                placeholder="Регистрация"
                value={roleForm.name}
                onChange={(changeEvent) =>
                  setRoleForm((form) => ({ ...form, name: changeEvent.target.value }))
                }
              />
              <textarea
                className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
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
                          ? "border-violet-700"
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
                className="h-11 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
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

          <Section title="База знаний Алисы">
            <form className="space-y-3" onSubmit={addKnowledge}>
              <div className="grid grid-cols-3 gap-2">
                {knowledgeModes.map((mode) => (
                  <button
                    className={`h-9 rounded-lg border text-xs font-semibold ${
                      knowledgeMode === mode.id
                        ? "border-violet-700 bg-violet-700 text-white"
                        : "border-slate-200 bg-white text-slate-600"
                    }`}
                    key={mode.id}
                    type="button"
                    onClick={() => {
                      setKnowledgeMode(mode.id);
                      setKnowledgeFile(null);
                    }}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>

              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                placeholder={knowledgeMode === "file" ? "Название материала, можно оставить пустым" : "Название материала"}
                value={knowledgeForm.title}
                onChange={(changeEvent) =>
                  setKnowledgeForm((form) => ({
                    ...form,
                    title: changeEvent.target.value,
                  }))
                }
              />

              {knowledgeMode === "file" ? (
                <label className="block rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-sm font-medium text-slate-700">
                  {knowledgeFile ? knowledgeFile.name : "Выбрать файл"}
                  <input
                    accept=".pdf,.txt,.mp3,.mp4,.jpeg,.jpg,.png,application/pdf,text/plain,audio/mpeg,video/mp4,image/jpeg,image/png"
                    className="sr-only"
                    type="file"
                    onChange={(changeEvent) => {
                      setKnowledgeFile(changeEvent.target.files?.[0] || null);
                      changeEvent.target.value = "";
                    }}
                  />
                </label>
              ) : null}

              {knowledgeMode === "link" ? (
                <input
                  className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                  placeholder="Ссылка на регламент, карту или документ"
                  value={knowledgeForm.url}
                  onChange={(changeEvent) =>
                    setKnowledgeForm((form) => ({
                      ...form,
                      url: changeEvent.target.value,
                    }))
                  }
                />
              ) : null}

              {knowledgeMode === "text" ? (
                <textarea
                  className="min-h-32 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
                  placeholder="Текст, который Алиса должна знать и искать"
                  value={knowledgeText}
                  onChange={(changeEvent) => setKnowledgeText(changeEvent.target.value)}
                />
              ) : null}

              <textarea
                className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
                placeholder={
                  knowledgeMode === "file"
                    ? "Описание файла. Для скриншотов лучше кратко написать, что на изображении"
                    : "Краткое описание материала"
                }
                value={knowledgeForm.description}
                onChange={(changeEvent) =>
                  setKnowledgeForm((form) => ({
                    ...form,
                    description: changeEvent.target.value,
                  }))
                }
              />

              <div className="grid grid-cols-[1fr_120px] gap-2">
                <input
                  className="h-11 min-w-0 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                  placeholder="Теги через запятую"
                  value={knowledgeForm.tags}
                  onChange={(changeEvent) =>
                    setKnowledgeForm((form) => ({
                      ...form,
                      tags: changeEvent.target.value,
                    }))
                  }
                />
                <select
                  className="h-11 min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-violet-600"
                  value={knowledgeForm.visibility}
                  onChange={(changeEvent) =>
                    setKnowledgeForm((form) => ({
                      ...form,
                      visibility: changeEvent.target.value,
                    }))
                  }
                >
                  {visibilityOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <button
                className="h-11 w-full rounded-lg bg-violet-700 px-4 text-sm font-semibold text-white disabled:opacity-60"
                disabled={
                  isSaving ||
                  (knowledgeMode === "file" && !knowledgeFile) ||
                  (knowledgeMode === "link" && (!knowledgeForm.title.trim() || !knowledgeForm.url.trim())) ||
                  (knowledgeMode === "text" && (!knowledgeForm.title.trim() || !knowledgeText.trim()))
                }
                type="submit"
              >
                Добавить материал
              </button>
            </form>

            {knowledgeItems.length > 0 ? (
              <div className="mt-4 space-y-2">
                {knowledgeItems.map((item) => (
                  <div
                    className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700"
                    key={item.id}
                  >
                    <div className="font-medium text-slate-900">{item.title}</div>
                    <div className="mt-1 break-all text-xs text-slate-500">{item.url}</div>
                    {item.description ? (
                      <div className="mt-1 text-xs text-slate-600">
                        {item.description}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                Материалов базы знаний пока нет.
              </p>
            )}
          </Section>

          <Section title="Конфиденциальность">
            <form className="space-y-2" onSubmit={addConfidentialityRule}>
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                placeholder="Категория закрытых данных"
                value={ruleForm.category}
                onChange={(changeEvent) =>
                  setRuleForm((form) => ({ ...form, category: changeEvent.target.value }))
                }
              />
              <textarea
                className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
                placeholder="Что Алиса не должна раскрывать без прав"
                value={ruleForm.description}
                onChange={(changeEvent) =>
                  setRuleForm((form) => ({
                    ...form,
                    description: changeEvent.target.value,
                  }))
                }
              />
              <select
                className="h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-violet-600"
                value={ruleForm.severity}
                onChange={(changeEvent) =>
                  setRuleForm((form) => ({ ...form, severity: changeEvent.target.value }))
                }
              >
                {severityOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button
                className="h-11 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
                disabled={
                  isSaving || !ruleForm.category.trim() || !ruleForm.description.trim()
                }
                type="submit"
              >
                Добавить правило
              </button>
            </form>
            {confidentialityRules.length > 0 ? (
              <div className="mt-3 space-y-2">
                {confidentialityRules.map((rule) => (
                  <div
                    className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700"
                    key={rule.id}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-900">{rule.category}</span>
                      <span className="rounded-full bg-slate-200 px-2 py-1 text-[11px] text-slate-600">
                        {rule.severity}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-600">
                      {rule.description}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                Правила конфиденциальности ещё не добавлены.
              </p>
            )}
          </Section>

          <Section title="Зоны">
            <form className="space-y-3" onSubmit={createZone}>
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                placeholder="Вход"
                value={zoneForm.name}
                onChange={(changeEvent) =>
                  setZoneForm((form) => ({ ...form, name: changeEvent.target.value }))
                }
              />
              <input
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
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
                className="h-11 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
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
                className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                placeholder="Анна Иванова"
                value={staffForm.name}
                onChange={(changeEvent) =>
                  setStaffForm((form) => ({ ...form, name: changeEvent.target.value }))
                }
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="h-11 min-w-0 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
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
                  className="h-11 min-w-0 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
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
                  className="h-11 min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-violet-600"
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
                  className="h-11 min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-violet-600"
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
                className="h-11 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
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

          <Section title="Импорт волонтёров">
            <textarea
              className="min-h-28 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
              placeholder={'CSV: Анна,222222222,Регистрация\nили JSON: [{"name":"Анна","telegram_id":"222222222"}]'}
              value={importText}
              onChange={(changeEvent) => setImportText(changeEvent.target.value)}
            />
            {importPreview.length > 0 ? (
              <div className="mt-3 space-y-2">
                {importPreview.map((item, index) => (
                  <div
                    className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700"
                    key={`${item.name}-${index}`}
                  >
                    {item.name || "Без имени"}
                    {item.telegram_id ? ` · ${item.telegram_id}` : ""}
                    {item.role ? ` · ${item.role}` : ""}
                  </div>
                ))}
              </div>
            ) : null}
            <p className="mt-3 text-xs text-slate-500">
              Массовый импорт пока готов как UI. Для сохранения пачкой нужен отдельный backend endpoint.
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
