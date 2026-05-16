import { useEffect, useState } from "react";
import { api } from "./api/client.js";
import AliceResponse from "./components/AliceResponse.jsx";
import CommandBar from "./components/CommandBar.jsx";
import EventSelector from "./components/EventSelector.jsx";
import LoginForm from "./components/LoginForm.jsx";
import MessageFeed from "./components/MessageFeed.jsx";
import ProfilePanel from "./components/ProfilePanel.jsx";
import StaffGrid from "./components/StaffGrid.jsx";
import TicketTable from "./components/TicketTable.jsx";
import EventSetup from "./pages/EventSetup.jsx";
import { useAppStore } from "./store/useAppStore.js";

const tabs = [
  { id: "command", label: "Штаб" },
  { id: "tickets", label: "Тикеты" },
  { id: "team", label: "Команда" },
  { id: "profile", label: "Профиль" },
];

const titles = {
  command: "Команда Алисе",
  setup: "Настройка",
  tickets: "Активные тикеты",
  team: "Люди и роли",
  profile: "Профиль",
};

function navGridClass(count) {
  if (count === 2) {
    return "grid-cols-2";
  }

  if (count === 5) {
    return "grid-cols-5";
  }

  return "grid-cols-4";
}

const DEMO_ADMIN_TOKEN = "demo-admin-token";
const DEMO_VOLUNTEER_TOKEN = "demo-volunteer-token";
const DEMO_EVENT = {
  id: 1,
  name: "ICPC Semifinal",
  description: "Демо-мероприятие без backend",
};
const DEMO_STAFF = [
  {
    id: 1,
    name: "Координатор",
    is_admin: true,
    role: { name: "Оргкомитет" },
    status: "free",
    zone: { name: "Штаб" },
  },
  {
    id: 2,
    name: "Анна",
    role: { name: "Регистрация" },
    status: "free",
    zone: { name: "Вход" },
  },
  {
    id: 3,
    name: "Максим",
    role: { name: "Техкомитет" },
    status: "busy",
    zone: { name: "Live" },
  },
];
const DEMO_TICKETS = [
  {
    id: 1,
    title: "Очередь на регистрации",
    description: "Нужны два свободных человека у входа.",
    priority: "high",
    status: "waiting",
    assignments: [
      {
        id: 1,
        confirmed: false,
        staff: { id: 2, name: "Анна", status: "free" },
      },
    ],
  },
];
const DEMO_MESSAGES = [
  {
    id: 1,
    content: "Проверьте готовность регистрации к открытию.",
    visibility: "public",
    is_read: false,
    created_at: new Date().toISOString(),
  },
];

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
  const [myContext, setMyContext] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [staff, setStaff] = useState([]);
  const [staffError, setStaffError] = useState("");
  const [isStaffLoading, setIsStaffLoading] = useState(false);
  const [tickets, setTickets] = useState([]);
  const [ticketsError, setTicketsError] = useState("");
  const [ticketFilters, setTicketFilters] = useState({ status: "" });
  const [isTicketsLoading, setIsTicketsLoading] = useState(false);
  const eventId = useAppStore((state) => state.eventId);
  const token = useAppStore((state) => state.token);
  const logout = useAppStore((state) => state.logout);
  const setCurrentStaff = useAppStore((state) => state.setCurrentStaff);
  const setEventId = useAppStore((state) => state.setEventId);
  const setToken = useAppStore((state) => state.setToken);
  const selectedEvent = events.find((event) => String(event.id) === eventId);
  const selectedEventId = selectedEvent?.id;
  const currentStaff = useAppStore((state) => state.currentStaff);
  const isDemoMode =
    token === DEMO_ADMIN_TOKEN || token === DEMO_VOLUNTEER_TOKEN;
  const isVolunteerMode = token === DEMO_VOLUNTEER_TOKEN;
  const isAdminMode = Boolean(currentStaff?.isAdmin) && !isVolunteerMode;
  const currentStaffProfile = staff.find((person) => person.id === currentStaff?.id);
  const visibleTabs = isVolunteerMode
    ? [
        { id: "tickets", label: "Задачи" },
        { id: "profile", label: "Профиль" },
      ]
    : isAdminMode
    ? [tabs[0], { id: "setup", label: "Настр." }, ...tabs.slice(1)]
    : tabs;
  const pageTitle =
    isVolunteerMode && activeTab === "tickets" ? "Мои задачи" : titles[activeTab];

  useEffect(() => {
    if (isVolunteerMode && !visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab("tickets");
      return;
    }

    if (activeTab === "setup" && !isAdminMode) {
      setActiveTab("command");
    }
  }, [activeTab, isAdminMode, isVolunteerMode, visibleTabs]);

  useEffect(() => {
    if (!token) {
      setEvents([]);
      return;
    }

    if (isDemoMode) {
      setEvents([DEMO_EVENT]);
      setEventId(DEMO_EVENT.id);
      setEventsError("");
      setIsEventsLoading(false);
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
  }, [eventId, isDemoMode, setEventId, token]);

  useEffect(() => {
    if (!selectedEventId) {
      setTickets([]);
      return;
    }

    if (isDemoMode) {
      setTickets(DEMO_TICKETS);
      setTicketsError("");
      setIsTicketsLoading(false);
      return;
    }

    let isActive = true;

    const loadTickets = () => {
      setTicketsError("");
      setIsTicketsLoading(true);

      api
        .getTickets(selectedEventId, ticketFilters)
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
  }, [isDemoMode, refreshKey, selectedEventId, ticketFilters]);

  useEffect(() => {
    if (!selectedEventId) {
      setMessages([]);
      setStaff([]);
      return;
    }

    if (isDemoMode) {
      setStaff(DEMO_STAFF);
      setMessages(DEMO_MESSAGES);
      setStaffError("");
      setMessagesError("");
      setIsStaffLoading(false);
      setIsMessagesLoading(false);
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
  }, [isDemoMode, refreshKey, selectedEventId]);

  useEffect(() => {
    if (!selectedEventId || !currentStaff?.id) {
      setMyContext(null);
      return;
    }

    if (isDemoMode) {
      const myTickets = tickets.filter((ticket) =>
        (ticket.assignments || []).some(
          (assignment) => assignment.staff?.id === currentStaff.id,
        ),
      );

      setMyContext({
        my_tickets: isVolunteerMode ? myTickets : tickets,
        my_messages: messages,
        role_tickets: isVolunteerMode ? myTickets : tickets,
      });
      return;
    }

    let isActive = true;

    api
      .getStaffContext(selectedEventId, currentStaff.id)
      .then((context) => {
        if (isActive) {
          setMyContext(context);
        }
      })
      .catch(() => {
        if (isActive) {
          setMyContext(null);
        }
      });

    return () => {
      isActive = false;
    };
  }, [currentStaff?.id, isDemoMode, isVolunteerMode, messages, refreshKey, selectedEventId, tickets]);

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

  const startDemo = (role) => {
    const isVolunteer = role === "volunteer";
    const demoStaff = isVolunteer ? DEMO_STAFF[1] : DEMO_STAFF[0];

    setAuthError("");
    setToken(isVolunteer ? DEMO_VOLUNTEER_TOKEN : DEMO_ADMIN_TOKEN);
    setCurrentStaff({
      id: demoStaff.id,
      isAdmin: Boolean(demoStaff.is_admin),
      name: demoStaff.name,
    });
    setEventId(DEMO_EVENT.id);
    setActiveTab(isVolunteer ? "tickets" : "command");
    setEvents([DEMO_EVENT]);
    setStaff(DEMO_STAFF);
    setTickets(DEMO_TICKETS);
    setMessages(DEMO_MESSAGES);
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

    if (isDemoMode) {
      window.setTimeout(() => {
        setAgentResponse({
          action: "ticket_created",
          message: "Демо: рекомендую отправить Анну на регистрацию.",
          suggestion: {
            reasoning: "Анна свободна и уже находится у входа.",
            suggested_staff_ids: [2],
            confidence: "high",
            ticket_id: 1,
          },
          ticket: DEMO_TICKETS[0],
        });
        setIsCommandLoading(false);
      }, 300);
      return;
    }

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

    if (isDemoMode) {
      setTickets((items) =>
        items.map((ticket) =>
          ticket.id === ticketId
            ? {
                ...ticket,
                status: accept ? "in_progress" : ticket.status,
                assignments: accept
                  ? staffIds.map((staffId, index) => ({
                      id: index + 1,
                      confirmed: false,
                      staff: staff.find((person) => person.id === staffId),
                    }))
                  : ticket.assignments,
              }
            : ticket,
        ),
      );
      setAgentResponse(null);
      setIsConfirming(false);
      return;
    }

    try {
      await api.confirmSuggestion(selectedEvent.id, {
        ticket_id: ticketId,
        accept,
        staff_ids: staffIds.length > 0 ? staffIds : null,
      });
      setAgentResponse(null);
      setRefreshKey((key) => key + 1);
    } catch (error) {
      setAgentError(error.message);
    } finally {
      setIsConfirming(false);
    }
  };

  const refreshEventData = () => {
    setRefreshKey((key) => key + 1);
  };

  const eventCreated = (event) => {
    setEvents((items) => [...items, event]);
    setEventId(event.id);
    refreshEventData();
  };

  const createTicket = async (payload) => {
    if (!selectedEvent) {
      return;
    }

    setTicketsError("");

    if (isDemoMode) {
      setTickets((items) => [
        {
          id: Date.now(),
          status: "new",
          assignments: [],
          ...payload,
        },
        ...items,
      ]);
      return;
    }

    try {
      await api.createTicket(selectedEvent.id, payload);
      refreshEventData();
    } catch (error) {
      setTicketsError(error.message);
    }
  };

  const changeTicket = async (ticketId, status, staffIds = null) => {
    if (!selectedEvent) {
      return;
    }

    setTicketsError("");

    if (isDemoMode) {
      setTickets((items) =>
        items.map((ticket) => {
          if (ticket.id !== ticketId) {
            return ticket;
          }

          if (staffIds) {
            return {
              ...ticket,
              assignments: staffIds.map((staffId, index) => ({
                id: index + 1,
                confirmed: false,
                staff: staff.find((person) => person.id === staffId),
              })),
            };
          }

          return status ? { ...ticket, status } : ticket;
        }),
      );
      return;
    }

    try {
      if (staffIds) {
        await api.assignTicket(selectedEvent.id, ticketId, staffIds);
      } else if (status) {
        await api.updateTicket(selectedEvent.id, ticketId, { status });
      }
      refreshEventData();
    } catch (error) {
      setTicketsError(error.message);
    }
  };

  const askTicketQuestion = async (ticket, content) => {
    const message = `Вопрос по задаче #${ticket.id} "${ticket.title}": ${content}`;

    await sendMessage({
      content: message,
      visibility: "public",
    });

    await changeTicket(ticket.id, "waiting");
  };

  const changeStaffStatus = async (staffId, status) => {
    if (!selectedEvent) {
      return;
    }

    setStaffError("");

    if (isDemoMode) {
      setStaff((items) =>
        items.map((person) =>
          person.id === staffId ? { ...person, status } : person,
        ),
      );
      return;
    }

    try {
      await api.updateStaff(selectedEvent.id, staffId, { status });
      refreshEventData();
    } catch (error) {
      setStaffError(error.message);
    }
  };

  const sendMessage = async (payload) => {
    if (!selectedEvent) {
      return;
    }

    setMessagesError("");

    if (isDemoMode) {
      setMessages((items) => [
        {
          id: Date.now(),
          is_read: false,
          created_at: new Date().toISOString(),
          ...payload,
        },
        ...items,
      ]);
      return;
    }

    try {
      await api.createMessage(selectedEvent.id, payload);
      refreshEventData();
    } catch (error) {
      setMessagesError(error.message);
    }
  };

  const markMessageRead = async (messageId) => {
    if (!selectedEvent) {
      return;
    }

    setMessagesError("");

    if (isDemoMode) {
      setMessages((items) =>
        items.map((message) =>
          message.id === messageId ? { ...message, is_read: true } : message,
        ),
      );
      return;
    }

    try {
      await api.markMessageRead(selectedEvent.id, messageId);
      refreshEventData();
    } catch (error) {
      setMessagesError(error.message);
    }
  };

  if (!token) {
    return (
      <LoginForm
        error={authError}
        isLoading={isLoginLoading}
        onDemoAdmin={() => startDemo("admin")}
        onDemoVolunteer={() => startDemo("volunteer")}
        onSubmit={login}
      />
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
            <h1 className="text-lg font-semibold">{pageTitle}</h1>
            <EventSelector
              eventId={eventId}
              events={events}
              onChange={setEventId}
            />
          </div>
        </header>

        <main className="flex-1 px-4 pb-24 pt-4">
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
          ) : activeTab === "setup" ? (
            <EventSetup
              event={selectedEvent}
              staff={staff}
              onChanged={refreshEventData}
              onEventCreated={eventCreated}
            />
          ) : activeTab === "tickets" ? (
            <TicketTable
              error={ticketsError}
              filters={ticketFilters}
              isLoading={isTicketsLoading}
              mode={isVolunteerMode ? "volunteer" : "admin"}
              staff={staff}
              tickets={
                isVolunteerMode
                  ? tickets.filter((ticket) =>
                      (ticket.assignments || []).some(
                        (assignment) => assignment.staff?.id === currentStaff?.id,
                      ),
                    )
                  : tickets
              }
              onCreate={createTicket}
              onFilterChange={(nextFilters) =>
                setTicketFilters((filters) => ({ ...filters, ...nextFilters }))
              }
              onQuestion={askTicketQuestion}
              onStatusChange={changeTicket}
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
                  onStatusChange={changeStaffStatus}
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
                  onMarkRead={markMessageRead}
                  onSend={sendMessage}
                />
              </section>
            </div>
          ) : activeTab === "profile" ? (
            <ProfilePanel
              context={myContext}
              currentStaff={currentStaffProfile || currentStaff}
              event={selectedEvent}
              onLogout={logout}
            />
          ) : (
            <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
              <p className="text-sm text-slate-600">
                Экран "{titles[activeTab]}" будет заполнен следующим шагом.
              </p>
            </section>
          )}
        </main>

        <nav
          className={`fixed bottom-0 left-1/2 z-20 grid w-full max-w-md -translate-x-1/2 border-t border-slate-200 bg-white ${
            navGridClass(visibleTabs.length)
          }`}
        >
          {visibleTabs.map((tab) => (
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
