const rows = document.querySelector('#classes');
const notice = document.querySelector('#notice');
const dialog = document.querySelector('#class-dialog');
const form = document.querySelector('#class-form');
const dialogError = document.querySelector('#dialog-error');
const removeDialog = document.querySelector('#remove-dialog');
const removeError = document.querySelector('#remove-error');
let editing = null;

async function api(path, options = {}) {
  const response = await fetch(path, {...options,
    headers: {'Accept': 'application/json', ...options.headers}});
  if (response.status === 401) {
    location.assign('/');
    throw new Error('Sign in again');
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function message(value, error = false) {
  notice.textContent = value;
  notice.classList.toggle('error', error);
  notice.hidden = !value;
}

async function refresh() {
  rows.replaceChildren();
  const loading = rows.insertRow().insertCell();
  loading.colSpan = 4;
  loading.textContent = 'Loading classes…';
  try {
    const result = await api('/api/data-classes');
    rows.replaceChildren();
    for (const item of result.classes) {
      const row = rows.insertRow();
      row.insertCell().textContent = item.name;
      row.insertCell().textContent = item.approved_model_ids.join(', ') || 'None';
      row.insertCell().textContent = item.project_count;
      const action = document.createElement('button');
      action.type = 'button';
      action.textContent = 'Edit';
      action.addEventListener('click', () => openDialog(item));
      row.insertCell().append(action);
    }
  } catch (error) {
    rows.replaceChildren();
    const cell = rows.insertRow().insertCell();
    cell.colSpan = 4;
    cell.textContent = 'Could not load classes';
    message(error.message, true);
  }
}

async function openDialog(item = null) {
  editing = item;
  form.reset();
  dialogError.hidden = true;
  document.querySelector('#class-dialog-title').textContent = item ? `Edit ${item.name}` : 'Add class';
  document.querySelector('#class-name').value = item?.name || '';
  document.querySelector('#save-class').textContent = item ? 'Save' : 'Add class';
  document.querySelector('#remove-class').hidden = !item;
  const choices = document.querySelector('#approved-model-choices');
  choices.querySelectorAll('label, p').forEach((element) => element.remove());
  const save = document.querySelector('#save-class');
  save.disabled = true;
  dialog.showModal();
  try {
    const result = await api('/api/models');
    const models = result.models.filter((model) => model.approved);
    if (!models.length) {
      const empty = document.createElement('p');
      empty.className = 'field-detail';
      empty.textContent = 'No models set up yet';
      choices.append(empty);
    }
    for (const model of models) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.name = 'approved_model_ids';
      input.value = model.id;
      input.checked = item?.approved_model_ids.includes(model.id) || false;
      label.append(input, document.createTextNode(' ' + model.id));
      choices.append(label);
    }
    save.disabled = false;
  } catch (error) {
    dialogError.textContent = error.message;
    dialogError.hidden = false;
  }
}

document.querySelector('#show-add').addEventListener('click', () => openDialog());
document.querySelector('#cancel-class').addEventListener('click', () => dialog.close());
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const save = document.querySelector('#save-class');
  save.disabled = true;
  dialogError.hidden = true;
  const value = {name: document.querySelector('#class-name').value,
    approved_model_ids: new FormData(form).getAll('approved_model_ids')};
  try {
    const updated = await api(editing ? `/api/data-classes/${encodeURIComponent(editing.id)}` : '/api/data-classes', {
      method: editing ? 'PUT' : 'POST',
      headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
      body: JSON.stringify(value),
    });
    dialog.close();
    message(editing ? `Saved ${updated.name}.` : `Added ${updated.name}.`);
    await refresh();
  } catch (error) {
    dialogError.textContent = error.message;
    dialogError.hidden = false;
  } finally { save.disabled = false; }
});

document.querySelector('#remove-class').addEventListener('click', () => {
  if (!editing) return;
  removeError.hidden = true;
  document.querySelector('#remove-explanation').textContent =
    `Remove ${editing.name}? Its model approvals will be removed. A model approved for no other class will need setup again.`;
  removeDialog.showModal();
});
document.querySelector('#cancel-remove').addEventListener('click', () => removeDialog.close());
document.querySelector('#confirm-remove').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  removeError.hidden = true;
  try {
    await api(`/api/data-classes/${encodeURIComponent(editing.id)}`, {
      method: 'DELETE', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
    });
    removeDialog.close();
    dialog.close();
    message(`Removed ${editing.name}.`);
    await refresh();
  } catch (error) {
    removeError.textContent = error.message;
    removeError.hidden = false;
  } finally { button.disabled = false; }
});

api('/api/identity').then((identity) => {
  document.querySelector('#signed-in-user').textContent = identity.username;
}).catch(() => {});
refresh();
document.documentElement.dataset.appReady = 'true';
