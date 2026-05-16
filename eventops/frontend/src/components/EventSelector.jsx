export default function EventSelector({ eventId, events, onChange }) {
  if (events.length === 0) {
    return (
      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
        Нет события
      </span>
    );
  }

  if (events.length === 1) {
    return (
      <span className="max-w-32 truncate rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-700">
        {events[0].name}
      </span>
    );
  }

  return (
    <select
      className="h-9 max-w-40 rounded-md border border-slate-300 bg-white px-2 text-xs text-slate-700"
      value={eventId}
      onChange={(event) => onChange(event.target.value)}
    >
      {events.map((event) => (
        <option key={event.id} value={event.id}>
          {event.name}
        </option>
      ))}
    </select>
  );
}
