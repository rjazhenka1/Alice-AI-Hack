import { create } from "zustand";

const savedEventId = localStorage.getItem("eventops_event_id") || "";
const savedToken = localStorage.getItem("eventops_token") || "";

export const useAppStore = create((set) => ({
  currentStaff: null,
  eventId: savedEventId,
  token: savedToken,

  setCurrentStaff: (currentStaff) => set({ currentStaff }),
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
    localStorage.removeItem("eventops_token");
    set({ currentStaff: null, eventId: "", token: "" });
  },
}));
