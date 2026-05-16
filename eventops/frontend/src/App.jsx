import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import CommandBar from "./components/CommandBar.jsx";
import EventSelector from "./components/EventSelector.jsx";
import LoginForm from "./components/LoginForm.jsx";
import { useAppStore } from "./store/useAppStore.js";

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
  const [authError, setAuthError] = useState("");
  const [events, setEvents] = useState([]);
  const [eventsError, setEventsError] = useState("");
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [isLoginLoading, setIsLoginLoading] = useState(false);
  const [lastCommand, setLastCommand] = useState(null);
  const eventId = useAppStore((state) => state.eventId);
  const token = useAppStore((state) => state.token);
  const logout = useAppStore((state) => state.logout);
  const setCurrentStaff = useAppStore((state) => state.setCurrentStaff);
  const setEventId = useAppStore((state) => state.setEventId);
  const setToken = useAppStore((state) => state.setToken);
  const selectedEvent = events.find((event) => String(event.id) === eventId);

  useEffect(() => {
    if (!token) {
      setEvents([]);
      return;
    }

    let isActive = true;
    setEventsError("");
    setIsEventsLoading(true);

    api
      .getEvents()
      .then((items) => {
        if (!isActive) {
          return;
        }

        setEvents(items);
        if (items.length > 0 && !items.some((event) => String(event.id) === eventId)) {
          setEventId(items[0].id);
        }
      })
      .catch((error) => {
        if (isActive) {
          setEventsError(error.message);
        }
      })
      .finally(() => {
        if (isActive) {
          setIsEventsLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [eventId, setEventId, token]);

  const login = async (telegramId) => {
    setAuthError("");
    setIsLoginLoading(true);

    try {
      const data = await api.login(telegramId);
      setToken(data.access_token);
      setCurrentStaff({
        id: data.staff_id,
        isAdmin: data.is_admin,
      });
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setIsLoginLoading(false);
    }
  };

  if (!token) {
    return (
      <LoginForm error={authError} isLoading={isLoginLoading} onSubmit={login} />
    );
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <div className="mx-auto flex min-h-screen max-w-md flex-col bg-white">
        <header className="border-b border-slate-200 px-4 py-3">
          <p className="text-xs font-semibold uppercase text-teal-700">
            EventOps AI
          </p>
          <div className="mt-2 flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold">{titles[activeTab]}</h1>
            <EventSelector
              eventId={eventId}
              events={events}
              onChange={setEventId}
            />
          </div>
        </header>

        <main className="flex-1 px-4 py-4">
          {isEventsLoading ? (
            <p className="mb-4 text-sm text-slate-500">Загружаем события...</p>
          ) : null}
          {eventsError ? (
            <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              {eventsError}
            </p>
          ) : null}
          {activeTab === "command" ? (
            <div className="space-y-4">
              {selectedEvent ? (
                <CommandBar onSubmit={setLastCommand} />
              ) : (
                <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
                  <p className="text-sm text-slate-600">
                    Нет доступного мероприятия для отправки команд.
                  </p>
                </section>
              )}
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
              {activeTab === "profile" ? (
                <button
                  className="mt-4 h-10 rounded-lg border border-slate-300 px-4 text-sm font-medium text-slate-700"
                  type="button"
                  onClick={logout}
                >
                  Выйти
                </button>
              ) : null}
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
