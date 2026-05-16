import { useEffect, useRef, useState } from "react";
import AliceResponse from "./AliceResponse.jsx";
import CommandBar from "./CommandBar.jsx";

const audioTypes = [
  "audio/ogg;codecs=opus",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
];

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.readAsDataURL(blob);
  });
}

const priorityStyles = {
  low: "bg-slate-100 text-slate-600",
  medium: "bg-sky-100 text-sky-700",
  high: "bg-amber-100 text-amber-700",
  critical: "bg-red-100 text-red-700",
};

const statusLabels = {
  new: "Новый",
  in_progress: "В работе",
  waiting: "Ожидает",
  resolved: "Решён",
  closed: "Закрыт",
};

const statusOrder = {
  new: 0,
  waiting: 1,
  in_progress: 2,
  resolved: 3,
  closed: 4,
};

const statusStyles = {
  new: "border-slate-200 bg-white",
  in_progress: "border-sky-200 bg-sky-50",
  waiting: "border-amber-200 bg-amber-50",
  resolved: "border-emerald-200 bg-emerald-50",
  closed: "border-slate-200 bg-slate-50",
};

const statusOptions = [
  { value: "", label: "Все" },
  { value: "new", label: "Новые" },
  { value: "in_progress", label: "В работе" },
  { value: "waiting", label: "Ожидают" },
  { value: "resolved", label: "Решены" },
];

const responseOptions = [
  { status: "in_progress", label: "ОК, взял" },
  { status: "waiting", label: "Есть вопрос" },
  { status: "resolved", label: "Готово" },
];

export default function TicketTable({
  agentError,
  agentResponse,
  isAgentLoading = false,
  isConfirming = false,
  error,
  filters,
  isLoading,
  mode = "admin",
  onFilterChange,
  onAgentConfirm,
  onAgentReject,
  onCommandSubmit,
  onReply,
  onQuestion,
  onThreadOpen,
  onStatusChange,
  replies = {},
  staff,
  tickets,
}) {
  const [assignments, setAssignments] = useState({});
  const [openQuestionTicketId, setOpenQuestionTicketId] = useState(null);
  const [openThreadTicketId, setOpenThreadTicketId] = useState(null);
  const [questionAnswers, setQuestionAnswers] = useState({});
  const [recordingTicketId, setRecordingTicketId] = useState(null);
  const [recordingThreadTicketId, setRecordingThreadTicketId] = useState(null);
  const [questions, setQuestions] = useState({});
  const [threadVoiceStatus, setThreadVoiceStatus] = useState({});
  const [threadReplies, setThreadReplies] = useState({});
  const chunksRef = useRef([]);
  const onThreadOpenRef = useRef(onThreadOpen);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);

  useEffect(() => {
    onThreadOpenRef.current = onThreadOpen;
  }, [onThreadOpen]);

  const toggleAssignee = (ticketId, staffId) => {
    setAssignments((items) => {
      const selected = new Set(items[ticketId] || []);

      if (selected.has(staffId)) {
        selected.delete(staffId);
      } else {
        selected.add(staffId);
      }

      return { ...items, [ticketId]: Array.from(selected) };
    });
  };

  const stopQuestionRecording = () => {
    recorderRef.current?.stop();
  };

  const stopThreadRecording = () => {
    recorderRef.current?.stop();
  };

  const startThreadVoiceReply = async (ticket) => {
    if (!window.isSecureContext) {
      setThreadVoiceStatus((items) => ({
        ...items,
        [ticket.id]: "Голосовой ответ требует localhost или HTTPS.",
      }));
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setThreadVoiceStatus((items) => ({
        ...items,
        [ticket.id]: "Запись аудио не поддерживается этим браузером.",
      }));
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = audioTypes.find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});

      chunksRef.current = [];
      recorderRef.current = recorder;
      streamRef.current = stream;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        setRecordingThreadTicketId(null);
        stream.getTracks().forEach((track) => track.stop());

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        const audioBase64 = await blobToBase64(blob);
        setThreadVoiceStatus((items) => ({
          ...items,
          [ticket.id]: "Распознаю голосовой ответ...",
        }));
        await onReply(ticket, "Голосовой ответ", {
          audioBase64,
          mimeType: blob.type,
        });
        setThreadVoiceStatus((items) => ({
          ...items,
          [ticket.id]: "Ответ отправлен.",
        }));
        setOpenThreadTicketId(ticket.id);
      };

      recorder.start();
      setRecordingThreadTicketId(ticket.id);
      setThreadVoiceStatus((items) => ({
        ...items,
        [ticket.id]: "Идёт запись ответа.",
      }));
    } catch (error) {
      setRecordingThreadTicketId(null);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      setThreadVoiceStatus((items) => ({
        ...items,
        [ticket.id]:
          error.name === "NotAllowedError"
            ? "Браузер не дал доступ к микрофону."
            : "Не удалось начать запись ответа.",
      }));
    }
  };

  const startQuestionVoiceInput = async (ticket) => {
    if (!window.isSecureContext) {
      setQuestionAnswers((items) => ({
        ...items,
        [ticket.id]: "Голосовой ввод требует localhost или HTTPS.",
      }));
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setQuestionAnswers((items) => ({
        ...items,
        [ticket.id]: "Запись аудио не поддерживается этим браузером.",
      }));
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = audioTypes.find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});

      chunksRef.current = [];
      recorderRef.current = recorder;
      streamRef.current = stream;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        setRecordingTicketId(null);
        stream.getTracks().forEach((track) => track.stop());

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        const audioBase64 = await blobToBase64(blob);
        setQuestionAnswers((items) => ({
          ...items,
          [ticket.id]: "Алиса слушает голосовой вопрос...",
        }));
        const answer = await onQuestion(ticket, "Голосовой вопрос", {
          audioBase64,
          mimeType: blob.type,
        });
        setQuestionAnswers((items) => ({
          ...items,
          [ticket.id]: answer || "Передала вопрос администратору.",
        }));
        setOpenThreadTicketId(ticket.id);
      };

      recorder.start();
      setRecordingTicketId(ticket.id);
      setQuestionAnswers((items) => ({
        ...items,
        [ticket.id]: "Идёт запись вопроса.",
      }));
    } catch (error) {
      setRecordingTicketId(null);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      setQuestionAnswers((items) => ({
        ...items,
        [ticket.id]:
          error.name === "NotAllowedError"
            ? "Браузер не дал доступ к микрофону."
            : "Не удалось начать запись вопроса.",
      }));
    }
  };

  const sendQuestion = async (event, ticket) => {
    event.preventDefault();
    const content = (questions[ticket.id] || "").trim();

    if (!content) {
      return;
    }

    setQuestionAnswers((items) => ({ ...items, [ticket.id]: "Алиса проверяет базу знаний..." }));
    const answer = await onQuestion(ticket, content);
    setQuestionAnswers((items) => ({
      ...items,
      [ticket.id]: answer || "Передала вопрос администратору.",
    }));
    setQuestions((items) => ({ ...items, [ticket.id]: "" }));
    setOpenQuestionTicketId(null);
    setOpenThreadTicketId(ticket.id);
  };

  const sendThreadReply = async (event, ticket) => {
    event.preventDefault();
    const content = (threadReplies[ticket.id] || "").trim();

    if (!content) {
      return;
    }

    await onReply(ticket, content);
    setThreadReplies((items) => ({ ...items, [ticket.id]: "" }));
    setOpenThreadTicketId(ticket.id);
  };

  const toggleThread = (ticketId) => {
    const nextId = openThreadTicketId === ticketId ? null : ticketId;
    setOpenThreadTicketId(nextId);
    if (nextId) {
      onThreadOpen?.(nextId);
    }
  };

  useEffect(() => {
    if (!openThreadTicketId) {
      return undefined;
    }

    onThreadOpenRef.current?.(openThreadTicketId);
    const timer = window.setInterval(() => {
      onThreadOpenRef.current?.(openThreadTicketId);
    }, 5000);

    return () => window.clearInterval(timer);
  }, [openThreadTicketId]);

  const personName = (staffId, fallback = "Участник") =>
    staff.find((person) => person.id === staffId)?.name || fallback;

  const isInitialLoading = isLoading && tickets.length === 0;
  const visibleTickets =
    mode === "admin" && filters.status
      ? tickets.filter((ticket) => ticket.status === filters.status)
      : tickets;
  const orderedTickets = visibleTickets
    .map((ticket, index) => ({ index, ticket }))
    .sort((left, right) => {
      const leftOrder = statusOrder[left.ticket.status] ?? 99;
      const rightOrder = statusOrder[right.ticket.status] ?? 99;

      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }

      return left.index - right.index;
    })
    .map((item) => item.ticket);

  return (
    <div className="space-y-4">
      {mode === "admin" ? (
        <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-950">Новая команда</h2>
          <CommandBar
            disabled={isAgentLoading || isConfirming}
            onSubmit={onCommandSubmit}
          />
          {isAgentLoading ? (
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500">
              Алиса разбирает команду...
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
            onConfirm={onAgentConfirm}
            onReject={onAgentReject}
          />
        </section>
      ) : null}

      {mode === "admin" ? (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {statusOptions.map((option) => (
            <button
              className={`h-9 shrink-0 rounded-full px-3 text-xs font-medium ${
                filters.status === option.value
                  ? "bg-violet-700 text-white"
                  : "bg-slate-100 text-slate-600"
              }`}
              key={option.value}
              type="button"
              onClick={() => onFilterChange({ status: option.value })}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
      ) : null}

      {isInitialLoading ? (
        <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="text-sm text-slate-600">Загружаем тикеты...</p>
        </section>
      ) : null}

      {!isInitialLoading && tickets.length === 0 ? (
        <section className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
          <p className="text-sm text-slate-600">Активных тикетов пока нет.</p>
        </section>
      ) : null}

      {orderedTickets.map((ticket) => {
        const selectedStaff = assignments[ticket.id] || [];

        return (
        <article
          className={`rounded-lg border p-4 shadow-sm ${
            statusStyles[ticket.status] || statusStyles.new
          }`}
          key={ticket.id}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">
                {ticket.title}
              </h2>
              <p className="mt-1 text-xs font-medium text-slate-500">
                {statusLabels[ticket.status] || ticket.status}
              </p>
            </div>
            <span
              className={`rounded-full px-2 py-1 text-xs font-medium ${
                priorityStyles[ticket.priority] || priorityStyles.medium
              }`}
            >
              {ticket.priority}
            </span>
          </div>

          {ticket.description ? (
            <p className="mt-3 text-sm text-slate-600">{ticket.description}</p>
          ) : null}

          {(ticket.assignments || []).length > 0 ? (
            <p className="mt-3 text-xs text-slate-500">
              Исполнители:{" "}
              {ticket.assignments
                .map((assignment) => assignment.staff?.name)
                .filter(Boolean)
                .join(", ")}
            </p>
          ) : null}

          <button
            className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700"
            type="button"
            onClick={() => toggleThread(ticket.id)}
          >
            {openThreadTicketId === ticket.id ? "Скрыть обсуждение" : "Обсуждение"}
            {(replies[ticket.id] || []).length > 0 ? ` · ${replies[ticket.id].length}` : ""}
          </button>

          {openThreadTicketId === ticket.id ? (
            <section className="mt-3 space-y-2 rounded-lg border border-slate-200 bg-white p-3">
              {(replies[ticket.id] || []).length > 0 ? (
                replies[ticket.id].map((reply) => (
                  <div
                    className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700"
                    key={reply.id}
                  >
                    <div className="mb-1 font-semibold text-slate-900">
                      {reply.sender?.name || personName(reply.from_staff_id)}
                    </div>
                    <div className="whitespace-pre-line">{reply.content}</div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-500">Сообщений по задаче пока нет.</p>
              )}
              {mode === "admin" ? (
                <div className="space-y-2">
                  <form className="space-y-2" onSubmit={(event) => sendThreadReply(event, ticket)}>
                    <input
                      className="h-10 w-full min-w-0 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-violet-600"
                      placeholder="Ответ по задаче"
                      value={threadReplies[ticket.id] || ""}
                      onChange={(event) =>
                        setThreadReplies((items) => ({
                          ...items,
                          [ticket.id]: event.target.value,
                        }))
                      }
                    />
                    <div className="grid grid-cols-[1fr_104px] gap-2">
                      <button
                        className={`h-11 rounded-lg text-sm font-semibold text-white ${
                          recordingThreadTicketId === ticket.id
                            ? "bg-red-600"
                            : "bg-violet-700"
                        } disabled:opacity-60`}
                        disabled={recordingThreadTicketId !== null && recordingThreadTicketId !== ticket.id}
                        type="button"
                        onClick={() =>
                          recordingThreadTicketId === ticket.id
                            ? stopThreadRecording()
                            : startThreadVoiceReply(ticket)
                        }
                      >
                        {recordingThreadTicketId === ticket.id ? "Стоп" : "Голос"}
                      </button>
                      <button
                        className="h-11 rounded-lg border border-violet-200 bg-white text-xs font-semibold text-violet-700 disabled:opacity-60"
                        disabled={!(threadReplies[ticket.id] || "").trim()}
                        type="submit"
                      >
                        Ответить
                      </button>
                    </div>
                  </form>
                  {threadVoiceStatus[ticket.id] ? (
                    <p className="text-xs text-slate-500">{threadVoiceStatus[ticket.id]}</p>
                  ) : null}
                </div>
              ) : null}
            </section>
          ) : null}

          {mode === "volunteer" ? (
            <>
              <div className="mt-4 grid grid-cols-3 gap-2">
                {responseOptions.map((option) => (
                  <button
                    className={`h-10 rounded-lg border text-xs font-medium ${
                      ticket.status === option.status
                        ? "border-violet-700 bg-violet-700 text-white"
                        : "border-slate-300 bg-white text-slate-700"
                    }`}
                    key={option.status}
                    type="button"
                    onClick={() => {
                      if (option.status === "waiting") {
                        setOpenQuestionTicketId(
                          openQuestionTicketId === ticket.id ? null : ticket.id,
                        );
                        return;
                      }

                      onStatusChange(ticket.id, option.status);
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              {openQuestionTicketId === ticket.id ? (
                <form className="mt-3 space-y-2" onSubmit={(event) => sendQuestion(event, ticket)}>
                  <textarea
                    className="min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-600"
                    placeholder="Что нужно уточнить?"
                    value={questions[ticket.id] || ""}
                    onChange={(event) =>
                      setQuestions((items) => ({
                        ...items,
                        [ticket.id]: event.target.value,
                      }))
                    }
                  />
                  <div className="grid grid-cols-[1fr_120px] gap-2">
                    <button
                      className={`h-11 rounded-lg text-sm font-semibold text-white ${
                        recordingTicketId === ticket.id
                          ? "bg-red-600"
                          : "bg-violet-700"
                      } disabled:opacity-60`}
                      disabled={recordingTicketId !== null && recordingTicketId !== ticket.id}
                      type="button"
                      onClick={() =>
                        recordingTicketId === ticket.id
                          ? stopQuestionRecording()
                          : startQuestionVoiceInput(ticket)
                      }
                    >
                      {recordingTicketId === ticket.id ? "Стоп" : "Голос"}
                    </button>
                    <button
                      className="h-11 rounded-lg border border-violet-200 bg-white px-2 text-xs font-semibold text-violet-700 disabled:opacity-60"
                      disabled={!(questions[ticket.id] || "").trim()}
                      type="submit"
                    >
                      Отправить вопрос
                    </button>
                  </div>
                </form>
              ) : null}
              {questionAnswers[ticket.id] ? (
                <div className="mt-3 rounded-lg border border-violet-100 bg-violet-50 p-3 text-xs text-violet-800">
                  {questionAnswers[ticket.id]}
                </div>
              ) : null}
            </>
          ) : (
            <div className="mt-4 grid grid-cols-2 gap-2">
              <button
                className="h-10 rounded-lg border border-slate-300 text-xs font-medium text-slate-700"
                type="button"
                onClick={() => onStatusChange(ticket.id, "in_progress")}
              >
                В работу
              </button>
              <button
                className="h-10 rounded-lg border border-slate-300 text-xs font-medium text-slate-700"
                type="button"
                onClick={() => onStatusChange(ticket.id, "resolved")}
              >
                Решён
              </button>
            </div>
          )}

          {mode === "admin" && staff.length > 0 ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">
                Назначить вручную
              </summary>
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap gap-2">
                  {staff.map((person) => (
                    <button
                      className={`rounded-full px-3 py-1 text-xs font-medium ${
                        selectedStaff.includes(person.id)
                          ? "bg-violet-700 text-white"
                          : "bg-slate-100 text-slate-600"
                      }`}
                      key={person.id}
                      type="button"
                      onClick={() => toggleAssignee(ticket.id, person.id)}
                    >
                      {person.name}
                    </button>
                  ))}
                </div>
                <button
                  className="h-10 w-full rounded-lg bg-violet-700 text-xs font-semibold text-white disabled:opacity-60"
                  disabled={selectedStaff.length === 0}
                  type="button"
                  onClick={() => onStatusChange(ticket.id, null, selectedStaff)}
                >
                  Назначить выбранных
                </button>
              </div>
            </details>
          ) : null}
        </article>
      );
      })}
    </div>
  );
}
