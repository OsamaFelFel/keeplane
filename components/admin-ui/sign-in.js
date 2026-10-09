const form = document.querySelector('#sign-in-form');
const error = document.querySelector('#sign-in-error');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  error.hidden = true;
  const fields = Object.fromEntries(new FormData(form));
  try {
    const response = await fetch('/api/session', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(fields),
    });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || 'Could not sign in');
    }
    window.location.assign('/');
  } catch (cause) {
    error.textContent = cause.message;
    error.hidden = false;
    button.disabled = false;
  }
});
