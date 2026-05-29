import { useState, useRef, useCallback } from "react";
import {
  type ChatMessage,
  type ActivityEvent,
  type FileAttachment,
  type CuMode,
  type FoundryIqMode,
  sendMessage,
} from "../api/client";

let messageIdCounter = 0;
function nextMessageId(): string {
  return `msg-${++messageIdCounter}`;
}

let activityIdCounter = 0;
function nextActivityId(): string {
  return `act-${++activityIdCounter}`;
}

/** Map tool names to their parent skill */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activities, setActivities] = useState<ActivityEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const sessionIdRef = useRef(crypto.randomUUID());
  const assistantIdRef = useRef<string>("");

  const send = useCallback(async (text: string, attachments?: FileAttachment[], cuMode: CuMode = "none", foundryIqMode?: FoundryIqMode) => {
    if ((!text.trim() && (!attachments || attachments.length === 0)) || isStreaming) return;

    const userMsg: ChatMessage = {
      id: nextMessageId(),
      role: "user",
      content: text,
      attachments,
    };

    const assistantMsg: ChatMessage = {
      id: nextMessageId(),
      role: "assistant",
      content: "",
    };
    assistantIdRef.current = assistantMsg.id;

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    // Clear previous activities for this turn
    setActivities([]);

    await sendMessage(text, sessionIdRef.current, {
      onDelta(content) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantIdRef.current
              ? { ...m, content: m.content + content }
              : m
          )
        );
      },
      onActivity(event) {
        const activity: ActivityEvent = {
          ...event,
          id: nextActivityId(),
          timestamp: Date.now(),
        };

        setActivities((prev) => {
          const updated = [...prev];

          // Update existing activity for same call_id (or tool if no call_id)
          const matchKey = event.call_id || event.tool;
          
          // First, try to find by call_id if present (most specific match)
          let existing = event.call_id
            ? updated.findIndex((a) => a.call_id === event.call_id)
            : -1;
          
          // If not found by call_id, try by tool name (but only update non-complete activities)
          if (existing < 0) {
            existing = updated.findIndex(
              (a) => (a.call_id || a.tool) === matchKey && a.status !== "complete"
            );
          }
          
          if (existing >= 0) {
            // Merge: prefer newer args if present, keep existing if not
            updated[existing] = {
              ...updated[existing],
              ...activity,
              args: activity.args || updated[existing]?.args,
              result: activity.result || updated[existing]?.result,
            };
            return updated;
          }
          
          // Only create new activity if it's a fresh "running" event (not a late arrival)
          if (activity.status === "running") {
            return [...updated, activity];
          }
          
          // Ignore late "complete" events for activities we don't have
          return updated;
        });
      },
      onWarning(message) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantIdRef.current
              ? { ...m, warning: message }
              : m
          )
        );
      },
      onError(message) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantIdRef.current
              ? { ...m, content: m.content + `\n\n⚠️ ${message}` }
              : m
          )
        );
      },
      onDone() {
        setIsStreaming(false);
      },
    }, attachments, cuMode, foundryIqMode);
  }, [isStreaming]);

  const resetChat = useCallback(async () => {
    const { resetSession } = await import("../api/client");
    await resetSession(sessionIdRef.current);
    sessionIdRef.current = crypto.randomUUID();
    setMessages([]);
    setActivities([]);
  }, []);

  const clearActivities = useCallback(() => {
    setActivities([]);
  }, []);

  return {
    messages,
    activities,
    isStreaming,
    send,
    resetChat,
    clearActivities,
  };
}
