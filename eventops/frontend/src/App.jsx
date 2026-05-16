import { useState } from "react";
import CommandBar from "./components/CommandBar.jsx";

const tabs = [
  { id: "command", label: "Штаб" },
  { id: "tickets", label: "Тикеты" },
  { id: "team", label: "Команда" },
  { id: "profile", label: "Профиль" },
];

const titles = {
  command: "Команда Алисе",
  tickets: "Активные тикеты",
  team: "Люди и роли",
  profile: "Профиль",
};

export default function App() {
  const [activeTab, setActiveTab] = useState("command");
  const [lastCommand, setLastCommand] = useState(null);

  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <div className="mx-auto flex min-h-screen max-w-md flex-col bg-white">
        <header className="border-b border-slate-200 px-4 py-3">
          <p className="text-xs font-semibold uppercase text-teal-700">
            EventOps AI
          </p>
          <div className="mt-2 flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold">{titles[activeTab]}</h1>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
              Нет события
            </span>
          </div>
        </header>

        <main className="flex-1 px-4 py-4">
          {activeTab === "command" ? (
            <div className="space-y-4">
              <CommandBar onSubmit={setLastCommand} />
              {lastCommand ? (
                <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-semibold uppercase text-slate-500">
                    Последняя команда
                  </p>
                  <p className="mt-2 text-sm text-slate-900">
                    {lastCommand.text || "Аудио-команда записана для Алисы"}
                  </p>
                  {lastCommand.mimeType ? (
                    <p className="mt-1 text-xs text-slate-500">
                      {lastCommand.mimeType}
                    </p>
                  ) : null}
                </section>
              ) : null}
            </div>
          ) : (
            <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
              <p className="text-sm text-slate-600">
                Экран "{titles[activeTab]}" будет заполнен следующим шагом.
              </p>
            </section>
          )}
        </main>

        <nav className="grid grid-cols-4 border-t border-slate-200 bg-white">
          {tabs.map((tab) => (
            <button
              className={`px-2 py-3 text-xs font-medium ${
                activeTab === tab.id ? "text-teal-700" : "text-slate-500"
              }`}
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
