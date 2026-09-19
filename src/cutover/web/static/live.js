/* Live run viewer. Renders NDJSON events with textContent only (model output is untrusted). */
(() => {
  const button = document.getElementById("run");
  if (!button) return;
  const steps = document.getElementById("steps");
  const state = document.getElementById("state");
  const clock = document.getElementById("clock");
  const summary = document.getElementById("summary");
  const table = document.getElementById("result-table");
  const checks = document.getElementById("checks");
  const idle = document.getElementById("result-idle");
  const fmt = (n, d = 0) => Number(n).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const usd = (n) => "US$ " + fmt(n, 6);
  let timer = null, started = 0, pending = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function step(kind, title, detail, ms, extra) {
    const row = el("div", "step " + kind);
    row.append(el("span", "dot"), el("span", "when", "+" + fmt(ms / 1000, 2) + " s"));
    const body = el("div", "what");
    body.append(el("b", null, title));
    if (detail) body.append(el("span", null, detail));
    if (extra) body.append(extra);
    row.append(body);
    steps.append(row);
    row.scrollIntoView({ block: "nearest" });
    return row;
  }

  function settle() { if (pending) { pending.classList.remove("wait"); pending = null; } }

  function render(ev) {
    const t = ev.t_ms || 0;
    switch (ev.type) {
      case "run.start":
        step("info", "Execução iniciada", `${ev.columns} colunas · destino ${ev.target} · modelo ${ev.model}`, t); break;
      case "payload.built": {
        const box = el("details"); box.append(el("summary", null, "Ver o payload enviado"), el("pre", null, ev.prompt));
        step("info", "Payload montado", `${fmt(ev.tokens)} tokens estimados. Só nomes e tipos de colunas.`, t, box); break;
      }
      case "gate.scored":
        step("ok", "Score e nível", `score ${fmt(ev.score)} (heurístico) → nível ${ev.tier} · teto de entrada ${fmt(ev.input_cap)}, saída ${fmt(ev.output_cap)} · custo máximo estimado ${usd(ev.estimated_cost_usd)}`, t); break;
      case "gate.admitted":
        step("ok", "Portão: admitido", `${fmt(ev.admitted_tokens)} tokens admitidos, ${fmt(ev.rejected_tokens)} rejeitados`, t); break;
      case "gate.blocked":
        step("bad", "Portão: bloqueado", ev.reason, t); break;
      case "provider.call":
        pending = step("info wait", "Chamando o provedor", `${ev.model} · max_tokens ${fmt(ev.max_tokens || 0)} · aguardando resposta`, t); break;
      case "provider.response":
        settle();
        step("ok", "Resposta recebida", `${fmt(ev.input_tokens)} tokens de entrada, ${fmt(ev.output_tokens)} de saída · ${fmt(ev.latency_ms)} ms · ${usd(ev.cost_usd)}`, t); break;
      case "provider.error":
        settle(); step("bad", "Erro do provedor", ev.message, t); break;
      case "gate.audited":
        step("ok", "Auditoria registrada", "Chamada gravada no livro-razão de desperdício.", t); break;
      case "result.blocked":
        step("bad", "Sem sugestão", ev.reason, t); break;
      case "result": {
        step("info", "Sugestão recebida", ev.error ? "Saída do modelo não pôde ser lida: " + ev.error : "Nada foi aplicado; exige aprovação humana.", t);
        idle.hidden = true;
        const body = table.querySelector("tbody"); body.replaceChildren();
        for (const [source, entry] of Object.entries(ev.mappings)) {
          const target = typeof entry === "string" ? entry : (entry && entry.target) || "—";
          const type = typeof entry === "object" && entry ? entry.type || "—" : "—";
          const row = el("tr"); const a = el("td", "name", source), b = el("td", "name", String(target)), c = el("td", null, String(type));
          row.append(a, b, c); body.append(row);
        }
        table.hidden = false; break;
      }
      case "checks": {
        const failed = ev.checks.filter((c) => c.status === "failed").length;
        step(failed ? "bad" : "ok", "Verificações determinísticas", `${ev.checks.length - failed} de ${ev.checks.length} passaram (pass rate ${fmt(ev.pass_rate, 2)})`, t);
        checks.replaceChildren();
        for (const c of ev.checks) {
          if (c.status === "passed") {
            const ok = el("p", "note", "✓ " + c.details); checks.append(ok);
          } else {
            const flag = el("div", "flag"); flag.append(el("span", "flag-k", c.name), el("p", null, c.details), el("p", "mono", c.offenders.join("; ")));
            checks.append(flag);
          }
        }
        break;
      }
      case "policy":
        step("info", "Política de refinamento: " + ev.action, ev.reason, t); break;
      case "summary":
        document.getElementById("s-in").textContent = fmt(ev.input_tokens);
        document.getElementById("s-out").textContent = fmt(ev.output_tokens);
        document.getElementById("s-cost").textContent = fmt(ev.cost_usd, 6);
        summary.hidden = false; break;
      case "error":
        settle(); step("bad", "Erro", ev.message, t); break;
    }
  }

  button.addEventListener("click", async () => {
    button.disabled = true;
    steps.replaceChildren(); summary.hidden = true; table.hidden = true; checks.replaceChildren(); idle.hidden = false;
    state.textContent = "Ao vivo"; state.classList.add("running");
    started = performance.now();
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
      clearInterval(timer);
      const total = (performance.now() - started) / 1000;
      clock.textContent = fmt(total, 1) + " s";
      document.getElementById("s-time").textContent = fmt(total, 1);
      state.textContent = "Concluído"; state.classList.remove("running");
      button.disabled = false; button.textContent = "Rodar de novo";
    }
  });
})();
