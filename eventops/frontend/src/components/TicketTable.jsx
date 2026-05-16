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

export default function TicketTable({ error, isLoading, tickets }) {
  if (isLoading && tickets.length === 0) {
    return <p className="text-sm text-slate-500">Загружаем тикеты...</p>;
  }

  if (error) {
    return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  }

  if (tickets.length === 0) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
        <p className="text-sm text-slate-600">Активных тикетов пока нет.</p>
      </section>
    );
  }

  return (
    <div className="space-y-3">
      {tickets.map((ticket) => (
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
        </article>
      ))}
    </div>
  );
}
