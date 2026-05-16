export default function MessageFeed({ error, isLoading, messages }) {
  if (isLoading && messages.length === 0) {
    return <p className="text-sm text-slate-500">Загружаем сообщения...</p>;
  }

  if (error) {
    return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  }

  if (messages.length === 0) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
        <p className="text-sm text-slate-600">Сообщений пока нет.</p>
      </section>
    );
  }

  return (
    <div className="space-y-3">
      {messages.map((message) => (
        <article
          className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          key={message.id}
        >
          <p className="text-sm text-slate-900">{message.content}</p>
          <p className="mt-2 text-xs text-slate-500">
            {message.visibility}
            {message.created_at
              ? ` · ${new Date(message.created_at).toLocaleTimeString("ru-RU", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}`
              : ""}
          </p>
        </article>
      ))}
    </div>
  );
}
