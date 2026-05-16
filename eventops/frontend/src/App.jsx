import { useEffect, useRef, useState } from "react";
import { api } from "./api/client.js";
import AliceResponse from "./components/AliceResponse.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import CommandBar from "./components/CommandBar.jsx";
import EventSelector from "./components/EventSelector.jsx";
import LoginForm from "./components/LoginForm.jsx";
import ProfilePanel from "./components/ProfilePanel.jsx";
import TicketTable from "./components/TicketTable.jsx";
import EventSetup from "./pages/EventSetup.jsx";
import { useAppStore } from "./store/useAppStore.js";

const tabs = [
  { id: "chat", label: "Чат" },
  { id: "tickets", label: "Тикеты" },
  { id: "event", label: "Событие" },
  { id: "settings", label: "Настр." },
];

const titles = {
  chat: "Чат с Алисой",
  event: "Создание мероприятия",
  tickets: "Тикеты",
  settings: "Настройки",
};

const APP_NAME = "Eventful";

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
    priority: "medium",
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

function buildAgentContext(chatItems, nextMessage = null) {
  const contextItems = nextMessage ? [...chatItems, nextMessage] : chatItems;

  return contextItems
    .filter((message) => message.from === "me" || message.from === "alice")
    .slice(-20)
    .map((message) => ({
      role: message.from === "me" ? "user" : "assistant",
      text: message.text,
      source: message.source || "agent_text",
    }));
}

function playAliceAudio(response, enabled) {
  if (!enabled || !response?.message) {
    return;
  }

  const audioBase64 = response.audio?.audio_base64;
  if (audioBase64) {
    const format = response.audio?.format || "oggopus";
    const mimeType = format === "oggopus" ? "audio/ogg" : `audio/${format}`;
    const audio = new Audio(`data:${mimeType};base64,${audioBase64}`);
    audio.play().catch(() => {});
    return;
  }

  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(response.message);
  utterance.lang = "ru-RU";
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}

export default function App() {
  const [activeTab, setActiveTab] = useState("chat");
  const [authError, setAuthError] = useState("");
  const [agentError, setAgentError] = useState("");
  const [agentResponse, setAgentResponse] = useState(null);
  const [chat, setChat] = useState([]);
  const [events, setEvents] = useState([]);
  const [eventsError, setEventsError] = useState("");
  const [isCommandLoading, setIsCommandLoading] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [isLoginLoading, setIsLoginLoading] = useState(false);
  const [isAuthVerified, setIsAuthVerified] = useState(false);
  const [messages, setMessages] = useState([]);
  const [messagesError, setMessagesError] = useState("");
  const [broadcastMode, setBroadcastMode] = useState(false);
  const [isMessagesLoading, setIsMessagesLoading] = useState(false);
  const [myContext, setMyContext] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [replyTarget, setReplyTarget] = useState(null);
  const [ticketReplies, setTicketReplies] = useState({});
  const [staff, setStaff] = useState([]);
  const [staffError, setStaffError] = useState("");
  const [isStaffLoading, setIsStaffLoading] = useState(false);
  const [tickets, setTickets] = useState([]);
  const [ticketsError, setTicketsError] = useState("");
  const [ticketFilters, setTicketFilters] = useState({ status: "" });
  const [isTicketsLoading, setIsTicketsLoading] = useState(false);
  const [voiceAlertsEnabled, setVoiceAlertsEnabled] = useState(
    () => localStorage.getItem("eventops_voice_alerts") !== "off",
  );
  const knownVolunteerTicketIdsRef = useRef(new Set());
  const volunteerTicketsInitializedRef = useRef(false);
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
  const isAdminMode = Boolean(currentStaff?.isAdmin);
  const isVolunteerMode = Boolean(token) && !isAdminMode;
  const currentStaffProfile = staff.find((person) => person.id === currentStaff?.id);
  const visibleTabs = isVolunteerMode
    ? [
        { id: "chat", label: "Чат" },
        { id: "tickets", label: "Задачи" },
        { id: "settings", label: "Настр." },
      ]
    : isAdminMode
    ? tabs
    : tabs;
  const pageTitle =
    isVolunteerMode && activeTab === "tickets" ? "Мои задачи" : titles[activeTab];

  useEffect(() => {
    if (!token || isDemoMode) {
      setIsAuthVerified(Boolean(token && isDemoMode));
      return undefined;
    }

    let isActive = true;
    setIsAuthVerified(false);

    api
      .getMe()
      .then((data) => {
        if (!isActive) {
          return;
        }

        setCurrentStaff({
          id: data.staff_id,
          isAdmin: data.is_admin,
        });
        setIsAuthVerified(true);
      })
      .catch((error) => {
        if (isActive && (error.status === 401 || error.status === 403)) {
          logout();
        } else if (isActive) {
          setIsAuthVerified(true);
        }
      });

    return () => {
      isActive = false;
    };
  }, [isDemoMode, logout, setCurrentStaff, token]);

  useEffect(() => {
    if (isVolunteerMode && !visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab("chat");
      return;
    }

    if (activeTab === "event" && !isAdminMode) {
      setActiveTab("chat");
    }
  }, [activeTab, isAdminMode, isVolunteerMode, visibleTabs]);

  useEffect(() => {
    localStorage.setItem("eventops_voice_alerts", voiceAlertsEnabled ? "on" : "off");
  }, [voiceAlertsEnabled]);

  useEffect(() => {
    knownVolunteerTicketIdsRef.current = new Set();
    volunteerTicketsInitializedRef.current = false;
  }, [currentStaff?.id, selectedEventId, token]);

  useEffect(() => {
    if (!isVolunteerMode || !currentStaff?.id) {
      return;
    }

    const myTickets = tickets.filter((ticket) =>
      (ticket.assignments || []).some(
        (assignment) => assignment.staff?.id === currentStaff.id,
      ),
    );

    const knownIds = knownVolunteerTicketIdsRef.current;
    if (!volunteerTicketsInitializedRef.current) {
      knownVolunteerTicketIdsRef.current = new Set(myTickets.map((ticket) => ticket.id));
      volunteerTicketsInitializedRef.current = true;
      return;
    }

    const newTickets = myTickets.filter((ticket) => !knownIds.has(ticket.id));
    if (newTickets.length === 0) {
      return;
    }

    knownVolunteerTicketIdsRef.current = new Set([
      ...Array.from(knownIds),
      ...newTickets.map((ticket) => ticket.id),
    ]);

    if (!voiceAlertsEnabled) {
      return;
    }

    const [firstTicket] = newTickets;
    const message =
      newTickets.length === 1
        ? `Новая задача: ${firstTicket.title}`
        : `У тебя ${newTickets.length} новые задачи. Первая: ${firstTicket.title}`;

    playAliceAudio({ message }, true);
  }, [currentStaff?.id, isVolunteerMode, selectedEventId, tickets, token, voiceAlertsEnabled]);

  useEffect(() => {
    if (!token || messages.length === 0) {
      return;
    }

    setChat((items) => {
      const existing = new Set(items.map((item) => item.messageId).filter(Boolean));
      const incoming = messages
        .filter((message) => {
          if (existing.has(message.id)) {
            return false;
          }

          if (isAdminMode) {
            return message.from_staff_id !== currentStaff?.id;
          }

          return (
            (message.to_staff_id === currentStaff?.id ||
              (message.visibility === "public" && !message.to_staff_id && !message.to_role_id)) &&
            !message.content.startsWith("Ответ по задаче #")
          );
        })
        .slice(0, 10)
        .map((message) => {
          const isPublicBroadcast =
            message.visibility === "public" && !message.to_staff_id && !message.to_role_id;

          return {
            id: `message-${message.id}`,
            messageId: message.id,
            staffId: message.from_staff_id,
            senderName:
              staff.find((person) => person.id === message.from_staff_id)?.name ||
              (isAdminMode ? "Участник" : "Администратор"),
            from: isAdminMode || isPublicBroadcast ? "admin" : "alice",
            text: message.content,
            canReply: isAdminMode && Boolean(message.from_staff_id),
            createdAt: message.created_at,
          };
        });

      return incoming.length > 0 ? [...items, ...incoming] : items;
    });
  }, [currentStaff?.id, isAdminMode, messages, staff, token]);

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
  }, [currentStaff?.id, isVolunteerMode, messages, selectedEventId, tickets]);

  const login = async (telegramUsername) => {
    setAuthError("");
    setIsLoginLoading(true);

    try {
      const data = await api.login(telegramUsername);
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
    setActiveTab("chat");
    setEvents([DEMO_EVENT]);
    setStaff(DEMO_STAFF);
    setTickets(DEMO_TICKETS);
    setMessages(DEMO_MESSAGES);
    setChat([
      {
        id: "hello",
        from: "alice",
        text: isVolunteer
          ? "Я Алиса. Спрашивай по задачам и мероприятию. Если не найду ответ, передам вопрос администратору."
          : "Я Алиса. Здесь будут вопросы команды и ответы по операционной ситуации.",
        createdAt: new Date().toISOString(),
      },
    ]);
  };

  const appendChat = (entry) => {
    const message = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      createdAt: new Date().toISOString(),
      ...entry,
    };

    setChat((items) => [...items, message]);
    return message;
  };

  const routeUnansweredQuestion = async (text) => {
    const content = `Вопрос от ${currentStaffProfile?.name || currentStaff?.name || "участника"}: ${text}`;
    const admin = staff.find((person) => person.is_admin && person.id !== currentStaff?.id);

    await sendMessage(
      admin
        ? { content, to_staff_id: admin.id, visibility: "role_only" }
        : { content, visibility: "public" },
    );
  };

  const handleChatReply = async (target, content) => {
    if (!content) {
      setReplyTarget(target);
      return;
    }

    const staffId = target.staffId || target.from_staff_id;
    if (!staffId) {
      setMessagesError("Не понял, кому отправить ответ.");
      return;
    }

    await sendMessage({
      content,
      to_staff_id: staffId,
      visibility: "role_only",
    });
    setReplyTarget(null);
  };

  const sendBroadcastMessage = async (content) => {
    const text = content.trim();
    if (!text) {
      return;
    }

    await sendMessage({ content: text, visibility: "public" });
    appendChat({
      from: "me",
      text: `Всем: ${text}`,
      source: "admin_broadcast",
    });
    setBroadcastMode(false);
  };

  const loadTicketReplies = async (ticketId) => {
    if (!selectedEvent) {
      return;
    }

    if (isDemoMode) {
      setTicketReplies((items) => ({ ...items, [ticketId]: items[ticketId] || [] }));
      return;
    }

    try {
      const replies = await api.getTicketReplies(selectedEvent.id, ticketId);
      setTicketReplies((items) => ({ ...items, [ticketId]: replies }));
    } catch (error) {
      setTicketsError(error.message);
    }
  };

  const replyToTicket = async (ticket, content, audio = null) => {
    if (!selectedEvent) {
      return;
    }

    if (isDemoMode) {
      setTicketReplies((items) => ({
        ...items,
        [ticket.id]: [
          ...(items[ticket.id] || []),
          {
            id: Date.now(),
            ticket_id: ticket.id,
            from_staff_id: currentStaff?.id,
            sender: currentStaffProfile || currentStaff,
            content,
            visibility: "public",
          },
        ],
      }));
      return;
    }

    let replyContent = content;
    if (audio) {
      try {
        const transcription = await api.transcribeAudio(selectedEvent.id, {
          audio_base64: audio.audioBase64,
          audio_mime_type: audio.mimeType,
        });
        replyContent = transcription.text || content;
      } catch (error) {
        setTicketsError(error.message);
        return;
      }
    }

    try {
      const reply = await api.createTicketReply(selectedEvent.id, ticket.id, {
        content: replyContent,
        visibility: "public",
      });
      setTicketReplies((items) => ({
        ...items,
        [ticket.id]: [...(items[ticket.id] || []), reply],
      }));
    } catch (error) {
      setTicketsError(error.message);
    }
  };

  const sendChatText = async (text) => {
    if (!selectedEvent) {
      return;
    }

    const userMessage = appendChat({ from: "me", text, source: "agent_text" });
    setIsCommandLoading(true);
    setAgentError("");

    if (isDemoMode) {
      window.setTimeout(() => {
        const lowered = text.toLowerCase();
        if (lowered.includes("не знаю") || lowered.includes("вопрос")) {
          routeUnansweredQuestion(text);
          const response = {
            message: "Не нашла точный ответ в базе знаний. Передала вопрос администратору.",
          };
          appendChat({
            from: "alice",
            text: response.message,
            source: "agent_text",
          });
          playAliceAudio(response, voiceAlertsEnabled);
        } else {
          const response = {
            message: "Нашла в базе знаний: действуй по инструкции штаба и держи статус задачи актуальным.",
          };
          appendChat({
            from: "alice",
            text: response.message,
            source: "agent_text",
          });
          playAliceAudio(response, voiceAlertsEnabled);
        }
        setIsCommandLoading(false);
      }, 300);
      return;
    }

    try {
      const response = await api.sendCommand(selectedEvent.id, {
        text,
        mode: "chat",
        context: buildAgentContext(chat, userMessage),
      });
      appendChat({ from: "alice", text: response.message, source: "agent_text" });
      playAliceAudio(response, voiceAlertsEnabled);

      if (isVolunteerMode && response.action === "question_asked") {
        await routeUnansweredQuestion(text);
      }
    } catch (error) {
      const response = {
        message: "Не смогла ответить сейчас. Передала вопрос администратору.",
      };
      setAgentError(error.message);
      appendChat({
        from: "alice",
        text: response.message,
        source: "agent_text",
      });
      playAliceAudio(response, voiceAlertsEnabled);
      await routeUnansweredQuestion(text);
    } finally {
      setIsCommandLoading(false);
    }
  };

  const sendChatAudio = async ({ audioBase64, audioUrl, mimeType }) => {
    if (!selectedEvent) {
      return;
    }

    const userMessage = appendChat({
      from: "me",
      text: "Голосовое сообщение",
      source: "agent_audio",
      audioUrl,
    });
    setIsCommandLoading(true);
    setAgentError("");

    try {
      const response = isDemoMode
        ? { message: "Голосовое принято. Если вопрос останется открытым, передам администратору." }
        : await api.sendCommand(selectedEvent.id, {
            audio_base64: audioBase64,
            audio_mime_type: mimeType,
            mode: "chat",
            context: buildAgentContext(chat, userMessage),
          });
      appendChat({ from: "alice", text: response.message, source: "agent_text" });
      playAliceAudio(response, voiceAlertsEnabled);

      if (isVolunteerMode && response.action === "question_asked") {
        await routeUnansweredQuestion(response.transcript || "Голосовой вопрос");
      }
    } catch (error) {
      const response = { message: "Не смогла обработать голосовое." };
      setAgentError(error.message);
      appendChat({ from: "alice", text: response.message, source: "agent_text" });
      playAliceAudio(response, voiceAlertsEnabled);
    } finally {
      setIsCommandLoading(false);
    }
  };

  const sendCommand = async (command) => {
    if (!selectedEvent) {
      return;
    }

    const payload = command.audioBase64
      ? {
          audio_base64: command.audioBase64,
          audio_mime_type: command.mimeType,
          mode: "command",
        }
      : { text: command.text, mode: "command" };

    setAgentError("");
    setAgentResponse(null);
    setIsCommandLoading(true);

    if (isDemoMode) {
      window.setTimeout(() => {
        const response = {
          action: "ticket_created",
          message: "Демо: создала задачу и предлагаю назначить Анну.",
          suggestion: {
            reasoning: "Анна свободна и находится у входа.",
            suggested_staff_ids: [2],
            confidence: "high",
            ticket_id: 1,
          },
          ticket: DEMO_TICKETS[0],
        };
        setAgentResponse(response);
        playAliceAudio(response, voiceAlertsEnabled);
        setIsCommandLoading(false);
      }, 300);
      return;
    }

    try {
      const response = await api.sendCommand(selectedEvent.id, payload);
      setAgentResponse(response);
      playAliceAudio(response, voiceAlertsEnabled);
      refreshEventData();
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
      refreshEventData();
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

  const askTicketQuestion = async (ticket, content, audio = null) => {
    if (isDemoMode) {
      setTicketReplies((items) => ({
        ...items,
        [ticket.id]: [
          ...(items[ticket.id] || []),
          {
            id: Date.now(),
            ticket_id: ticket.id,
            from_staff_id: currentStaff?.id,
            sender: currentStaffProfile || currentStaff,
            content,
            visibility: "public",
          },
        ],
      }));
      await changeTicket(ticket.id, "waiting");
      return "Демо: проверила базу знаний и передала вопрос администратору.";
    }

    let aliceText = "Передала вопрос администратору.";
    let aliceAction = "question_asked";
    let questionText = content;
    try {
      const response = await api.sendCommand(
        selectedEvent.id,
        audio
          ? {
              audio_base64: audio.audioBase64,
              audio_mime_type: audio.mimeType,
              mode: "ticket_question",
              context: [
                {
                  role: "user",
                  text: `Контекст тикета #${ticket.id}: ${ticket.title}. ${ticket.description || ""}`,
                  source: "agent_text",
                },
              ],
            }
          : {
              text: `Вопрос по задаче #${ticket.id} "${ticket.title}": ${content}`,
              mode: "ticket_question",
              context: [
                {
                  role: "user",
                  text: `Контекст тикета #${ticket.id}: ${ticket.title}. ${ticket.description || ""}`,
                  source: "agent_text",
                },
              ],
            },
      );
      aliceText = response.message || aliceText;
      aliceAction = response.action || aliceAction;
      questionText = audio ? response.transcript || content : content;
    } catch {
      // Keep the ticket thread usable even when Alice is temporarily unavailable.
    }

    const normalizedQuestion = questionText.trim() || content;
    const shouldShowAliceInThread = aliceAction === "answered" && aliceText.trim();

    try {
      await api.createTicketReply(selectedEvent.id, ticket.id, {
        content: normalizedQuestion,
        visibility: "public",
      });
      if (shouldShowAliceInThread) {
        await api.createTicketReply(selectedEvent.id, ticket.id, {
          content: aliceText,
          visibility: "public",
        });
      }
      await loadTicketReplies(ticket.id);
    } catch (error) {
      setTicketsError(error.message);
    }

    await changeTicket(ticket.id, "waiting");
    return aliceText;
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
        onSubmit={login}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[#f3f0ff] text-slate-950">
      <div className="mx-auto flex min-h-screen max-w-md flex-col bg-white">
        <header className="border-b border-violet-100 px-4 py-3">
          <p className="text-xs font-semibold uppercase text-violet-700">
            {APP_NAME}
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
          {activeTab === "chat" ? (
            <div className="space-y-3">
              {agentError ? (
                <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
                  {agentError}
                </p>
              ) : null}
              <ChatPanel
                broadcastMode={isAdminMode && broadcastMode}
                chat={chat}
                disabled={!selectedEvent}
                isLoading={isCommandLoading}
                mode={isAdminMode ? "admin" : "volunteer"}
                replyTarget={isAdminMode ? replyTarget : null}
                onBroadcastToggle={isAdminMode ? () => setBroadcastMode((value) => !value) : undefined}
                onCancelReply={() => setReplyTarget(null)}
                onSendBroadcast={isAdminMode ? sendBroadcastMessage : undefined}
                onReply={isAdminMode ? handleChatReply : undefined}
                onSendAudio={sendChatAudio}
                onSendText={sendChatText}
              />
            </div>
          ) : activeTab === "event" ? (
            <EventSetup
              event={selectedEvent}
              staff={staff}
              onChanged={refreshEventData}
              onEventCreated={eventCreated}
            />
          ) : activeTab === "tickets" ? (
            <TicketTable
              agentError={agentError}
              agentResponse={agentResponse}
              error={ticketsError}
              filters={ticketFilters}
              isAgentLoading={isCommandLoading}
              isConfirming={isConfirming}
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
              replies={ticketReplies}
              onFilterChange={(nextFilters) =>
                setTicketFilters((filters) => ({ ...filters, ...nextFilters }))
              }
              onAgentConfirm={(ticketId, staffIds) =>
                confirmSuggestion(ticketId, staffIds, true)
              }
              onAgentReject={(ticketId) => confirmSuggestion(ticketId, [], false)}
              onCommandSubmit={sendCommand}
              onQuestion={askTicketQuestion}
              onReply={replyToTicket}
              onThreadOpen={loadTicketReplies}
              onStatusChange={changeTicket}
            />
          ) : activeTab === "settings" ? (
            <ProfilePanel
              context={myContext}
              currentStaff={currentStaffProfile || currentStaff}
              event={selectedEvent}
              onLogout={logout}
              onVoiceAlertsChange={setVoiceAlertsEnabled}
              voiceAlertsEnabled={voiceAlertsEnabled}
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
          className={`fixed bottom-0 left-1/2 z-20 grid w-full max-w-md -translate-x-1/2 border-t border-violet-100 bg-white ${
            navGridClass(visibleTabs.length)
          }`}
        >
          {visibleTabs.map((tab) => (
            <button
              className={`px-2 py-3 text-xs font-medium ${
                activeTab === tab.id ? "text-violet-700" : "text-slate-500"
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
