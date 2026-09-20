/* Copy buttons for the generated code. Falls back to selecting the text when the clipboard API is blocked. */
(() => {
  document.querySelectorAll("button.copy").forEach((button) => {
    button.addEventListener("click", async () => {
      const node = document.getElementById(button.dataset.target);
      if (!node) return;
      try {
        await navigator.clipboard.writeText(node.textContent);
        button.textContent = "Copiado";
      } catch {
        const range = document.createRange(); range.selectNodeContents(node);
        const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
        button.textContent = "Selecionado: use Ctrl+C";
      }
      setTimeout(() => { button.textContent = "Copiar"; }, 1800);
    });
  });
})();
