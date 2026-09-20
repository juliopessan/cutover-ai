/* Manual and rule-based correction of a suggested mapping. The server recomputes the checks; nothing here decides. */
(() => {
  const root = document.getElementById("edit");
  if (!root) return;
  const msg = document.getElementById("edit-msg"), out = document.getElementById("edit-checks");
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  function show(data) {
    out.replaceChildren();
    for (const c of data.checks || []) {
      if (c.status === "passed") out.append(el("p", "note", "✓ " + c.details));
      else { const f = el("div", "flag"); f.append(el("span", "flag-k", c.name), el("p", null, c.details), el("p", "mono", c.offenders.join("; "))); out.append(f); }
    }
  }
  async function send(payload) {
    const response = await fetch(root.dataset.url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!data.ok) { msg.textContent = data.message; out.replaceChildren(); return; }
    show(data);
    msg.textContent = data.pass_rate >= 1
      ? `Salvo. Todas as verificações passam. A aprovação foi cancelada: volte ao mapeamento para aprovar de novo. Recarregando…`
      : `Salvo, mas ainda há verificações reprovadas (pass rate ${data.pass_rate.toFixed(2)}). Continue corrigindo.`;
    setTimeout(() => location.reload(), data.pass_rate >= 1 ? 1600 : 2400);
  }

  document.getElementById("auto").addEventListener("click", () => send({ mode: "auto" }));
  document.getElementById("save").addEventListener("click", () => {
    const entries = {};
    root.querySelectorAll("tr[data-column]").forEach((row) => {
      entries[row.dataset.column] = { target: row.querySelector(".f-target").value, type: row.querySelector(".f-type").value };
    });
    send({ mode: "manual", entries });
  });
})();
