export default function ProfilePanel({ currentStaff, event, onLogout }) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <p className="text-xs font-semibold uppercase text-slate-500">
          Пользователь
        </p>
        <h2 className="mt-2 text-base font-semibold text-slate-950">
          Staff #{currentStaff?.id || "-"}
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          {currentStaff?.isAdmin ? "Администратор" : "Участник"}
        </p>
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
