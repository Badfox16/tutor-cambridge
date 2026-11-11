/* Student UI (pure ES module, no build step).
   Talks to the tutor API; the mark scheme never reaches this code. */

const $ = (id) => document.getElementById(id);
const state = {
  questions: [],
  session: null,        // {id, turns:[...]}
  question: null,       // safe question (no scheme)
  lastTurnId: null,
  marksVisible: false,  // marks appear automatically at hint level 3
};

/* ---------------------------------------------------------- helpers */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = `erro ${res.status}`;
    try { msg = (await res.json()).error || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json();
}

/** POST and consume an NDJSON event stream. */
async function streamEvents(path, body, onEvent) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let msg = `erro ${res.status}`;
    try { msg = (await res.json()).error || msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
  const tail = buffer.trim();
  if (tail) onEvent(JSON.parse(tail));
}

function showError(message) {
  const el = $("error");
  if (!message) { el.classList.add("hidden"); return; }
  el.textContent = message;
  el.classList.remove("hidden");
}

/* ---------------------------------------------------------- status */

async function refreshStatus() {
  const dot = $("status-dot"), text = $("status-text");
  try {
    const h = await api("/api/health");
    dot.className = "dot " + (h.ollama?.up ? "on" : "off");
    text.textContent = h.ollama?.up
      ? `pronto · ${h.model}${h.ollama.loaded ? " (carregado)" : ""}`
      : "Ollama não está respondendo";
  } catch {
    dot.className = "dot off";
    text.textContent = "servidor indisponível";
  }
}

/* ---------------------------------------------------------- questions */

async function loadQuestions() {
  const data = await api("/api/questions");
  state.questions = data.questions || [];
  const list = $("question-list");
  list.innerHTML = "";
  if (!state.questions.length) {
    list.innerHTML = `<p class="meta">Nenhuma questão disponível — o Marking Lab está acessível?</p>`;
    return;
  }
  for (const q of state.questions) {
    const btn = document.createElement("button");
    btn.className = "qitem";
    btn.innerHTML = `<strong>${q.topic || q.id}</strong>
      <span class="meta">${q.id} · ${q.syllabusRef || ""} · ${q.tier || ""} · ${q.totalMarks ?? "?"} marks</span>`;
    btn.addEventListener("click", () => openQuestion(q.id));
    list.appendChild(btn);
  }
}

async function openQuestion(questionId) {
  showError(null);
  try {
    const data = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId }),
    });
    state.session = data.session;
    state.question = data.question;
    state.lastTurnId = null;
    renderQuestion();
    renderFeedback(null);
  } catch (e) {
    showError(`Não foi possível abrir a questão: ${e.message}`);
  }
}

function renderQuestion() {
  const q = state.question;
  $("pick").classList.add("hidden");
  $("quiz").classList.remove("hidden");
  $("q-meta").textContent =
    `${q.topic || ""} · ${q.syllabusRef || ""} · ${q.tier || ""} · id ${q.id}`;
  $("q-stem").textContent = q.stem || "";

  const parts = $("q-parts");
  parts.innerHTML = "";
  const markedLines = q.lines.filter((l) => l.marked);
  for (const line of markedLines) {
    const div = document.createElement("div");
    div.className = "part";
    const showMarks = state.marksVisible;
    const unit = line.answerLineUnit
      ? ` <span class="unit">(resposta em ${line.answerLineUnit})</span>` : "";
    div.innerHTML = `<label>(${line.label}) ${line.text}
        ${showMarks ? `<span class="marks">[${line.marks} mark${line.marks > 1 ? "s" : ""}]</span>` : ""}
      </label>${unit}`;
    const ta = document.createElement("textarea");
    ta.id = `answer-${line.label}`;
    ta.placeholder = "Escreva sua resposta aqui…";
    ta.dataset.label = line.label;
    div.appendChild(ta);
    parts.appendChild(div);
  }
}

function collectAnswers() {
  const lines = {};
  for (const ta of document.querySelectorAll("#q-parts textarea")) {
    const value = ta.value.trim();
    if (value) lines[ta.dataset.label] = value;
  }
  return lines;
}

/* ---------------------------------------------------------- feedback */

function renderFeedback(turnMeta, streaming) {
  const card = $("feedback-card");
  if (turnMeta === null) { card.classList.add("hidden"); return; }
  card.classList.remove("hidden");
  $("turn-meta").textContent = turnMeta;
  $("thinking").classList.toggle("hidden", !streaming);
  const actions = document.querySelector("#feedback-card .actions");
  actions.classList.toggle("hidden", !!streaming);
  $("rate").classList.add("hidden");
}

function setHintBadge(hintLevel, attempt) {
  const names = ["pergunta-guia", "ideia/fórmula", "passo a passo", "solução completa"];
  $("turn-meta").textContent =
    `tentativa ${attempt} · pista nível ${hintLevel} (${names[hintLevel] || "?"})`;
}

async function submitAnswer() {
  const lines = collectAnswers();
  if (!Object.keys(lines).length) {
    showError("Escreva a resposta de pelo menos uma parte antes de enviar.");
    return;
  }
  showError(null);
  $("send").disabled = true;
  await runTurn("/api/sessions/" + state.session.id + "/answer", { lines });
}

async function runTurn(path, body) {
  const fb = $("feedback");
  fb.textContent = "";
  fb.classList.add("empty");
  renderFeedback("preparando…", true);
  let turnId = null;
  try {
    await streamEvents(path, body, (ev) => {
      if (ev.type === "status") {
        const stage = { marking: "corrigindo sua resposta…", feedback: "escrevendo o feedback…", regenerating: "ajustando o feedback…" };
        $("turn-meta").textContent = stage[ev.stage] || ev.stage;
        setHintBadge(ev.hint_level, ev.attempt);
      } else if (ev.type === "delta") {
        fb.classList.remove("empty");
        fb.textContent += ev.text;
      } else if (ev.type === "done") {
        turnId = ev.turn_id;
        state.lastTurnId = ev.turn_id;
        setHintBadge(ev.hint_level, ev.attempt);
        // marks appear once the ladder reaches level 3 (or fully correct answer)
        const reached3 = ev.hint_level >= 3 || ev.correct === true;
        if (reached3 && !state.marksVisible) { state.marksVisible = true; $("show-marks").checked = true; renderQuestion(); }
        const sum = $("marks-summary");
        if (ev.marks_summary) {
          sum.textContent = `Marks: ${ev.marks_summary}${ev.correct === true ? " — tudo correto! 🎉" : ""}`;
          sum.classList.remove("hidden");
        } else {
          sum.classList.add("hidden");
        }
        $("rate").classList.remove("hidden");
        markRatingButtons(null);
      } else if (ev.type === "error") {
        throw new Error(ev.message);
      }
    });
    renderFeedback($("turn-meta").textContent, false);
  } catch (e) {
    renderFeedback(null);
    showError(friendly(e));
  } finally {
    $("send").disabled = false;
  }
}

function friendly(e) {
  const m = String(e.message || e);
  if (/fetch|NetworkError|Failed to fetch/i.test(m)) {
    return "Não consegui falar com o servidor (tutor-cambridge está no ar?)";
  }
  if (/Ollama/i.test(m)) return "Ollama não está respondendo. Verifique se o Ollama está rodando.";
  return m;
}

/* ---------------------------------------------------------- actions */

async function retry() {
  // same session, next attempt: clear feedback, focus the first textarea
  renderFeedback(null);
  const first = document.querySelector("#q-parts textarea");
  if (first) first.focus();
}

async function anotherHint() {
  try {
    const data = await api(`/api/sessions/${state.session.id}/hint`, { method: "POST", body: "{}" });
    $("turn-meta").textContent = `próxima tentativa virá com pista nível ${data.hint_level}`;
  } catch (e) { showError(friendly(e)); }
}

async function reveal() {
  if (!confirm("Mostrar a solução completa? Você pode tentar mais uma vez antes.")) return;
  showError(null);
  await runTurn(`/api/sessions/${state.session.id}/reveal`, {});
}

async function rate(rating) {
  if (!state.lastTurnId) return;
  try {
    await api(`/api/turns/${state.lastTurnId}/rating`, {
      method: "POST",
      body: JSON.stringify({ rating }),
    });
    markRatingButtons(rating);
  } catch (e) { showError(friendly(e)); }
}

function markRatingButtons(chosen) {
  for (const [id, value] of [["rate-up", 1], ["rate-down", -1]]) {
    const b = $(id);
    b.classList.toggle("chosen", chosen === value);
  }
}

/* ---------------------------------------------------------- boot */

function backToPicker() {
  $("quiz").classList.add("hidden");
  $("pick").classList.remove("hidden");
  renderFeedback(null);
  showError(null);
}

async function boot() {
  $("send").addEventListener("click", submitAnswer);
  $("back").addEventListener("click", backToPicker);
  $("retry").addEventListener("click", retry);
  $("hint").addEventListener("click", anotherHint);
  $("reveal").addEventListener("click", reveal);
  $("rate-up").addEventListener("click", () => rate(1));
  $("rate-down").addEventListener("click", () => rate(-1));
  $("show-marks").addEventListener("change", (e) => {
    state.marksVisible = e.target.checked;
    if (state.question) renderQuestion();
  });
  await refreshStatus();
  try { await loadQuestions(); }
  catch (e) { showError(friendly(e)); }
}

boot();
