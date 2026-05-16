export default function AliceResponse({
  isConfirming,
  onConfirm,
  onReject,
  response,
}) {
  if (!response) {
    return null;
  }

  const ticketId = response.suggestion?.ticket_id || response.ticket?.id;
  const suggestedStaffIds = response.suggestion?.suggested_staff_ids || [];

  return (
    <section className="rounded-lg border border-teal-200 bg-teal-50 p-4">
      <p className="text-xs font-semibold uppercase text-teal-700">Алиса</p>
      <p className="mt-2 text-sm text-slate-900">{response.message}</p>

      {response.suggestion?.reasoning ? (
        <p className="mt-3 text-sm text-slate-600">
          {response.suggestion.reasoning}
        </p>
      ) : null}

      {suggestedStaffIds.length > 0 ? (
        <p className="mt-3 text-xs text-slate-500">
          Предложенные исполнители: {suggestedStaffIds.join(", ")}
        </p>
      ) : null}

      {ticketId ? (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button
            className="h-11 rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
            disabled={isConfirming}
            type="button"
            onClick={() => onConfirm(ticketId, suggestedStaffIds)}
          >
            Подтвердить
          </button>
          <button
            className="h-11 rounded-lg border border-slate-300 bg-white text-sm font-medium text-slate-700 disabled:opacity-60"
            disabled={isConfirming}
            type="button"
            onClick={() => onReject(ticketId)}
          >
            Отменить
          </button>
        </div>
      ) : null}
    </section>
  );
}
