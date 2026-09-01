// Types mirror the API contract (SPEC §3.1 and §3.3).
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

interface RecipeDetail {
  id: string;
  title: string;
  url: string;
  time_minutes: number | null;
  diet_tags: string[];
  ingredients: string[];
  steps: string[];
}

const REFUSAL_LABELS: Record<RefusalReason, string> = {
  out_of_corpus: "Not in this corpus",
  out_of_domain: "Not a recipe question",
  safety: "Can't judge safety — ingredients below",
};

// Chosen to demonstrate the response contract, not just successful answers:
// the corpus holds two carbonara recipes that disagree, pad thai is absent on
// purpose, and the allergy question exercises the safety policy (SPEC §3.4).
const EXAMPLES: { text: string; kind: "answer" | "refusal" }[] = [
  { text: "How do I make carbonara?", kind: "answer" },
  { text: "What's a vegetarian dinner I can make in under 30 minutes?", kind: "answer" },
  { text: "What's a good recipe for pad thai?", kind: "refusal" },
  { text: "Is the carbonara nut-free?", kind: "refusal" },
];

const form = document.getElementById("ask-form") as HTMLFormElement;
const input = document.getElementById("question") as HTMLInputElement;
const button = document.getElementById("submit") as HTMLButtonElement;
const result = document.getElementById("result") as HTMLElement;
const examples = document.getElementById("examples") as HTMLElement;

const recipeCache = new Map<string, RecipeDetail>();
let timer: number | undefined;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function reset(state: string): void {
  window.clearInterval(timer);
  result.hidden = false;
  result.dataset.state = state;
  result.replaceChildren();
}

/** Honest progress: one request is in flight, so we show elapsed time rather
 *  than invented stages. */
function showLoading(): void {
  reset("loading");
  const row = el("div", "loading");
  row.append(
    el("span", "spinner"),
    el("span", undefined, "Searching the corpus and writing an answer…"),
  );
  const elapsed = el("span", "elapsed", "0.0s");
  row.append(elapsed);
  result.append(row);

  const started = performance.now();
  timer = window.setInterval(() => {
    elapsed.textContent = `${((performance.now() - started) / 1000).toFixed(1)}s`;
  }, 100);
}

function showError(message: string): void {
  reset("error");
  result.append(el("span", "badge", "Error"), el("p", "answer", message));
}

function formatTime(minutes: number | null): string {
  if (minutes === null) return "time unknown";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function renderRecipe(recipe: RecipeDetail): HTMLElement {
  const body = el("div", "source-body");

  const meta = [formatTime(recipe.time_minutes), ...recipe.diet_tags].join(" · ");
  body.append(el("p", undefined, meta));

  if (recipe.ingredients.length) {
    body.append(el("h4", undefined, "Ingredients"));
    const list = el("ul");
    for (const item of recipe.ingredients) list.append(el("li", undefined, item));
    body.append(list);
  }

  if (recipe.steps.length) {
    body.append(el("h4", undefined, "Steps"));
    const list = el("ol");
    for (const step of recipe.steps) list.append(el("li", undefined, step));
    body.append(list);
  }

  // CC BY-SA 4.0 obliges us to name the source, link it and name the licence
  // whenever we render this text ourselves rather than linking out (SPEC §3.3).
  const credit = el("p", "attribution");
  credit.append(document.createTextNode("From "));
  const link = el("a", undefined, recipe.title);
  link.setAttribute("href", recipe.url);
  link.setAttribute("target", "_blank");
  link.setAttribute("rel", "noopener");
  credit.append(link, document.createTextNode(" on Wikibooks, CC BY-SA 4.0."));
  body.append(credit);

  return body;
}

function setToggleLabel(card: HTMLElement, open: boolean, title: string): void {
  const meta = card.querySelector<HTMLElement>(".meta");
  if (meta) meta.textContent = open ? "hide recipe" : "show recipe";
  const toggle = card.querySelector(".source-toggle");
  toggle?.setAttribute("aria-label", `${open ? "Hide" : "Show"} ${title}`);
  toggle?.setAttribute("aria-expanded", String(open));
}

async function toggleSource(card: HTMLElement, citation: Citation): Promise<void> {
  const open = card.dataset.open === "true";
  if (open) {
    card.dataset.open = "false";
    card.querySelector(".source-body")?.remove();
    setToggleLabel(card, false, citation.title);
    return;
  }

  card.dataset.open = "true";
  setToggleLabel(card, true, citation.title);
  const cached = recipeCache.get(citation.recipe_id);
  if (cached) {
    card.append(renderRecipe(cached));
    return;
  }

  const pending = el("div", "source-body");
  pending.append(el("p", undefined, "Loading recipe…"));
  card.append(pending);

  try {
    const response = await fetch(`/recipes/${encodeURIComponent(citation.recipe_id)}`);
    if (!response.ok) throw new Error(String(response.status));
    const recipe = (await response.json()) as RecipeDetail;
    recipeCache.set(citation.recipe_id, recipe);
    pending.replaceWith(renderRecipe(recipe));
  } catch {
    pending.replaceChildren();
    const failed = el("p", undefined, "Could not load this recipe. ");
    const link = el("a", undefined, "Open it on Wikibooks");
    link.setAttribute("href", citation.url);
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener");
    failed.append(link);
    pending.append(failed);
  }
}

function renderSources(citations: Citation[]): HTMLElement {
  const wrap = el("div", "sources");
  wrap.append(el("p", "sources-title", citations.length === 1 ? "Source" : "Sources"));

  for (const citation of citations) {
    const card = el("div", "source");
    card.dataset.open = "false";

    const toggle = el("button", "source-toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-label", `Show ${citation.title}`);
    toggle.setAttribute("aria-expanded", "false");
    toggle.append(
      el("span", "caret", "›"),
      el("span", "name", citation.title),
      el("span", "meta", "show recipe"),
    );
    toggle.addEventListener("click", () => void toggleSource(card, citation));

    card.append(toggle);
    wrap.append(card);
  }
  return wrap;
}

function render(data: AskResponse): void {
  reset(data.refused ? "refused" : "answer");

  if (data.refused) {
    const reason = data.refusal_reason ?? "out_of_corpus";
    result.append(el("span", "badge", REFUSAL_LABELS[reason] ?? reason));
  }
  if (data.answer) result.append(el("p", "answer", data.answer));
  if (data.citations.length) result.append(renderSources(data.citations));
}

async function ask(question: string): Promise<void> {
  input.value = question;
  button.disabled = true;
  showLoading();

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (response.status === 422) {
      showError("That question can't be processed — it must be 1–500 characters.");
    } else if (response.status === 503) {
      showError("The answering model is unavailable right now. Please try again shortly.");
    } else if (!response.ok) {
      showError(`The service is having trouble right now (HTTP ${response.status}).`);
    } else {
      render((await response.json()) as AskResponse);
    }
  } catch {
    showError("Network error — could not reach the service.");
  } finally {
    window.clearInterval(timer);
    button.disabled = false;
  }
}

for (const example of EXAMPLES) {
  const chip = el("button", "chip", example.text);
  chip.type = "button";
  chip.dataset.kind = example.kind;
  chip.addEventListener("click", () => void ask(example.text));
  examples.append(chip);
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (question) void ask(question);
});
