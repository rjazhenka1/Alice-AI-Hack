import { useState } from "react";

export default function LoginForm({ error, isLoading, onSubmit }) {
  const [telegramId, setTelegramId] = useState("");

  const submit = (event) => {
    event.preventDefault();
    const value = telegramId.trim();

    if (value) {
      onSubmit(value);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center bg-white px-4 py-8 text-slate-950">
      <p className="text-xs font-semibold uppercase text-teal-700">EventOps AI</p>
      <h1 className="mt-2 text-2xl font-semibold">Вход в штаб</h1>
      <form className="mt-6 space-y-4" onSubmit={submit}>
        <label className="block text-sm font-medium text-slate-700">
          Telegram ID
          <input
            className="mt-2 h-12 w-full rounded-lg border border-slate-300 px-3 text-base outline-none focus:border-teal-600"
            inputMode="numeric"
            placeholder="123456789"
            value={telegramId}
            onChange={(event) => setTelegramId(event.target.value)}
          />
        </label>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <button
          className="h-12 w-full rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isLoading || !telegramId.trim()}
          type="submit"
        >
          {isLoading ? "Входим..." : "Войти"}
        </button>
      </form>
    </main>
  );
}
