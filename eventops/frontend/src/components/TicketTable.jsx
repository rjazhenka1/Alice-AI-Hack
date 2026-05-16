import { useState } from "react";
import AliceResponse from "./AliceResponse.jsx";
import CommandBar from "./CommandBar.jsx";

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

const statusOrder = {
  new: 0,
  waiting: 1,
  in_progress: 2,
  resolved: 3,
  closed: 4,
};

const statusStyles = {
  new: "border-slate-200 bg-white",
  in_progress: "border-sky-200 bg-sky-50",
  waiting: "border-amber-200 bg-amber-50",
  resolved: "border-emerald-200 bg-emerald-50",
  closed: "border-slate-200 bg-slate-50",
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
  agentError,
  agentResponse,
  isAgentLoading = false,
  isConfirming = false,
  error,
  filters,
  isLoading,
  mode = "admin",
  onFilterChange,
  onAgentConfirm,
  onAgentReject,
  onCommandSubmit,
  onQuestion,
  onStatusChange,
  staff,
  tickets,
}) {
  const [assignments, setAssignments] = useState({});
  const [openQuestionTicketId, setOpenQuestionTicketId] = useState(null);
  const [questions, setQuestions] = useState({});

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

  const visibleTickets =
    mode === "admin" && filters.status
      ? tickets.filter((ticket) => ticket.status === filters.status)
      : tickets;
  const orderedTickets = visibleTickets
    .map((ticket, index) => ({ index, ticket }))
    .sort((left, right) => {
      const leftOrder = statusOrder[left.ticket.status] ?? 99;
      const rightOrder = statusOrder[right.ticket.status] ?? 99;

      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }

      return left.index - right.index;
    })
    .map((item) => item.ticket);

  return (
    <div className="space-y-4">
      {mode === "admin" ? (
        <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-950">Новая команда</h2>
          <CommandBar
            disabled={isAgentLoading || isConfirming}
            onSubmit={onCommandSubmit}
          />
          {isAgentLoading ? (
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500">
              Алиса разбирает команду...
            </p>
          ) : null}
          {agentError ? (
            <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
              {agentError}
            </p>
          ) : null}
          <AliceResponse
            isConfirming={isConfirming}
            response={agentResponse}
            onConfirm={onAgentConfirm}
            onReject={onAgentReject}
          />
        </section>
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

      {orderedTickets.map((ticket) => {
        const selectedStaff = assignments[ticket.id] || [];

        return (
        <article
          className={`rounded-lg border p-4 shadow-sm ${
            statusStyles[ticket.status] || statusStyles.new
          }`}
          key={ticket.id}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">
                {ticket.title}
              </h2>
              <p className="mt-1 text-xs font-medium text-slate-500">
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
                    className={`h-10 rounded-lg border text-xs font-medium ${
                      ticket.status === option.status
                        ? "border-slate-950 bg-slate-950 text-white"
                        : "border-slate-300 bg-white text-slate-700"
                    }`}
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
