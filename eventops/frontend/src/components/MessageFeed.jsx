import { useState } from "react";

export default function MessageFeed({ error, isLoading, messages, onMarkRead, onSend }) {
  const [content, setContent] = useState("");

  const submit = (event) => {
    event.preventDefault();
    const value = content.trim();

    if (!value) {
      return;
    }

    onSend({ content: value, visibility: "public" });
    setContent("");
  };

  if (isLoading && messages.length === 0) {
    return <p className="text-sm text-slate-500">Загружаем сообщения...</p>;
  }

  if (error) {
    return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>;
  }

  return (
    <div className="space-y-3">
      <form
        className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
        onSubmit={submit}
      >
        <textarea
          className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
          placeholder="Сообщение всем участникам"
          value={content}
          onChange={(event) => setContent(event.target.value)}
        />
        <button
          className="h-10 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
          disabled={!content.trim()}
          type="submit"
        >
          Отправить
        </button>
      </form>

      {messages.length === 0 ? (
        <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="text-sm text-slate-600">Сообщений пока нет.</p>
        </section>
      ) : null}

      {messages.map((message) => (
        <article
          className={`rounded-lg border p-4 shadow-sm ${
            message.is_read
              ? "border-slate-200 bg-white"
              : "border-violet-200 bg-violet-50"
          }`}
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
          {!message.is_read ? (
            <button
              className="mt-3 h-9 rounded-lg border border-slate-300 bg-white px-3 text-xs font-medium text-slate-700"
              type="button"
              onClick={() => onMarkRead(message.id)}
            >
              Прочитано
            </button>
          ) : null}
        </article>
      ))}
    </div>
  );
}
