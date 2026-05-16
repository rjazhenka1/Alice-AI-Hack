const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function withQuery(path, params = {}) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });

  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

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
    let detail = message;

    try {
      detail = JSON.parse(message).detail || message;
    } catch {
      detail = message;
    }

    throw new Error(detail || `Request failed: ${response.status}`);
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
  createEvent: (payload) =>
    request("/events", {
      method: "POST",
      body: payload,
    }),
  getRoles: (eventId) => request(`/events/${eventId}/roles`),
  createRole: (eventId, payload) =>
    request(`/events/${eventId}/roles`, {
      method: "POST",
      body: payload,
    }),
  getZones: (eventId) => request(`/events/${eventId}/zones`),
  createZone: (eventId, payload) =>
    request(`/events/${eventId}/zones`, {
      method: "POST",
      body: payload,
    }),
  getStaff: (eventId) => request(`/events/${eventId}/staff`),
  createStaff: (eventId, payload) =>
    request(`/events/${eventId}/staff`, {
      method: "POST",
      body: payload,
    }),
  updateStaff: (eventId, staffId, payload) =>
    request(`/events/${eventId}/staff/${staffId}`, {
      method: "PATCH",
      body: payload,
    }),
  getStaffContext: (eventId, staffId) =>
    request(`/events/${eventId}/staff/${staffId}/context`),
  getTickets: (eventId, filters = {}) =>
    request(withQuery(`/events/${eventId}/tickets`, filters)),
  createTicket: (eventId, payload) =>
    request(`/events/${eventId}/tickets`, {
      method: "POST",
      body: payload,
    }),
  updateTicket: (eventId, ticketId, payload) =>
    request(`/events/${eventId}/tickets/${ticketId}`, {
      method: "PATCH",
      body: payload,
    }),
  assignTicket: (eventId, ticketId, staffIds) =>
    request(`/events/${eventId}/tickets/${ticketId}/assign`, {
      method: "POST",
      body: { staff_ids: staffIds },
    }),
  confirmAssignment: (eventId, ticketId, assignmentId, confirmed) =>
    request(`/events/${eventId}/tickets/${ticketId}/assignments/${assignmentId}`, {
      method: "PATCH",
      body: { confirmed },
    }),
  getMessages: (eventId, filters = {}) =>
    request(withQuery(`/events/${eventId}/messages`, filters)),
  createMessage: (eventId, payload) =>
    request(`/events/${eventId}/messages`, {
      method: "POST",
      body: payload,
    }),
  markMessageRead: (eventId, messageId) =>
    request(`/events/${eventId}/messages/${messageId}/read`, {
      method: "PATCH",
    }),
  sendCommand: (eventId, payload) =>
    request(`/events/${eventId}/agent/command`, {
      method: "POST",
      body: payload,
    }),
  confirmSuggestion: (eventId, payload) =>
    request(`/events/${eventId}/agent/confirm`, {
      method: "POST",
      body: payload,
    }),
};
