import { useState, useEffect } from "react";
import { useChat } from "./hooks/useChat";
import { useTheme } from "./hooks/useTheme";
import { fetchFeatures, type CuMode, type FoundryIqMode } from "./api/client";
import ChatPanel from "./components/ChatPanel";
import ActivitySidebar from "./components/ActivitySidebar";

export default function App() {
  const { messages, activities, isStreaming, send, resetChat, clearActivities } = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const { theme, toggle: toggleTheme } = useTheme();
  const [enableAttachments, setEnableAttachments] = useState(false);
  const [cuMode, setCuMode] = useState<CuMode>("none");
  const [enableFoundryIqCuDemo, setEnableFoundryIqCuDemo] = useState(false);
  const [foundryIqMode, setFoundryIqMode] = useState<FoundryIqMode>("minimal");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      // Retry until gateway responds (handles gateway cold start / restart race)
      for (let attempt = 0; attempt < 10; attempt++) {
        try {
          const response = await fetch("/api/features");
          if (cancelled) return;
          if (response.ok) {
            const f = await response.json() as import("./api/client").Features;
            setEnableAttachments(f.content_understanding);
            setEnableFoundryIqCuDemo(f.foundry_iq_cu_demo);
            return;
          }
        } catch {
          // gateway not yet ready
        }
        if (!cancelled) await new Promise((r) => setTimeout(r, 1500));
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleSend = (text: string, attachments?: import("./api/client").FileAttachment[]) => {
    send(text, attachments, cuMode, enableFoundryIqCuDemo ? foundryIqMode : undefined);
  };

  return (
    <div className="flex h-screen flex-col bg-white text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 dark:border-gray-800 dark:bg-gray-950">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">Fibey Field Ops</h1>
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-300">
            Foundry Toolbox Demo
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={toggleTheme}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            <span className="material-icons-outlined text-[18px]">
              {theme === "dark" ? "light_mode" : "dark_mode"}
            </span>
          </button>
          <button
            onClick={resetChat}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            <span className="material-icons-outlined text-[18px]">add_comment</span>
            New Chat
          </button>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            <span className="material-icons-outlined text-[18px]">
              {sidebarOpen ? "visibility_off" : "visibility"}
            </span>
            {sidebarOpen ? "Hide" : "Show"} Activity
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex min-h-0 flex-1">
        <ChatPanel
          messages={messages}
          isStreaming={isStreaming}
          onSend={handleSend}
          enableAttachments={enableAttachments}
        />
        {sidebarOpen && (
          <ActivitySidebar
            activities={activities}
            isStreaming={isStreaming}
            onClear={clearActivities}
            enableAttachments={enableAttachments}
            cuMode={cuMode}
            onCuModeChange={setCuMode}
            enableFoundryIqCuDemo={enableFoundryIqCuDemo}
            foundryIqMode={foundryIqMode}
            onFoundryIqModeChange={setFoundryIqMode}
          />
        )}
      </div>
    </div>
  );
}
