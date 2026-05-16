import { useRef, useState } from "react";

const commandTypes = [
  { id: "incident", label: "Инцидент" },
  { id: "task", label: "Задача" },
  { id: "question", label: "Вопрос" },
];

const audioTypes = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onloadend = () => resolve(reader.result.split(",")[1]);
    reader.readAsDataURL(blob);
  });
}

export default function CommandBar({ disabled = false, onSubmit }) {
  const [commandType, setCommandType] = useState("incident");
  const [isRecording, setIsRecording] = useState(false);
  const [text, setText] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("");
  const chunksRef = useRef([]);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);

  const submit = (event) => {
    event.preventDefault();
    const command = text.trim();

    if (!command) {
      return;
    }

    onSubmit({ type: commandType, text: command });
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
      streamRef.current = stream;

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

        onSubmit({
          type: commandType,
          audioBase64,
          mimeType: blob.type,
        });
        setVoiceStatus("Аудио записано и готово к отправке Алисе.");
      };

      recorder.start();
      setIsRecording(true);
      setVoiceStatus("Идёт запись. Нажми Стоп, когда закончишь.");
    } catch (error) {
      setIsRecording(false);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      setVoiceStatus(
        error.name === "NotAllowedError"
          ? "Браузер не дал доступ к микрофону."
          : "Не удалось начать запись аудио.",
      );
    }
  };

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="grid grid-cols-3 gap-2">
        {commandTypes.map((type) => (
          <button
            className={`rounded-md border px-3 py-2 text-sm font-medium ${
              commandType === type.id
                ? "border-teal-600 bg-teal-50 text-teal-700"
                : "border-slate-200 text-slate-600"
            }`}
            key={type.id}
            type="button"
            onClick={() => setCommandType(type.id)}
          >
            {type.label}
          </button>
        ))}
      </div>

      <textarea
        className="min-h-36 w-full rounded-lg border border-slate-300 px-3 py-3 text-base outline-none focus:border-teal-600"
        placeholder="На регистрации очередь, нужны люди"
        disabled={disabled}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />

      <div className="grid grid-cols-[96px_1fr] gap-2">
        <button
          className="h-12 rounded-lg border border-slate-300 text-sm font-medium text-slate-700 disabled:opacity-60"
          disabled={disabled && !isRecording}
          type="button"
          onClick={isRecording ? stopRecording : startRecording}
        >
          {isRecording ? "Стоп" : "Голос"}
        </button>
        <button
          className="h-12 rounded-lg bg-slate-950 text-sm font-semibold text-white disabled:opacity-60"
          disabled={disabled || !text.trim()}
          type="submit"
        >
          Отправить
        </button>
      </div>

      {voiceStatus ? (
        <p className="text-sm text-slate-500">{voiceStatus}</p>
      ) : null}
    </form>
  );
}
