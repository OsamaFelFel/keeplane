/* Use Django's masked token with the HttpOnly CSRF cookie. Never retry a write. */
window.keeplaneFetch = async function (path, options = {}) {
  if (new URL(path, window.location.href).origin !== window.location.origin) {
    throw new Error('Keeplane requests must use the same origin');
  }
  const headers = new Headers(options.headers);
  if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
    const bootstrap = await fetch('/api/auth-options', {credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', signal: options.signal});
    if (!bootstrap.ok) throw new Error('Could not prepare the request. Try again.');
    const {csrf_token} = await bootstrap.json();
    if (!csrf_token) throw new Error('Could not prepare the request. Reload Keeplane.');
    headers.set('X-CSRFToken', csrf_token);
  }
  return fetch(path, {...options, headers, credentials: 'same-origin', mode: 'same-origin'});
};

document.addEventListener('click', async (event) => {
  const link = event.target.closest('a[href="/sign-out"]');
  if (!link) return;
  event.preventDefault();
  if (link.getAttribute('aria-disabled') === 'true') return;
  link.setAttribute('aria-disabled', 'true');
  let error = document.querySelector('#sign-out-error');
  if (error) error.remove();
  try {
    const response = await window.keeplaneFetch('/sign-out', {method: 'POST'});
    if (!response.ok) throw new Error('Could not sign out. Try again.');
    window.location.assign('/sign-in');
  } catch (cause) {
    error = document.createElement('span');
    error.id = 'sign-out-error';
    error.setAttribute('role', 'alert');
    error.textContent = cause.message;
    link.after(error);
    link.removeAttribute('aria-disabled');
  }
});
