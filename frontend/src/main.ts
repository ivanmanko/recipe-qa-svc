// Types mirror the AskResponse contract (SPEC §3.1).
type RefusalReason = "out_of_corpus" | "out_of_domain" | "safety";

interface Citation {
  title: string;
  url: string;
  recipe_id: string;
}

interface AskResponse {
  answer: string | null;
  citations: Citation[];
  refused: boolean;
  refusal_reason: RefusalReason | null;
  request_id: string;
}

const REFUSAL_LABELS: Record<RefusalReason, string> = {
  out_of_corpus: "Not in the corpus",
  out_of_domain: "Not a recipe question",
  safety: "Safety — can't judge, ingredients below",
};

const form = document.getElementById("ask-form") as HTMLFormElement;
const input = document.getElementById("question") as HTMLInputElement;
const button = document.getElementById("submit") as HTMLButtonElement;
const result = document.getElementById("result") as HTMLElement;

function show(className: string, html: string): void {
  result.hidden = false;
  result.className = className;
  result.innerHTML = html;
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function citationsHtml(citations: Citation[]): string {
  if (citations.length === 0) return "";
  const items = citations
    .map(
      (c) =>
        `<li><a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.title)}</a></li>`,
    )
    .join("");
  return `<div class="citations"><h2>Sources</h2><ul>${items}</ul></div>`;
}

function render(data: AskResponse): void {
  const answer = data.answer ? escapeHtml(data.answer) : "";
  if (data.refused) {
    const reason = data.refusal_reason ?? "out_of_corpus";
    show(
      "refused",
      `<span class="badge">${REFUSAL_LABELS[reason] ?? reason}</span>` +
        `<div>${answer}</div>` +
        citationsHtml(data.citations),
    );
  } else {
    show("", `<div>${answer}</div>` + citationsHtml(data.citations));
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;

  button.disabled = true;
  show("", "Thinking…");
  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (response.status === 422) {
      show("error", "That question can't be processed — it must be 1–500 characters.");
    } else if (!response.ok) {
      show("error", `The service is having trouble right now (HTTP ${response.status}). Please try again.`);
    } else {
      render((await response.json()) as AskResponse);
    }
  } catch {
    show("error", "Network error — could not reach the service.");
  } finally {
    button.disabled = false;
  }
});
