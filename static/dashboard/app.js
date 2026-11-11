// Dashboard do tutor-cambridge. JS puro, gráficos em SVG à mão, offline.
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { run: "", model: "", tab: "overview" };

const STAGE_COLORS = {
  "lab.fetch": "#5b9dff", "render": "#8b7cf7", "model.load": "#ffc266",
  "model.prefill": "#ff9f6b", "model.generate": "#ff6b6b", "parse": "#3ecf8e",
  "lab.submit": "#46c8b2", "lab.score": "#6bd0ff", "tutor.feedback": "#c98bff",
  "tutor.leak_check": "#ff7fd1", "judge": "#d0d86b",
};

// ---------- helpers ----------
async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

const fmt = {
  ms(v) { return v == null ? "—" : (v >= 10000 ? `${(v / 1000).toFixed(1)} s` : `${v.toFixed(1)} ms`); },
  pct(v, n) { return v == null ? "—" : `${(v * 100).toFixed(1)}%${n != null ? ` <span class="note">(n=${n})</span>` : ""}`; },
  num(v, d = 1) { return v == null ? "—" : v.toFixed(d); },
  tok(v) { return v == null ? "—" : `${v} tok/s`; },
};

function card(title, value, note = "") {
  return `<div class="card"><h3>${title}</h3><div class="big">${value}</div>${note ? `<div class="note">${note}</div>` : ""}</div>`;
}

function empty(msg) { return `<div class="empty">${msg}</div>`; }

function table(headers, rows) {
  if (!rows.length) return empty("Sem dados ainda — rode o marker: python -m tutor.marker run");
  const head = `<tr>${headers.map((h, i) => `<th class="${i && i < headers.length - 1 ? "" : h.cls || ""}">${h.label || h}</th>`).join("")}</tr>`;
  return `<table><thead>${head}</thead><tbody>${rows.map((r) => `<tr>${r}</tr>`).join("")}</tbody></table>`;
}

function barChart(labels, values, colors, unit = "ms") {
  const max = Math.max(...values, 1);
  const bars = labels.map((l, i) => {
    const h = Math.round((values[i] / max) * 120);
    const color = colors[i] || STAGE_COLORS[l] || "#5b9dff";
    return `<g transform="translate(${i * 74},0)">
      <rect x="18" y="${140 - h}" width="38" height="${h}" fill="${color}" rx="3"/>
      <text x="37" y="${134 - h}" fill="var(--text)" font-size="10" text-anchor="middle">${values[i].toFixed(labels.length > 8 ? 0 : 1)}</text>
      <text x="37" y="155" fill="var(--muted)" font-size="9" text-anchor="middle">${l}</text>
    </g>`;
  }).join("");
  return `<svg viewBox="0 0 ${labels.length * 74} 165" width="${Math.min(labels.length * 74, 900)}">
    <line x1="0" y1="140" x2="${labels.length * 74}" y2="140" stroke="var(--line)"/>${bars}</svg>
    <div class="note">unidade: ${unit}</div>`;
}

function stackedBar(parts) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  const segs = parts.map((p) =>
    `<div class="bar-seg" style="width:${((p.value / total) * 100).toFixed(2)}%;background:${p.color}" title="${p.label}: ${p.value.toFixed(0)} ms"></div>`).join("");
  const legend = parts.map((p) =>
    `<span><span class="dot" style="background:${p.color}"></span>${p.label} ${fmt.ms(p.value)}</span>`).join("");
  return `<div class="bar-track">${segs}</div><div class="legend">${legend}</div>`;
}

function pill(ok, okText = "ok", failText = "falha") {
  return `<span class="pill ${ok ? "ok" : "fail"}">${ok ? okText : failText}</span>`;
}

// ---------- tabs ----------
const renderers = {
  async overview(el) {
    const [ov, health] = await Promise.all([api("/api/stats/overview"), api("/api/health")]);
    $("#health").innerHTML = `Ollama <span class="${health.ollama.up ? "up" : "down"}">${health.ollama.up ? "no ar" : "fora"}</span> · Lab <span class="${health.lab.up ? "up" : "down"}">${health.lab.up ? "no ar" : "fora"}</span>`;
    const loaded = health.ollama.loaded?.name;
    const vram = health.ollama.loaded?.size_vram ? ` (${(health.ollama.loaded.size_vram / 1e9).toFixed(1)} GB em VRAM)` : "";
    el.innerHTML = `
      <div class="cards">
        ${card("Ollama", health.ollama.up ? "no ar" : "fora do ar", loaded ? `${loaded}${vram}` : "nenhum modelo carregado")}
        ${card("Marking Lab", health.lab.up ? "no ar" : "fora do ar", `dataset v${health.lab.datasetVersion ?? "?"}`)}
        ${card("Traces", ov.counts.traces, `${ov.counts.answer_traces} de respostas · ${ov.counts.sessions} sessões · ${ov.counts.turns} turnos`)}
        ${card("Taxa de sucesso", fmt.pct(ov.success_rate, ov.counts.answer_traces), "traces de resposta com ok=1")}
      </div>
      <h2>Runs recentes</h2>
      ${table([{ label: "#", cls: "num" }, "kind", "modelo", "prompt", "status", "início", "fim", { label: "Lab run", cls: "num" }],
        ov.recent_runs.map((r) => [
          `<td class="num">${r.id}</td><td>${r.kind}</td><td>${r.model}</td><td>${r.prompt_variant}</td>
           <td><span class="pill ${r.status === "done" ? "ok" : r.status === "running" ? "na" : "fail"}">${r.status}</span></td>
           <td>${(r.started_at || "").slice(0, 19).replace("T", " ")}</td>
           <td>${(r.finished_at || "").slice(0, 19).replace("T", " ")}</td>
           <td class="num">${r.lab_run_id ?? "—"}</td>`]))}`;
  },

  async accuracy(el) {
    const m = await api(`/api/stats/marker?run_id=${state.run}`);
    if (!m.score) { el.innerHTML = empty(m.note || "Sem score — rode e feche uma run do marker."); return; }
    const o = m.score.overall || {};
    const clear = m.score.clearCases || {};
    const marked = m.score.answersMarked;
    el.innerHTML = `
      <div class="cards">
        ${card("Acordo total", fmt.pct(o.exactTotalAgreement, o.results), `clear cases: ${fmt.pct(clear.exactTotalAgreement)}`)}
        ${card("Acordo por linha", fmt.pct(o.lineAgreement), "partes com total = referência")}
        ${card("Acordo por ponto", fmt.pct(o.pointAgreement), "granularidade fina (com scheme)")}
        ${card("MAE", fmt.num(o.meanAbsError, 2), "|nota − referência|, média")}
        ${card("Bias", fmt.num(o.bias, 2), o.bias < 0 ? "negativo: severo demais" : o.bias > 0 ? "positivo: generoso demais" : "centrado")}
        ${card("Parse failures", o.parseFailures ?? "—", `de ${marked} respostas marcadas`)}
      </div>
      <h2>Concordância dos traces desta run</h2>
      <div class="note">agree ${m.agreement.agree} · disagree ${m.agreement.disagree} (n=${m.agreement.n})</div>
      <h2>Discordâncias (${m.disagreements.length})</h2>
      ${table([{ label: "#", cls: "num" }, "resposta", "questão", "attempt", { label: "obtido", cls: "num" }, { label: "referência", cls: "num" }, "trace"],
        m.disagreements.map((d) => [
          `<td class="num">${d.resultId}</td><td>${d.answerId ?? "(custom)"}</td><td>${d.questionId}</td>
           <td class="num">${d.repeat}</td><td class="num">${d.harness?.total ?? "parse failed"}</td>
           <td class="num">${d.reference?.total ?? "—"}</td>
           <td>${d.trace_id ? `<a href="#" data-trace="${d.trace_id}">ver trace</a>` : "—"}</td>`]))}`;
    el.querySelectorAll("[data-trace]").forEach((a) =>
      a.addEventListener("click", (e) => { e.preventDefault(); openTrace(a.dataset.trace); }));
  },

  async stages(el) {
    const st = await api(`/api/stats/stages?run_id=${state.run}&model=${encodeURIComponent(state.model)}`);
    const names = Object.keys(st);
    if (!names.length) { el.innerHTML = empty("Sem spans ainda — rode o marker."); return; }
    const means = names.map((n) => st[n].mean_ms);
    el.innerHTML = `
      <h2>Tempo médio por etapa</h2>
      ${barChart(names, means, names.map((n) => STAGE_COLORS[n]))}
      <h2>Tempo médio por trace de resposta (empilhado)</h2>
      ${stackedBar(names.filter((n) => !["lab.score", "lab.submit", "lab.fetch"].includes(n))
        .map((n) => ({ label: n, value: st[n].mean_ms, color: STAGE_COLORS[n] })))}
      <h2>Detalhe (p50 / p95 / falhas)</h2>
      ${table(["etapa", { label: "n", cls: "num" }, { label: "média", cls: "num" }, { label: "p50", cls: "num" }, { label: "p95", cls: "num" }, { label: "falhas", cls: "num" }],
        names.map((n) => [`<td><span class="dot" style="background:${STAGE_COLORS[n]}"></span>${n}</td>
          <td class="num">${st[n].n}</td><td class="num">${fmt.ms(st[n].mean_ms)}</td>
          <td class="num">${fmt.ms(st[n].p50_ms)}</td><td class="num">${fmt.ms(st[n].p95_ms)}</td>
          <td class="num">${(st[n].fail_pct * 100).toFixed(1)}%</td>`]))}`;
  },

  async perf(el) {
    const p = await api(`/api/stats/model?model=${encodeURIComponent(state.model)}&run_id=${state.run}`);
    if (!p.n) { el.innerHTML = empty("Sem chamadas de modelo ainda."); return; }
    const hist = p.latency_histogram;
    const maxH = Math.max(...hist.map((b) => b.n), 1);
    el.innerHTML = `
      <div class="cards">
        ${card("Velocidade (tokens/s)", fmt.tok(p.tokens_per_s.mean), `p50 ${fmt.tok(p.tokens_per_s.p50)} · p95 ${fmt.tok(p.tokens_per_s.p95)} (n=${p.n})`)}
        ${card("TTFT", fmt.ms(p.ttft_ms.mean), `p50 ${fmt.ms(p.ttft_ms.p50)} · p95 ${fmt.ms(p.ttft_ms.p95)}`)}
        ${card("Load (cold/warm)", `${p.load_cold_warm.cold}/${p.load_cold_warm.warm}`, `média ${fmt.ms(p.load_ms.mean)} — cold start carrega os pesos`)}
        ${card("Tokens de prompt", fmt.num(p.prompt_tokens.mean, 0), "média por chamada")}
        ${card("Tokens gerados", fmt.num(p.gen_tokens.mean, 0), "média por chamada")}
        ${card("Thinking (chars)", fmt.num(p.thinking_chars.mean, 0), "só com think=on; nunca exibido ao aluno")}
      </div>
      <h2>Histograma de latência total</h2>
      ${barChart(hist.map((b) => b.bucket), hist.map((b) => b.n), hist.map(() => "#5b9dff"), "traces")}
      <div class="note">cada trace de resposta tem os números completos no Explorador (span model.generate)</div>`;
  },

  async reliability(el) {
    const r = await api(`/api/stats/reliability?run_id=${state.run}&model=${encodeURIComponent(state.model)}`);
    el.innerHTML = `
      <div class="cards">
        ${card("Parse OK", r.parse.ok, `${r.parse.failed} falhas · taxa ${(r.parse.rate * 100).toFixed(1)}%`)}
        ${card("Cortes por max_tokens", r.cut_off, "finish_reason=length")}
      </div>
      <h2>Motivos de parse failure</h2>
      ${table([{ label: "motivo", cls: "" }, { label: "n", cls: "num" }],
        r.parse.reasons.map((f) => [`<td>${f.reason || "(sem motivo)"}</td><td class="num">${f.n}</td>`]))}
      <h2>Falhas por etapa (spans ok=false)</h2>
      ${r.span_failures.length ? table(["etapa", { label: "n", cls: "num" }],
        r.span_failures.map((f) => [`<td>${f.stage}</td><td class="num">${f.n}</td>`]))
        : empty("Nenhuma falha de etapa registrada.")}`;
  },

  async traces(el) {
    const params = new URLSearchParams();
    if (state.run) params.set("run_id", state.run);
    if (state.model) params.set("model", state.model);
    const data = await api(`/api/traces?${params}`);
    el.innerHTML = `
      <h2>Traces de resposta (${data.total})</h2>
      ${table([{ label: "#", cls: "num" }, "questão", "resposta", { label: "att", cls: "num" }, "ok", "parse", { label: "acordo", cls: "num" }, { label: "tempo", cls: "num" }, "motivo", ""],
        data.traces.map((t) => [
          `<td class="num">${t.id}</td><td>${t.question_id}</td><td>${t.answer_id}</td>
           <td class="num">${t.attempt}</td><td>${pill(t.ok, "ok", "erro")}</td>
           <td>${t.parse_failed ? pill(false, "", "falha") : pill(true, "ok")}</td>
           <td class="num">${t.agree == null ? "—" : t.agree ? "✔" : "✘"}</td>
           <td class="num">${fmt.ms(t.total_ms)}</td><td class="note">${t.reason || ""}</td>
           <td><a href="#" data-trace="${t.id}">abrir</a></td>`]))}`;
    el.querySelectorAll("[data-trace]").forEach((a) =>
      a.addEventListener("click", (e) => { e.preventDefault(); openTrace(a.dataset.trace); }));
  },
};

async function openTrace(id) {
  const t = await api(`/api/traces/${id}`);
  const waterfall = t.spans.map((s) => {
    const width = Math.max(2, Math.round((s.duration_ms || 0) / (t.total_ms || 1) * 100));
    const color = STAGE_COLORS[s.stage] || "#5b9dff";
    return `<tr><td>${s.stage}</td><td><div style="background:${color};height:14px;width:${width}%;border-radius:3px"></div></td>
      <td class="num">${fmt.ms(s.duration_ms)}</td><td class="num">${s.tokens_in}→${s.tokens_out}</td>
      <td>${s.ok ? "" : `<span class="pill fail">${s.error || "falha"}</span>`}</td></tr>`;
  }).join("");
  const meta = t.spans.find((s) => s.stage === "model.generate")?.meta || {};
  $("#modal-content").innerHTML = `
    <h2>Trace #${t.id} — ${t.question_id} / ${t.answer_id} (attempt ${t.attempt})</h2>
    <div class="legend">
      <span>${t.ok ? pill(true, "ok") : pill(false, "", "erro")}</span>
      <span>parse ${t.parse_failed ? pill(false, "", "falha") : pill(true, "ok")}</span>
      <span>acordo: ${t.agree == null ? "—" : t.agree ? "✔" : "✘"}</span>
      <span>total ${fmt.ms(t.total_ms)}</span>
      <span>tok/s ${fmt.tok(meta.tokens_per_s)}</span><span>TTFT ${fmt.ms(meta.ttft_ms)}</span>
      <span>load ${fmt.ms(meta.load_ms)}</span>
    </div>
    ${t.reason ? `<h2>Motivo (parse/exceção)</h2><pre>${t.reason}</pre>` : ""}
    <h2>Cascata de spans</h2>
    <table><tbody>${waterfall}</tbody></table>
    <h2>Prompt enviado</h2><pre>${escapeHtml(t.prompt)}</pre>
    <h2>Resposta crua do modelo</h2><pre>${escapeHtml(t.raw_output || "(vazia)")}</pre>
    <h2>Parse</h2><pre>${JSON.stringify(t.parsed, null, 2) || "(null)"}</pre>`;
  $("#trace-modal").classList.remove("hidden");
}

function escapeHtml(s) { return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;"); }

// ---------- shell ----------
function switchTab(name) {
  state.tab = name;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("section.tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${name}`));
  renderers[name]($("#tab-" + name)).catch(showError);
}

function showError(e) {
  const el = $(`#tab-${state.tab}`);
  if (el) el.innerHTML = empty(`Erro ao carregar: ${e.message}`);
}

async function initFilters() {
  const [runs, health] = await Promise.all([api("/api/runs"), api("/api/health").catch(() => ({}))]);
  const runSel = $("#f-run");
  for (const r of runs.runs) {
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = `#${r.id} · ${r.model} · ${r.prompt_variant}`;
    runSel.appendChild(opt);
  }
  const modelSel = $("#f-model");
  for (const m of health.models || []) {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    modelSel.appendChild(opt);
  }
}

$("#f-run").addEventListener("change", (e) => { state.run = e.target.value; switchTab(state.tab); });
$("#f-model").addEventListener("change", (e) => { state.model = e.target.value; switchTab(state.tab); });
$("#f-refresh").addEventListener("click", () => switchTab(state.tab));
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
$("#modal-close").addEventListener("click", () => $("#trace-modal").classList.add("hidden"));
$("#trace-modal").addEventListener("click", (e) => { if (e.target.id === "trace-modal") $("#trace-modal").classList.add("hidden"); });

initFilters().then(() => switchTab("overview")).catch(showError);
