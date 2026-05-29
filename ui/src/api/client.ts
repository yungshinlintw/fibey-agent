export type CuMode = "none" | "basic" | "work_order";
export type FoundryIqMode = "minimal" | "standard";

export interface FileAttachment {
  name: string;
  type: string;
  dataUrl: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: FileAttachment[];
  warning?: string;
}

export interface ActivityEvent {
  id: string;
  tool: string;
  call_id?: string;
  status: "pending" | "running" | "complete" | "error";
  detail: string;
  timestamp: number;
  args?: string;
  result?: string;
}

export interface StreamCallbacks {
  onDelta: (content: string) => void;
  onActivity: (event: Omit<ActivityEvent, "id" | "timestamp">) => void;
  onWarning: (message: string) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

export async function sendMessage(
  message: string,
  sessionId: string,
  callbacks: StreamCallbacks,
  attachments?: FileAttachment[],
  cuMode: CuMode = "none",
  foundryIqMode?: FoundryIqMode
): Promise<void> {
  const body: Record<string, unknown> = { message, session_id: sessionId, cu_mode: cuMode };
  if (foundryIqMode) {
    body.foundry_iq_mode = foundryIqMode;
  }
  if (attachments && attachments.length > 0) {
    body.attachments = attachments.map((a) => ({
      name: a.name,
      type: a.type,
      data_url: a.dataUrl,
    }));
  }

  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    callbacks.onError(`Request failed: ${response.status}`);
    callbacks.onDone();
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError("No response body");
    callbacks.onDone();
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const raw = line.slice(6);

        if (currentEvent === "done" || raw === "[DONE]") {
          callbacks.onDone();
          return;
        }

        try {
          const data = JSON.parse(raw) as Record<string, string>;
          switch (currentEvent) {
            case "delta":
              callbacks.onDelta(data["content"] ?? "");
              break;
            case "warning":
              callbacks.onWarning(data["content"] ?? "");
              break;
            case "activity":
              callbacks.onActivity({
                tool: data["tool"] ?? "",
                call_id: data["call_id"],
                status: (data["status"] ?? "running") as ActivityEvent["status"],
                detail: data["detail"] ?? "",
                args: data["args"],
                result: data["result"],
              });
              break;
            case "error":
              callbacks.onError(data["message"] ?? "Unknown error");
              break;
          }
        } catch {
          // Skip malformed JSON
        }

        currentEvent = "";
      }
    }
  }

  callbacks.onDone();
}

export async function resetSession(sessionId: string): Promise<void> {
  await fetch("/api/sessions/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export interface Features {
  content_understanding: boolean;
  cu_modes: CuMode[];
  foundry_iq_cu_demo: boolean;
}

export async function fetchFeatures(): Promise<Features> {
  try {
    const response = await fetch("/api/features");
    if (!response.ok) return { content_understanding: false, cu_modes: ["none"], foundry_iq_cu_demo: false };
    return (await response.json()) as Features;
  } catch {
    return { content_understanding: false, cu_modes: ["none"], foundry_iq_cu_demo: false };
  }
}
