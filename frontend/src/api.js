const API_BASE = import.meta.env?.VITE_API_BASE || "http://localhost:8000";

export async function postChat(message, userId) {
  const payload = {
    message,
    user_id: userId ? Number(userId) : null
  };
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.error || "Chat request failed");
  }
  return response.json();
}

export async function getRunEvents(runId) {
  const response = await fetch(`${API_BASE}/api/runs/${runId}`);
  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.error || "Run fetch failed");
  }
  const payload = await response.json();
  const events = Array.isArray(payload.events) ? payload.events : [];
  events.sort((a, b) => (a.step_index || 0) - (b.step_index || 0));
  return { ...payload, events };
}
