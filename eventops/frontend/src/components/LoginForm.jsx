import { useState } from "react";

export default function LoginForm({
  error,
  isLoading,
  onDemoAdmin,
  onDemoVolunteer,
  onSubmit,
}) {
  const [telegramId, setTelegramId] = useState("");

  const submit = (event) => {
    event.preventDefault();
    const value = telegramId.trim();

    if (value) {
      onSubmit(value);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center bg-[#fbfaff] px-4 py-8 text-slate-950">
      <p className="text-xs font-semibold uppercase text-violet-700">EventOps AI</p>
      <h1 className="mt-2 text-2xl font-semibold">Вход в штаб</h1>
      <div className="mt-6 grid gap-3">
        <button
          className="h-12 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isLoading}
          type="button"
          onClick={onDemoAdmin}
        >
          Войти как админ
        </button>
        <button
          className="h-12 w-full rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 disabled:opacity-60"
          disabled={isLoading}
          type="button"
          onClick={onDemoVolunteer}
        >
          Войти как волонтёр
        </button>
      </div>

      <form className="mt-6 space-y-4 border-t border-slate-200 pt-6" onSubmit={submit}>
        <label className="block text-sm font-medium text-slate-700">
          Telegram ID
          <input
            className="mt-2 h-12 w-full rounded-lg border border-slate-300 px-3 text-base outline-none focus:border-violet-600"
            inputMode="numeric"
            placeholder="123456789"
            value={telegramId}
            onChange={(event) => setTelegramId(event.target.value)}
          />
        </label>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <button
          className="h-12 w-full rounded-lg bg-violet-700 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isLoading || !telegramId.trim()}
          type="submit"
        >
          {isLoading ? "Входим..." : "Войти"}
        </button>
      </form>
    </main>
  );
}
