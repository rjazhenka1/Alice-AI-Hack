import { useState } from "react";

export default function LoginForm({
  error,
  isLoading,
  onSubmit,
}) {
  const [telegramUsername, setTelegramUsername] = useState("");

  const submit = (event) => {
    event.preventDefault();
    const value = telegramUsername.trim();

    if (value) {
      onSubmit(value);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center bg-[#fbfaff] px-4 py-8 text-slate-950">
      <p className="text-xs font-semibold uppercase text-violet-700">Eventful</p>
      <h1 className="mt-2 text-2xl font-semibold">Вход в штаб</h1>
      <form className="mt-6 space-y-4" onSubmit={submit}>
        <label className="block text-sm font-medium text-slate-700">
          Telegram username
          <input
            className="mt-2 h-12 w-full rounded-lg border border-slate-300 px-3 text-base outline-none focus:border-violet-600"
            autoComplete="username"
            placeholder="@BellatorHonoris"
            value={telegramUsername}
            onChange={(event) => setTelegramUsername(event.target.value)}
          />
        </label>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <button
          className="h-12 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isLoading || !telegramUsername.trim()}
          type="submit"
        >
          {isLoading ? "Входим..." : "Войти через Telegram"}
        </button>
      </form>
    </main>
  );
}
