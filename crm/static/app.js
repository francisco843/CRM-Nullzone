document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const message = form.dataset.confirm || "Confirmar accion?";
    if (!window.confirm(message)) {
      event.preventDefault();
    }
  });
});
