const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const token = localStorage.getItem("eventops_token");
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.status === 204 ? null : response.json();
}

export const api = {
  login: (telegramId) =>
    request("/auth/login", {
      method: "POST",
      body: { telegram_id: telegramId },
    }),
  getEvents: () => request("/events"),
  getStaff: (eventId) => request(`/events/${eventId}/staff`),
  getTickets: (eventId) => request(`/events/${eventId}/tickets`),
  getMessages: (eventId) => request(`/events/${eventId}/messages`),
  sendCommand: (eventId, text) =>
    request(`/events/${eventId}/agent/command`, {
      method: "POST",
      body: { text },
    }),
  confirmSuggestion: (eventId, payload) =>
    request(`/events/${eventId}/agent/confirm`, {
      method: "POST",
      body: payload,
    }),
};
