import type { FileAttachment } from "../api/client";

interface Suggestion {
  prompt: string;
  tags: { label: string; color: "red" | "green" | "yellow" }[];
  file?: { path: string; name: string; type: string };
}

const suggestions: Suggestion[] = [
  {
    prompt: "Check the KB — what is the ORL reading at 1310nm for fiber F-03?",
    tags: [
      { label: "foundry-iq-demo", color: "red" },
      { label: "FoundryIQ", color: "green" },
    ],
  },
  {
    prompt:
      "For work order WO-2026-0089 (Emergency Restoration), what crew was assigned, what was the scheduled date, and what was the completion date?",
    tags: [
      { label: "cu-demo", color: "red" },
      { label: "FoundryIQ", color: "green" },
    ],
    file: { path: "/demo-files/SiteB_WorkOrders_Q1.pdf", name: "SiteB_WorkOrders_Q1.pdf", type: "application/pdf" },
  },
  {
    prompt:
      "Who was the assigned crew, what was the scheduled date, and what were the findings?",
    tags: [
      { label: "cu-demo", color: "red" },
      { label: "FoundryIQ", color: "green" },
    ],
    file: { path: "/demo-files/work_order_fiber_splice.pdf", name: "work_order_fiber_splice.pdf", type: "application/pdf" },
  },
  {
    prompt: "Pull up work order WO-003 and tell me what parts are needed.",
    tags: [
      { label: "work-order-preparation", color: "red" },
      { label: "Work Orders API", color: "green" },
      { label: "Inventory MCP", color: "yellow" },
    ],
  },
  {
    prompt: "Do we have OTDR test equipment in stock? What models are available?",
    tags: [
      { label: "inventory-lookup", color: "red" },
      { label: "Inventory MCP", color: "green" },
    ],
  },
  {
    prompt: "What are the proper procedures for fusion splicing single-mode fiber?",
    tags: [
      { label: "knowledge-retrieval", color: "red" },
      { label: "FoundryIQ", color: "green" },
    ],
  },
  {
    prompt:
      "Check the parts list for WO-005 and tell me if we have everything in stock.",
    tags: [
      { label: "work-order-preparation", color: "red" },
      { label: "Work Orders API", color: "green" },
      { label: "Inventory MCP", color: "yellow" },
    ],
  },
  {
    prompt:
      "What safety protocols should a technician review before performing aerial cable installation?",
    tags: [
      { label: "knowledge-retrieval", color: "red" },
      { label: "FoundryIQ", color: "green" },
    ],
  },
  {
    prompt:
      "Give me a full field briefing for WO-007 — parts availability, relevant procedures, and safety guidelines.",
    tags: [
      { label: "field-briefing", color: "red" },
      { label: "Work Orders API", color: "green" },
      { label: "Inventory MCP", color: "yellow" },
      { label: "FoundryIQ", color: "yellow" },
    ],
  },
];

const tagColors = {
  red: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
  green: "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300",
  yellow:
    "bg-yellow-50 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300",
};

interface PromptSuggestionsProps {
  onSelect: (prompt: string, attachments?: FileAttachment[]) => void;
}

export default function PromptSuggestions({ onSelect }: PromptSuggestionsProps) {
  const handleClick = async (s: Suggestion) => {
    if (!s.file) {
      onSelect(s.prompt);
      return;
    }
    try {
      const resp = await fetch(s.file.path);
      const blob = await resp.blob();
      const dataUrl = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.readAsDataURL(blob);
      });
      onSelect(s.prompt, [{ name: s.file.name, type: s.file.type, dataUrl }]);
    } catch {
      onSelect(s.prompt);
    }
  };

  // 4 rows: 3 / 3 / 2 / 1
  const rows = [
    suggestions.slice(0, 3),
    suggestions.slice(3, 6),
    suggestions.slice(6, 8),
    suggestions.slice(8, 9),
  ];

  return (
    <div className="flex flex-col gap-3">
      {rows.map((row, ri) => (
        <div key={ri} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${row.length}, minmax(0, 1fr))` }}>
          {row.map((s, i) => (
            <button
              key={i}
              onClick={() => handleClick(s)}
              className="group rounded-xl border border-gray-200 bg-white p-4 text-left transition-shadow hover:shadow-md dark:border-gray-700 dark:bg-gray-900"
            >
              <p className="text-sm text-gray-800 group-hover:text-gray-950 dark:text-gray-200 dark:group-hover:text-white">
                {s.prompt}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {s.tags.map((tag, j) => (
                  <span
                    key={j}
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tagColors[tag.color]}`}
                  >
                    {tag.label}
                  </span>
                ))}
                {s.file && (
                  <span className="flex items-center gap-0.5 rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                    <span className="material-icons-outlined text-[11px]">attach_file</span>
                    {s.file.name}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
