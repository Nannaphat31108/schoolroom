(() => {
  const dialog = document.getElementById('confirmDialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  let pendingForm = null;
  document.querySelectorAll('[data-confirm-cancel]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (form.dataset.confirmed === '1') return;
      event.preventDefault();
      pendingForm = form;
      dialog.showModal();
    });
  });

  dialog.querySelector('[data-dialog-close]')?.addEventListener('click', () => {
    pendingForm = null;
    dialog.close();
  });

  dialog.querySelector('[data-dialog-confirm]')?.addEventListener('click', () => {
    if (!pendingForm) return dialog.close();
    pendingForm.dataset.confirmed = '1';
    dialog.close();
    pendingForm.requestSubmit();
  });

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      pendingForm = null;
      dialog.close();
    }
  });
})();
