/* Mirrors cutover.web.report.roi in the browser so the reader can replace the assumptions. */
(() => {
  const form = document.getElementById("roi-form");  // a container of inputs, not a <form>
  if (!form) return;
  const data = JSON.parse(document.getElementById("roi-data").textContent);
  const fmt = (n, d = 0) => Number(n).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmts = {
    usd0: (v) => "US$ " + fmt(v, 0), h: (v) => fmt(v, 0) + " h", pct: (v) => fmt(v * 100, 0) + "%",
    n1: (v) => (Number.isFinite(v) ? fmt(v, 1) : "sem payback"),
  };
  const value = (name) => Number(form.querySelector(`[name="${name}"]`).value) || 0;

  function roi(a, aiCost) {
    const manual = a.datasets * a.manual_hours * a.rate_usd;
    const assisted = a.datasets * (a.review_hours * a.rate_usd + aiCost) + a.platform_usd;
    const saving = manual - assisted, setup = a.setup_hours * a.rate_usd, annual = saving * a.assessments_per_year;
    return {
      manual_cost: manual, assisted_cost: assisted, saving, hours_saved: a.datasets * (a.manual_hours - a.review_hours),
      reduction: manual ? saving / manual : 0, annual_saving: annual,
      payback_assessments: saving > 0 ? setup / saving : Infinity, roi_year_one: setup ? (annual - setup) / setup : 0,
    };
  }
  function current() {
    const a = {}; for (const key of Object.keys(data.defaults)) a[key] = value(key);
    return { a, aiCost: value("ai_cost") };
  }
  function paint() {
    const { a, aiCost } = current(), out = roi(a, aiCost);
    document.querySelectorAll("#roi-out [data-o]").forEach((node) => { node.textContent = fmts[node.dataset.f](out[node.dataset.o]); });
    const manualHours = [0.5, 1, 2, 4, 8], reviewHours = [0.1, 0.25, 0.5, 1];
    const head = document.querySelector("#sens thead"), body = document.querySelector("#sens tbody");
    head.replaceChildren(); body.replaceChildren();
    const hr = document.createElement("tr"); hr.append(document.createElement("th"));
    for (const r of reviewHours) { const th = document.createElement("th"); th.className = "num"; th.textContent = fmt(r, 2) + " h"; hr.append(th); }
    head.append(hr);
    for (const m of manualHours) {
      const tr = document.createElement("tr"), first = document.createElement("td");
      first.className = "name"; first.textContent = fmt(m, 1) + " h à mão"; tr.append(first);
      for (const r of reviewHours) {
        const td = document.createElement("td"); td.className = "num";
        td.textContent = fmt(roi({ ...a, manual_hours: m, review_hours: r }, aiCost).roi_year_one * 100, 0) + "%"; tr.append(td);
      }
      body.append(tr);
    }
  }
  form.addEventListener("input", paint); paint();
})();
