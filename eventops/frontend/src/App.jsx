import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import AliceResponse from "./components/AliceResponse.jsx";
import CommandBar from "./components/CommandBar.jsx";
import EventSelector from "./components/EventSelector.jsx";
import LoginForm from "./components/LoginForm.jsx";
import MessageFeed from "./components/MessageFeed.jsx";
import StaffGrid from "./components/StaffGrid.jsx";
import TicketTable from "./components/TicketTable.jsx";
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
  const [agentError, setAgentError] = useState("");
  const [agentResponse, setAgentResponse] = useState(null);
  const [events, setEvents] = useState([]);
  const [eventsError, setEventsError] = useState("");
  const [isCommandLoading, setIsCommandLoading] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [isLoginLoading, setIsLoginLoading] = useState(false);
  const [lastCommand, setLastCommand] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesError, setMessagesError] = useState("");
  const [isMessagesLoading, setIsMessagesLoading] = useState(false);
  const [staff, setStaff] = useState([]);
  const [staffError, setStaffError] = useState("");
  const [isStaffLoading, setIsStaffLoading] = useState(false);
  const [tickets, setTickets] = useState([]);
  const [ticketsError, setTicketsError] = useState("");
  const [isTicketsLoading, setIsTicketsLoading] = useState(false);
  const eventId = useAppStore((state) => state.eventId);
  const token = useAppStore((state) => state.token);
  const logout = useAppStore((state) => state.logout);
  const setCurrentStaff = useAppStore((state) => state.setCurrentStaff);
  const setEventId = useAppStore((state) => state.setEventId);
  const setToken = useAppStore((state) => state.setToken);
  const selectedEvent = events.find((event) => String(event.id) === eventId);
  const selectedEventId = selectedEvent?.id;

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

  useEffect(() => {
    if (!selectedEventId) {
      setTickets([]);
      return;
    }

    let isActive = true;

    const loadTickets = () => {
      setTicketsError("");
      setIsTicketsLoading(true);

      api
        .getTickets(selectedEventId)
        .then((items) => {
          if (isActive) {
            setTickets(items);
          }
        })
        .catch((error) => {
          if (isActive) {
            setTicketsError(error.message);
          }
        })
        .finally(() => {
          if (isActive) {
            setIsTicketsLoading(false);
          }
        });
    };

    loadTickets();
    const timer = window.setInterval(loadTickets, 5000);

    return () => {
      isActive = false;
      window.clearInterval(timer);
    };
  }, [selectedEventId]);

  useEffect(() => {
    if (!selectedEventId) {
      setMessages([]);
      setStaff([]);
      return;
    }

    let isActive = true;

    const loadTeam = () => {
      setMessagesError("");
      setStaffError("");
      setIsMessagesLoading(true);
      setIsStaffLoading(true);

      Promise.all([api.getStaff(selectedEventId), api.getMessages(selectedEventId)])
        .then(([staffItems, messageItems]) => {
          if (isActive) {
            setStaff(staffItems);
            setMessages(messageItems);
          }
        })
        .catch((error) => {
          if (isActive) {
            setStaffError(error.message);
            setMessagesError(error.message);
          }
        })
        .finally(() => {
          if (isActive) {
            setIsMessagesLoading(false);
            setIsStaffLoading(false);
          }
        });
    };

    loadTeam();
    const timer = window.setInterval(loadTeam, 5000);

    return () => {
      isActive = false;
      window.clearInterval(timer);
    };
  }, [selectedEventId]);

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

  const sendCommand = async (command) => {
    if (!selectedEvent) {
      return;
    }

    const payload = command.audioBase64
      ? { audio_base64: command.audioBase64 }
      : { text: command.text };

    setAgentError("");
    setAgentResponse(null);
    setIsCommandLoading(true);
    setLastCommand(command);

    try {
      const response = await api.sendCommand(selectedEvent.id, payload);
      setAgentResponse(response);
    } catch (error) {
      setAgentError(error.message);
    } finally {
      setIsCommandLoading(false);
    }
  };

  const confirmSuggestion = async (ticketId, staffIds, accept) => {
    if (!selectedEvent) {
      return;
    }

    setAgentError("");
    setIsConfirming(true);

    try {
      await api.confirmSuggestion(selectedEvent.id, {
        ticket_id: ticketId,
        accept,
        staff_ids: staffIds.length > 0 ? staffIds : null,
      });
      setAgentResponse(null);
    } catch (error) {
      setAgentError(error.message);
    } finally {
      setIsConfirming(false);
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
                <CommandBar
                  disabled={isCommandLoading || isConfirming}
                  onSubmit={sendCommand}
                />
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
              {isCommandLoading ? (
                <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500">
                  Отправляем команду Алисе...
                </p>
              ) : null}
              {agentError ? (
                <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
                  {agentError}
                </p>
              ) : null}
              <AliceResponse
                isConfirming={isConfirming}
                response={agentResponse}
                onConfirm={(ticketId, staffIds) =>
                  confirmSuggestion(ticketId, staffIds, true)
                }
                onReject={(ticketId) => confirmSuggestion(ticketId, [], false)}
              />
            </div>
          ) : activeTab === "tickets" ? (
            <TicketTable
              error={ticketsError}
              isLoading={isTicketsLoading}
              tickets={tickets}
            />
          ) : activeTab === "team" ? (
            <div className="space-y-5">
              <section>
                <h2 className="mb-3 text-sm font-semibold text-slate-700">
                  Команда
                </h2>
                <StaffGrid
                  error={staffError}
                  isLoading={isStaffLoading}
                  staff={staff}
                />
              </section>
              <section>
                <h2 className="mb-3 text-sm font-semibold text-slate-700">
                  Сообщения
                </h2>
                <MessageFeed
                  error={messagesError}
                  isLoading={isMessagesLoading}
                  messages={messages}
                />
              </section>
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
