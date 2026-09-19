/* Stopwatch and manual entry for the manual-assessment baseline. Values are self-reported. */
(() => {
  const root = document.querySelector(".baseline");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const clock = $("bl-clock"), start = $("bl-start"), stop = $("bl-stop"), msg = $("bl-msg");
  let t0 = 0, tick = null;
  const pad = (n) => String(n).padStart(2, "0");
  const show = (ms) => { const s = Math.floor(ms / 1000); clock.textContent = `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`; };

  async function save(seconds, method) {
    const body = new URLSearchParams({ seconds: String(Math.round(seconds)), method });
    const response = await fetch(root.dataset.url, { method: "POST", body });
    const data = await response.json();
    msg.textContent = data.message;
    if (data.ok) setTimeout(() => location.reload(), 700);
  }
  start.addEventListener("click", () => {
    t0 = performance.now(); start.disabled = true; stop.disabled = false; msg.textContent = "Cronômetro rodando.";
    tick = setInterval(() => show(performance.now() - t0), 250);
  });
  stop.addEventListener("click", () => {
    clearInterval(tick); const elapsed = (performance.now() - t0) / 1000; show(elapsed * 1000);
    stop.disabled = true; save(elapsed, "stopwatch");
  });
  $("bl-save").addEventListener("click", () => {
    const minutes = Number($("bl-minutes").value);
    if (!minutes) { msg.textContent = "Informe os minutos."; return; }
    save(minutes * 60, "manual");
  });
})();
