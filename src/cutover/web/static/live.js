/* Live run viewer. Renders NDJSON events with textContent only (model output is untrusted). */
(() => {
  const button = document.getElementById("run");
  if (!button) return;
  const $ = (id) => document.getElementById(id);
  const steps = $("steps"), state = $("state"), clock = $("clock"), summary = $("summary");
  const table = $("result-table"), checks = $("checks"), idle = $("result-idle"), verbEl = $("verb");
  const stages = [...document.querySelectorAll("#stages li")];
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = (n, d = 0) => Number(n).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const usd = (n) => "US$ " + fmt(n, 6);

  // Playful status verbs: decoration while we wait, never a claim about what the model is doing.
  const VERBS = ["Ruminando", "Perscrutando", "Cogitando", "Destilando", "Garimpando", "Ponderando",
    "Decantando", "Destrinchando", "Lapidando", "Tecendo", "Afinando", "Sondando", "Mastigando", "Esmiuçando",
    "Fermentando", "Alinhavando", "Peneirando", "Escavucando"];
  const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  const decisionBox = $("decision"), decisionText = $("decision-text"), actions = $("decision-actions"), after = $("decision-after");
  const base = button.dataset.url.replace(/\/run$/, "");
  let runId = null, lastChecksPassed = false;
  let timer = null, spin = null, started = 0, pending = null, stream = null, verbIndex = 0, frame = 0, lastVerb = "";

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  function nextVerb() {
    let v; do { v = VERBS[Math.floor(Math.random() * VERBS.length)]; } while (v === lastVerb);
    lastVerb = v; return v;
  }
  function paintVerb() { verbEl.textContent = (reduced ? "•" : FRAMES[frame % FRAMES.length]) + " " + lastVerb + "…"; }
  function startVerbs() {
    lastVerb = nextVerb(); paintVerb();
    if (reduced) return;
    spin = setInterval(() => { frame += 1; if (frame % 22 === 0) lastVerb = nextVerb(); paintVerb(); }, 80);
  }
  function stopVerbs(text) { clearInterval(spin); verbEl.textContent = text; }

  function stage(name, status) {
    const li = stages.find((s) => s.dataset.s === name); if (!li) return;
    li.classList.remove("active", "done"); if (status) li.classList.add(status);
  }
  function countUp(node, value, digits) {
    if (reduced) { node.textContent = fmt(value, digits); return; }
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / 700);
      node.textContent = fmt(value * (1 - Math.pow(1 - p, 3)), digits);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function step(kind, title, detail, ms, extra) {
    const row = el("div", "step " + kind);
    row.append(el("span", "dot"), el("span", "when", "+" + fmt(ms / 1000, 2) + " s"));
    const body = el("div", "what");
    body.append(el("b", null, title));
    if (detail) body.append(el("span", null, detail));
    if (extra) body.append(extra);
    row.append(body); steps.append(row);
    row.scrollIntoView({ block: "nearest" });
    return row;
  }
  function settle() { if (pending) { pending.classList.remove("wait"); pending = null; stream = null; } }

  function ensureStream() {
    if (stream || !pending) return stream;
    const box = el("div", "stream");
    const think = el("pre", "think"), answer = el("pre", "answer"), meter = el("span", "meter", "");
    box.append(el("span", "tag", "raciocínio do modelo"), think, el("span", "tag", "resposta"), answer, meter);
    pending.querySelector(".what").append(box);
    stream = { think, answer, meter, thinkText: "", answerText: "", chars: 0 };
    return stream;
  }
  function onDelta(ev) {
    const s = ensureStream(); if (!s) return;
    if (ev.kind === "reasoning") { s.thinkText = (s.thinkText + ev.text).slice(-360); s.think.textContent = s.thinkText; }
    else { s.answerText += ev.text; s.answer.textContent = s.answerText; }
    s.chars += ev.text.length;
    s.meter.textContent = "≈ " + fmt(Math.ceil(s.chars / 4)) + " tokens recebidos (estimativa: caracteres ÷ 4; o valor medido chega no fim)";
  }

  function paintTable(mappings, animate) {
    const body = table.querySelector("tbody"); body.replaceChildren();
    for (const [source, entry] of Object.entries(mappings)) {
      const target = typeof entry === "string" ? entry : (entry && entry.target) || "—";
      const type = typeof entry === "object" && entry ? entry.type || "—" : "—";
      const row = el("tr", animate ? "reveal" : null); row.append(el("td", "name", source), el("td", "name", String(target)), el("td", null, String(type)));
      if (animate) row.style.animationDelay = (body.children.length * 40) + "ms";
      body.append(row);
    }
    idle.hidden = true; table.hidden = false;
  }
  function paintChecks(list) {
    checks.replaceChildren();
    for (const c of list) {
      if (c.status === "passed") checks.append(el("p", "note", "✓ " + c.details));
      else { const flag = el("div", "flag"); flag.append(el("span", "flag-k", c.name), el("p", null, c.details), el("p", "mono", c.offenders.join("; "))); checks.append(flag); }
    }
  }

  function render(ev) {
    const t = ev.t_ms || 0;
    switch (ev.type) {
      case "run.start":
        stage("gate", "active");
        step("info", "Execução iniciada", `${ev.columns} colunas · destino ${ev.target} · modelo ${ev.model}`, t); break;
      case "payload.built": {
        const box = el("details"); box.append(el("summary", null, "Ver o payload enviado"), el("pre", null, ev.prompt));
        step("info", "Payload montado", `${fmt(ev.tokens)} tokens estimados. Só nomes e tipos de colunas.`, t, box); break;
      }
      case "gate.scored":
        step("ok", "Score e nível", `score ${fmt(ev.score)} (heurístico) → nível ${ev.tier} · teto de entrada ${fmt(ev.input_cap)}, saída ${fmt(ev.output_cap)} · custo máximo estimado ${usd(ev.estimated_cost_usd)}`, t); break;
      case "gate.admitted":
        stage("gate", "done"); stage("call", "active");
        step("ok", "Portão: admitido", `${fmt(ev.admitted_tokens)} tokens admitidos, ${fmt(ev.rejected_tokens)} rejeitados`, t); break;
      case "gate.blocked":
        stage("gate", null); step("bad", "Portão: bloqueado", ev.reason, t); break;
      case "provider.call":
        pending = step("info wait", "Chamando o provedor", `${ev.model} · max_tokens ${fmt(ev.max_tokens || 0)}`, t); break;
      case "provider.delta": onDelta(ev); break;
      case "provider.response":
        settle(); stage("call", "done"); stage("verify", "active");
        step("ok", "Resposta recebida", `${fmt(ev.input_tokens)} tokens de entrada, ${fmt(ev.output_tokens)} de saída (medidos pelo provedor) · ${fmt(ev.latency_ms)} ms · ${usd(ev.cost_usd)}`, t); break;
      case "provider.error":
        settle(); stage("call", null); step("bad", "Erro do provedor", ev.message, t); break;
      case "gate.audited":
        step("ok", "Auditoria registrada", "Chamada gravada no livro-razão de desperdício.", t); break;
      case "result.blocked":
        step("bad", "Sem sugestão", ev.reason, t); break;
      case "result": {
        step("info", "Sugestão recebida", ev.error ? "Saída do modelo não pôde ser lida: " + ev.error : "Nada foi aplicado; exige aprovação humana.", t);
        paintTable(ev.mappings, true); break;
      }
      case "checks": {
        const failed = ev.checks.filter((c) => c.status === "failed").length;
        stage("verify", "done");
        step(failed ? "bad" : "ok", "Verificações determinísticas", `${ev.checks.length - failed} de ${ev.checks.length} passaram (pass rate ${fmt(ev.pass_rate, 2)})`, t);
        paintChecks(ev.checks);
        stage("policy", "active"); break;
      }
      case "rule.corrected":
        step("ok", "Correção por regra (sem custo)", `${ev.changes.length} ajuste(s) determinístico(s); pass rate ${fmt(ev.pass_rate_before, 2)} → ${fmt(ev.pass_rate, 2)}. Nenhum modelo foi chamado; a aprovação continua sendo humana.`, t);
        paintTable(ev.mappings, true); paintChecks(ev.checks); break;
      case "policy":
        stage("policy", "done"); step("info", "Política de refinamento: " + ev.action, ev.reason, t); break;
      case "summary":
        summary.hidden = false;
        countUp($("s-in"), ev.input_tokens, 0); countUp($("s-out"), ev.output_tokens, 0); countUp($("s-cost"), ev.cost_usd, 6); break;
      case "saved":
        runId = ev.run_id;
        step("info", "Execução salva", `Registrada como #${ev.run_id}; o resultado não se perde ao recarregar a página.`, t);
        break;
      case "error":
        settle(); step("bad", "Erro", ev.message, t); break;
    }
    if (ev.type === "checks" || ev.type === "rule.corrected") lastChecksPassed = ev.pass_rate >= 1;
  }

  const fixesBox = $("fixes"), fixesList = $("fixes-list"), fixesIntro = $("fixes-intro"), editLink = $("edit-link");
  async function loadFixes() {
    if (!runId || !fixesBox) return;
    editLink.href = `${base}/runs/${runId}/edit`;
    const response = await fetch(`${base}/runs/${runId}/fixes`);
    const data = await response.json();
    fixesList.replaceChildren();
    if (!data.ok || !data.changes.length) { fixesBox.hidden = true; return; }
    for (const c of data.changes) {
      const li = el("li");
      li.append(el("code", null, c.column), document.createTextNode(` · ${c.field}: ${c.from ?? "—"} → ${c.to ?? "remover"}. `), el("span", "why", c.reason));
      fixesList.append(li);
    }
    fixesIntro.textContent = `${data.changes.length} correção(ões) que uma regra determinística consegue fazer. Nenhum modelo é chamado e nada custa. Depois de aplicar, a sugestão precisa ser aprovada de novo.`;
    fixesBox.hidden = false;
  }
  $("fixes-apply")?.addEventListener("click", async () => {
    const response = await fetch(`${base}/runs/${runId}/fix`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "auto" }) });
    const data = await response.json();
    if (!data.ok) { decisionText.textContent = data.message; return; }
    paintTable(data.mappings, false); paintChecks(data.checks);
    lastChecksPassed = data.pass_rate >= 1; $("approve").disabled = !lastChecksPassed;
    fixesBox.hidden = true; actions.hidden = false; after.hidden = true;
    decisionText.textContent = lastChecksPassed
      ? "Correções aplicadas e verificadas. Revise e aprove: a aprovação vale para este mapeamento corrigido."
      : "Correções aplicadas, mas ainda há verificações reprovadas. Edite manualmente ou rejeite.";
  });

  async function decide(decision) {
    if (!runId) return;
    const body = new URLSearchParams({ decision });
    const response = await fetch(`${base}/runs/${runId}/decision`, { method: "POST", body });
    const data = await response.json();
    decisionText.textContent = data.ok
      ? (decision === "approved" ? "Sugestão aprovada e registrada." : "Sugestão rejeitada e registrada.")
      : data.message;
    if (data.ok) { actions.hidden = true; after.hidden = false; }
  }
  $("approve").addEventListener("click", () => decide("approved"));
  $("reject").addEventListener("click", () => decide("rejected"));

  button.addEventListener("click", async () => {
    button.disabled = true;
    steps.replaceChildren(); summary.hidden = true; table.hidden = true; checks.replaceChildren(); idle.hidden = false;
    stages.forEach((s) => s.classList.remove("active", "done"));
    decisionBox.hidden = true; after.hidden = true; actions.hidden = false; runId = null; lastChecksPassed = false;
    if (fixesBox) fixesBox.hidden = true;
    state.textContent = "Ao vivo"; state.classList.add("running");
    started = performance.now(); startVerbs();
    timer = setInterval(() => { clock.textContent = fmt((performance.now() - started) / 1000, 1) + " s"; }, 100);
    try {
      const response = await fetch(button.dataset.url, { method: "POST" });
      if (!response.ok || !response.body) { step("bad", "Não foi possível iniciar", await response.text(), 0); return; }
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, index).trim(); buffer = buffer.slice(index + 1);
          if (line) render(JSON.parse(line));
        }
      }
    } catch (error) {
      step("bad", "Conexão interrompida", String(error), performance.now() - started);
    } finally {
      clearInterval(timer); settle();
      const total = (performance.now() - started) / 1000;
      clock.textContent = fmt(total, 1) + " s";
      countUp($("s-time"), total, 1);
      stopVerbs("Concluído em " + fmt(total, 1) + " s");
      state.textContent = "Concluído"; state.classList.remove("running");
      const left = $("runs-left"); if (left) left.textContent = String(Math.max(0, Number(left.textContent) - 1));
      if (runId && table.hidden === false) {
        decisionBox.hidden = false;
        $("approve").disabled = !lastChecksPassed;
        decisionText.textContent = lastChecksPassed
          ? "Revise a sugestão e as verificações antes de decidir. Nada é aplicado automaticamente."
          : "Há verificações reprovadas: esta sugestão não pode ser aprovada como está. Aplique as correções sugeridas, edite manualmente, rejeite ou rode de novo.";
        loadFixes();
        $("download-link").href = `${base}/runs/${runId}/download`;
      }
      button.disabled = false; button.textContent = "Rodar de novo";
    }
  });
})();
