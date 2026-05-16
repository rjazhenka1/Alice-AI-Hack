import { useRef, useState } from "react";

const audioTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.readAsDataURL(blob);
  });
}

function formatTime(value) {
  if (!value) {
    return "";
  }

  return new Date(value).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ChatPanel({
  chat,
  disabled = false,
  isLoading = false,
  mode = "volunteer",
  onSendAudio,
  onSendText,
}) {
  const [isRecording, setIsRecording] = useState(false);
  const [text, setText] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("");
  const chunksRef = useRef([]);
  const recorderRef = useRef(null);

  const submit = (event) => {
    event.preventDefault();
    const value = text.trim();

    if (!value) {
      return;
    }

    onSendText(value);
    setText("");
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
  };

  const startRecording = async () => {
    setVoiceStatus("");

    if (!window.isSecureContext) {
      setVoiceStatus("Голосовой ввод требует localhost или HTTPS.");
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setVoiceStatus("Запись аудио не поддерживается этим браузером.");
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

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = async () => {
        setIsRecording(false);
        stream.getTracks().forEach((track) => track.stop());

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        const audioBase64 = await blobToBase64(blob);
        onSendAudio({ audioBase64, mimeType: blob.type });
        setVoiceStatus("Голосовое отправлено Алисе.");
      };

      recorder.start();
      setIsRecording(true);
      setVoiceStatus("Идёт запись.");
    } catch (error) {
      setIsRecording(false);
      setVoiceStatus(
        error.name === "NotAllowedError"
          ? "Браузер не дал доступ к микрофону."
          : "Не удалось начать запись.",
      );
    }
  };

  return (
    <section className="flex min-h-[calc(100vh-180px)] flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto pb-4">
        {mode === "admin" ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Вопросы волонтёров, которые Алиса не закрыла сама, появятся здесь.
          </div>
        ) : null}

        {chat.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
            Напиши Алисе вопрос по мероприятию или текущей задаче.
          </div>
        ) : null}

        {chat.map((message) => (
          <article
            className={`max-w-[88%] rounded-lg px-3 py-2 text-sm ${
              message.from === "me"
                ? "ml-auto bg-slate-950 text-white"
                : message.from === "admin"
                  ? "bg-amber-50 text-amber-900"
                  : "bg-slate-100 text-slate-900"
            }`}
            key={message.id}
          >
            <p>{message.text}</p>
            {message.createdAt ? (
              <p
                className={`mt-1 text-[11px] ${
                  message.from === "me" ? "text-slate-300" : "text-slate-500"
                }`}
              >
                {formatTime(message.createdAt)}
              </p>
            ) : null}
          </article>
        ))}
      </div>

      <form
        className="sticky bottom-16 -mx-4 border-t border-slate-200 bg-white px-4 py-3"
        onSubmit={submit}
      >
        <div className="grid grid-cols-[1fr_48px] gap-2">
          <input
            className="h-12 min-w-0 rounded-lg border border-slate-300 px-3 text-base outline-none focus:border-teal-600"
            disabled={disabled}
            placeholder="Спросить Алису"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <button
            className={`h-12 rounded-lg text-sm font-semibold text-white disabled:opacity-60 ${
              text.trim() ? "bg-slate-950" : isRecording ? "bg-red-600" : "bg-teal-700"
            }`}
            disabled={disabled || isLoading}
            type={text.trim() ? "submit" : "button"}
            onClick={text.trim() ? undefined : isRecording ? stopRecording : startRecording}
          >
            {text.trim() ? "→" : isRecording ? "■" : "●"}
          </button>
        </div>
        {voiceStatus || isLoading ? (
          <p className="mt-2 text-xs text-slate-500">
            {isLoading ? "Алиса отвечает..." : voiceStatus}
          </p>
        ) : null}
      </form>
    </section>
  );
}
