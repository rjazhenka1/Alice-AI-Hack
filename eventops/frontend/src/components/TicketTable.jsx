import { useState } from "react";

const priorityStyles = {
  low: "bg-slate-100 text-slate-600",
  medium: "bg-sky-100 text-sky-700",
  high: "bg-amber-100 text-amber-700",
  critical: "bg-red-100 text-red-700",
};

const statusLabels = {
  new: "Новый",
  in_progress: "В работе",
  waiting: "Ожидает",
  resolved: "Решён",
  closed: "Закрыт",
};

const statusOptions = [
  { value: "", label: "Все" },
  { value: "new", label: "Новые" },
  { value: "in_progress", label: "В работе" },
  { value: "waiting", label: "Ожидают" },
  { value: "resolved", label: "Решены" },
];

const responseOptions = [
  { status: "in_progress", label: "ОК, взял" },
  { status: "waiting", label: "Есть вопрос" },
  { status: "resolved", label: "Готово" },
];

export default function TicketTable({
  error,
  filters,
  isLoading,
  mode = "admin",
  onCreate,
  onFilterChange,
  onQuestion,
  onStatusChange,
  staff,
  tickets,
}) {
  const [assignments, setAssignments] = useState({});
  const [form, setForm] = useState({
    title: "",
    description: "",
    priority: "medium",
    type: "incident",
    visibility: "public",
  });
  const [openQuestionTicketId, setOpenQuestionTicketId] = useState(null);
  const [questions, setQuestions] = useState({});

  const submit = (event) => {
    event.preventDefault();

    if (!form.title.trim()) {
      return;
    }

    onCreate({
      title: form.title.trim(),
      description: form.description.trim() || null,
      priority: form.priority,
      type: form.type,
      visibility: form.visibility,
    });
    setForm({
      title: "",
      description: "",
      priority: "medium",
      type: "incident",
      visibility: "public",
    });
  };

  const toggleAssignee = (ticketId, staffId) => {
    setAssignments((items) => {
      const selected = new Set(items[ticketId] || []);

      if (selected.has(staffId)) {
        selected.delete(staffId);
      } else {
        selected.add(staffId);
      }

      return { ...items, [ticketId]: Array.from(selected) };
    });
  };

  const sendQuestion = (event, ticket) => {
    event.preventDefault();
    const content = (questions[ticket.id] || "").trim();

    if (!content) {
      return;
    }

    onQuestion(ticket, content);
    setQuestions((items) => ({ ...items, [ticket.id]: "" }));
    setOpenQuestionTicketId(null);
  };

  if (isLoading && tickets.length === 0) {
    return <p className="text-sm text-slate-500">Загружаем тикеты...</p>;
  }

  return (
    <div className="space-y-4">
      {mode === "admin" ? (
        <form
          className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          onSubmit={submit}
        >
          <h2 className="text-sm font-semibold text-slate-950">Новый тикет</h2>
          <input
            className="h-11 w-full rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-teal-600"
            placeholder="На регистрации очередь"
            value={form.title}
            onChange={(event) =>
              setForm((state) => ({ ...state, title: event.target.value }))
            }
          />
          <textarea
            className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600"
            placeholder="Детали для исполнителей"
            value={form.description}
            onChange={(event) =>
              setForm((state) => ({ ...state, description: event.target.value }))
            }
          />
          <div className="grid grid-cols-3 gap-2">
            <select
              className="h-10 min-w-0 rounded-lg border border-slate-300 bg-white px-2 text-xs outline-none focus:border-teal-600"
              value={form.type}
              onChange={(event) =>
                setForm((state) => ({ ...state, type: event.target.value }))
              }
            >
              <option value="incident">Инцидент</option>
              <option value="planned">План</option>
              <option value="tech">Тех</option>
              <option value="question">Вопрос</option>
            </select>
            <select
              className="h-10 min-w-0 rounded-lg border border-slate-300 bg-white px-2 text-xs outline-none focus:border-teal-600"
              value={form.priority}
              onChange={(event) =>
                setForm((state) => ({ ...state, priority: event.target.value }))
              }
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
            <select
              className="h-10 min-w-0 rounded-lg border border-slate-300 bg-white px-2 text-xs outline-none focus:border-teal-600"
              value={form.visibility}
              onChange={(event) =>
                setForm((state) => ({ ...state, visibility: event.target.value }))
              }
            >
              <option value="public">public</option>
              <option value="role_only">role</option>
              <option value="confidential">conf.</option>
            </select>
          </div>
          <button
            className="h-11 w-full rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
            disabled={!form.title.trim()}
            type="submit"
          >
            Создать тикет
          </button>
        </form>
      ) : null}

      {mode === "admin" ? (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {statusOptions.map((option) => (
            <button
              className={`h-9 shrink-0 rounded-full px-3 text-xs font-medium ${
                filters.status === option.value
                  ? "bg-slate-950 text-white"
                  : "bg-slate-100 text-slate-600"
              }`}
              key={option.value}
              type="button"
              onClick={() => onFilterChange({ status: option.value })}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
      ) : null}

      {tickets.length === 0 ? (
        <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="text-sm text-slate-600">Активных тикетов пока нет.</p>
        </section>
      ) : null}

      {tickets.map((ticket) => {
        const selectedStaff = assignments[ticket.id] || [];

        return (
        <article
          className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          key={ticket.id}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">
                {ticket.title}
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                {statusLabels[ticket.status] || ticket.status}
              </p>
            </div>
            <span
              className={`rounded-full px-2 py-1 text-xs font-medium ${
                priorityStyles[ticket.priority] || priorityStyles.medium
              }`}
            >
              {ticket.priority}
            </span>
          </div>

          {ticket.description ? (
            <p className="mt-3 text-sm text-slate-600">{ticket.description}</p>
          ) : null}

          {(ticket.assignments || []).length > 0 ? (
            <p className="mt-3 text-xs text-slate-500">
              Исполнители:{" "}
              {ticket.assignments
                .map((assignment) => assignment.staff?.name)
                .filter(Boolean)
                .join(", ")}
            </p>
          ) : null}

          {mode === "volunteer" ? (
            <>
              <div className="mt-4 grid grid-cols-3 gap-2">
                {responseOptions.map((option) => (
                  <button
                    className="h-10 rounded-lg border border-slate-300 text-xs font-medium text-slate-700"
                    key={option.status}
                    type="button"
                    onClick={() => {
                      if (option.status === "waiting") {
                        setOpenQuestionTicketId(
                          openQuestionTicketId === ticket.id ? null : ticket.id,
                        );
                        return;
                      }

                      onStatusChange(ticket.id, option.status);
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              {openQuestionTicketId === ticket.id ? (
                <form className="mt-3 space-y-2" onSubmit={(event) => sendQuestion(event, ticket)}>
                  <textarea
                    className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600"
                    placeholder="Что нужно уточнить?"
                    value={questions[ticket.id] || ""}
                    onChange={(event) =>
                      setQuestions((items) => ({
                        ...items,
                        [ticket.id]: event.target.value,
                      }))
                    }
                  />
                  <button
                    className="h-10 w-full rounded-lg bg-slate-950 text-xs font-semibold text-white disabled:opacity-60"
                    disabled={!(questions[ticket.id] || "").trim()}
                    type="submit"
                  >
                    Отправить вопрос
                  </button>
                </form>
              ) : null}
            </>
          ) : (
            <div className="mt-4 grid grid-cols-2 gap-2">
              <button
                className="h-10 rounded-lg border border-slate-300 text-xs font-medium text-slate-700"
                type="button"
                onClick={() => onStatusChange(ticket.id, "in_progress")}
              >
                В работу
              </button>
              <button
                className="h-10 rounded-lg border border-slate-300 text-xs font-medium text-slate-700"
                type="button"
                onClick={() => onStatusChange(ticket.id, "resolved")}
              >
                Решён
              </button>
            </div>
          )}

          {mode === "admin" && staff.length > 0 ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">
                Назначить вручную
              </summary>
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap gap-2">
                  {staff.map((person) => (
                    <button
                      className={`rounded-full px-3 py-1 text-xs font-medium ${
                        selectedStaff.includes(person.id)
                          ? "bg-teal-700 text-white"
                          : "bg-slate-100 text-slate-600"
                      }`}
                      key={person.id}
                      type="button"
                      onClick={() => toggleAssignee(ticket.id, person.id)}
                    >
                      {person.name}
                    </button>
                  ))}
                </div>
                <button
                  className="h-10 w-full rounded-lg bg-slate-950 text-xs font-semibold text-white disabled:opacity-60"
                  disabled={selectedStaff.length === 0}
                  type="button"
                  onClick={() => onStatusChange(ticket.id, null, selectedStaff)}
                >
                  Назначить выбранных
                </button>
              </div>
            </details>
          ) : null}
        </article>
      );
      })}
    </div>
  );
}
