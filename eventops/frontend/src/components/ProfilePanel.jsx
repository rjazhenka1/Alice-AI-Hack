const statusLabels = {
  free: "Свободен",
  busy: "Занят",
  on_task: "На задаче",
  offline: "Оффлайн",
};

export default function ProfilePanel({ context, currentStaff, event, onLogout }) {
  const myTickets = context?.my_tickets || [];
  const myMessages = context?.my_messages || [];
  const isAdmin = currentStaff?.isAdmin || currentStaff?.is_admin;

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-semibold uppercase text-slate-500">
          Пользователь
        </p>
        <h2 className="mt-2 text-base font-semibold text-slate-950">
          {currentStaff?.name || `Staff #${currentStaff?.id || "-"}`}
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          {isAdmin ? "Администратор" : "Участник"}
        </p>
        {currentStaff?.status ? (
          <p className="mt-1 text-sm text-slate-600">
            {statusLabels[currentStaff.status] || currentStaff.status}
          </p>
        ) : null}
        {[currentStaff?.role?.name, currentStaff?.zone?.name]
          .filter(Boolean)
          .length > 0 ? (
          <p className="mt-1 text-sm text-slate-600">
            {[currentStaff?.role?.name, currentStaff?.zone?.name]
              .filter(Boolean)
              .join(" / ")}
          </p>
        ) : null}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-semibold uppercase text-slate-500">
          Мероприятие
        </p>
        <h2 className="mt-2 text-base font-semibold text-slate-950">
          {event?.name || "Не выбрано"}
        </h2>
        {event?.description ? (
          <p className="mt-1 text-sm text-slate-600">{event.description}</p>
        ) : null}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-semibold uppercase text-slate-500">
          Мой контекст
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-2xl font-semibold text-slate-950">
              {myTickets.length}
            </p>
            <p className="text-xs text-slate-500">моих задач</p>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-2xl font-semibold text-slate-950">
              {myMessages.length}
            </p>
            <p className="text-xs text-slate-500">сообщений</p>
          </div>
        </div>
        {myTickets.slice(0, 3).map((ticket) => (
          <p className="mt-3 text-sm text-slate-700" key={ticket.id}>
            {ticket.title}
          </p>
        ))}
      </section>

      <button
        className="h-12 w-full rounded-lg border border-slate-300 text-sm font-semibold text-slate-700"
        type="button"
        onClick={onLogout}
      >
        Выйти
      </button>
    </div>
  );
}
