const statusStyles = {
  free: "bg-emerald-100 text-emerald-700",
  busy: "bg-amber-100 text-amber-700",
  on_task: "bg-red-100 text-red-700",
  offline: "bg-slate-100 text-slate-500",
};

const statusLabels = {
  free: "Свободен",
  busy: "Занят",
  on_task: "На задаче",
  offline: "Оффлайн",
};

export default function StaffGrid({ error, isLoading, onStatusChange, staff }) {
  if (isLoading && staff.length === 0) {
    return <p className="text-sm text-slate-500">Загружаем команду...</p>;
  }

  if (error) {
    return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  }

  if (staff.length === 0) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
        <p className="text-sm text-slate-600">Участники ещё не добавлены.</p>
      </section>
    );
  }

  return (
    <div className="space-y-3">
      {staff.map((person) => (
        <article
          className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          key={person.id}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">
                {person.name}
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                {[person.role?.name, person.zone?.name].filter(Boolean).join(" / ") ||
                  "Без роли"}
              </p>
            </div>
            <span
              className={`rounded-full px-2 py-1 text-xs font-medium ${
                statusStyles[person.status] || statusStyles.offline
              }`}
            >
              {statusLabels[person.status] || person.status}
            </span>
          </div>
          {onStatusChange ? (
            <div className="mt-3 grid grid-cols-3 gap-2">
              {["free", "busy", "on_task"].map((status) => (
                <button
                  className={`h-9 rounded-lg text-xs font-medium ${
                    person.status === status
                      ? statusStyles[status]
                      : "border border-slate-300 text-slate-600"
                  }`}
                  key={status}
                  type="button"
                  onClick={() => onStatusChange(person.id, status)}
                >
                  {statusLabels[status]}
                </button>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
