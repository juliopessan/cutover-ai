/* Upload feedback: client-side size check, progress bar and a disabled button while it runs.
   Without JavaScript the form still posts normally and the server enforces the same limits. */
(() => {
  const form = document.querySelector("form.upload");
  if (!form || !window.XMLHttpRequest) return;
  const file = form.querySelector('input[type=file]');
  const button = form.querySelector("button[type=submit]");
  const maxBytes = Number(form.dataset.maxBytes || 0);
  const status = document.getElementById("upload-status");
  const bar = document.getElementById("upload-bar");
  const fill = document.getElementById("upload-fill");
  const fmtMb = (n) => (n / 1048576).toLocaleString("pt-BR", { maximumFractionDigits: 1 });

  function fail(message) {
    status.textContent = message;
    status.className = "note upload-error";
    bar.hidden = true;
    button.disabled = false;
    button.textContent = "Enviar e perfilar";
  }

  file.addEventListener("change", () => {
    const chosen = file.files[0];
    status.className = "note";
    if (!chosen) { status.textContent = ""; return; }
    if (maxBytes && chosen.size > maxBytes) {
      fail(`“${chosen.name}” tem ${fmtMb(chosen.size)} MB e o limite é ${fmtMb(maxBytes)} MB. Escolha um arquivo menor.`);
      return;
    }
    status.textContent = `${chosen.name} · ${fmtMb(chosen.size)} MB`;
  });

  form.addEventListener("submit", (event) => {
    const chosen = file.files[0];
    if (!chosen) return;                                   // let the browser show its own required message
    if (maxBytes && chosen.size > maxBytes) { event.preventDefault(); fail(`O arquivo excede ${fmtMb(maxBytes)} MB.`); return; }
    event.preventDefault();

    const request = new XMLHttpRequest();
    request.open("POST", form.action || location.pathname);
    button.disabled = true;
    button.textContent = "Enviando…";
    bar.hidden = false;
    fill.style.width = "0%";
    status.className = "note";
    status.textContent = `Enviando ${chosen.name}…`;

    request.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      fill.style.width = pct + "%";
      bar.setAttribute("aria-valuenow", String(pct));
      status.textContent = pct < 100
        ? `Enviando ${chosen.name}… ${pct}%`
        : `Perfilando ${chosen.name}… isso é calculado do arquivo, sem IA.`;
    });
    request.addEventListener("load", () => {
      // The server answers with a redirect to the profile page, which XHR follows for us.
      if (request.status >= 200 && request.status < 400 && request.responseURL) location.href = request.responseURL;
      else fail("O envio falhou. Recarregue a página e tente de novo.");
    });
    request.addEventListener("error", () => fail("Conexão interrompida durante o envio."));
    request.addEventListener("abort", () => fail("Envio cancelado."));
    request.send(new FormData(form));
  });
})();
