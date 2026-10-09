const switchControl = document.querySelector('#ent-notes');
const notice = document.querySelector('#editions-notice');

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Accept': 'application/json', ...options.headers}});
  if (response.status === 401) {
    window.location.assign('/');
    throw new Error('Sign in again');
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

api('/api/identity').then((identity) => {
  document.querySelector('#signed-in-user').textContent = identity.username;
}).catch(() => {});

api('/api/edition-note').then(({enabled}) => {
  switchControl.checked = enabled;
  switchControl.disabled = false;
}).catch((error) => {
  notice.textContent = error.message;
  notice.classList.add('error');
  notice.hidden = false;
});

switchControl.disabled = true;
switchControl.addEventListener('change', async () => {
  const wanted = switchControl.checked;
  switchControl.disabled = true;
  try {
    await api('/api/edition-note', {
      method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
      body: JSON.stringify({enabled: wanted}),
    });
    notice.textContent = wanted ? 'The note is on.' : 'The note is off.';
    notice.classList.remove('error');
    notice.hidden = false;
  } catch (error) {
    switchControl.checked = !wanted;
    notice.textContent = error.message;
    notice.classList.add('error');
    notice.hidden = false;
  } finally { switchControl.disabled = false; }
});

document.documentElement.dataset.appReady = 'true';
