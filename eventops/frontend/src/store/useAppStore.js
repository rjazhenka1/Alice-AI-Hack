import { create } from "zustand";

const savedEventId = localStorage.getItem("eventops_event_id") || "";
const savedStaff = localStorage.getItem("eventops_current_staff");
const savedToken = localStorage.getItem("eventops_token") || "";

function parseSavedStaff(value) {
  try {
    return value ? JSON.parse(value) : null;
  } catch {
    localStorage.removeItem("eventops_current_staff");
    return null;
  }
}

export const useAppStore = create((set) => ({
  currentStaff: parseSavedStaff(savedStaff),
  eventId: savedEventId,
  token: savedToken,

  setCurrentStaff: (currentStaff) => {
    if (currentStaff) {
      localStorage.setItem("eventops_current_staff", JSON.stringify(currentStaff));
    } else {
      localStorage.removeItem("eventops_current_staff");
    }

    set({ currentStaff });
  },
  setEventId: (eventId) => {
    const nextEventId = String(eventId);
    localStorage.setItem("eventops_event_id", nextEventId);
    set({ eventId: nextEventId });
  },
  setToken: (token) => {
    localStorage.setItem("eventops_token", token);
    set({ token });
  },
  logout: () => {
    localStorage.removeItem("eventops_event_id");
    localStorage.removeItem("eventops_current_staff");
    localStorage.removeItem("eventops_token");
    set({ currentStaff: null, eventId: "", token: "" });
  },
}));
