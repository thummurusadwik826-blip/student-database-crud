/**
 * Student Database Dashboard — JavaScript
 *
 * Architecture:
 *   - api.*       thin wrappers around fetch() for each backend endpoint
 *   - ui.*        DOM helpers: toast notifications, modal open/close, rendering
 *   - state       single source of truth for loaded students + sort state
 *   - handlers.*  event handler setup wired to buttons/inputs
 *
 * Every value written to the DOM uses textContent or createTextNode,
 * never innerHTML with user-supplied data, to prevent XSS.
 */

'use strict';

/* =========================================================================
   API layer — talks to the FastAPI backend
   ========================================================================= */
const api = {
  BASE: '/students',

  async list() {
    const r = await fetch(`${this.BASE}/`);
    if (!r.ok) throw new Error(`Server returned ${r.status}`);
    return r.json();
  },

  async get(id) {
    const r = await fetch(`${this.BASE}/${encodeURIComponent(id)}`);
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`Server returned ${r.status}`);
    return r.json();
  },

  async create(payload) {
    const r = await fetch(`${this.BASE}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = extractApiError(data, r.status);
      throw new ApiError(msg, r.status, data);
    }
    return data;
  },

  async update(id, payload) {
    const r = await fetch(`${this.BASE}/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = extractApiError(data, r.status);
      throw new ApiError(msg, r.status, data);
    }
    return data;
  },

  async delete(id) {
    const r = await fetch(`${this.BASE}/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    if (r.status === 204) return true;
    if (r.status === 404) return false;
    const data = await r.json().catch(() => ({}));
    throw new ApiError(extractApiError(data, r.status), r.status, data);
  },
};

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

function extractApiError(data, status) {
  if (data && data.detail) {
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail) && data.detail.length > 0) {
      const first = data.detail[0];
      return first.msg || JSON.stringify(first);
    }
  }
  return `Request failed (${status})`;
}

/* =========================================================================
   Application state
   ========================================================================= */
const state = {
  students: [],          // full list from API
  filtered: [],          // after search filter
  sortCol: 'student_id', // current sort column key
  sortDir: 'asc',        // 'asc' | 'desc'
  loading: false,
  searchQuery: '',
};

/* =========================================================================
   Toast notifications
   ========================================================================= */
const toast = (() => {
  const ICONS = {
    success: `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>`,
    error:   `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>`,
    warning: `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`,
  };

  function show(type, title, msg = '', duration = 4000) {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;

    // Icon
    const iconEl = document.createElement('div');
    iconEl.className = 'toast-icon';
    iconEl.innerHTML = ICONS[type] || '';

    // Body
    const body = document.createElement('div');
    body.className = 'toast-body';
    const titleEl = document.createElement('div');
    titleEl.className = 'toast-title';
    titleEl.textContent = title;
    body.appendChild(titleEl);
    if (msg) {
      const msgEl = document.createElement('div');
      msgEl.className = 'toast-msg';
      msgEl.textContent = msg;
      body.appendChild(msgEl);
    }

    // Dismiss button
    const dismiss = document.createElement('button');
    dismiss.className = 'toast-dismiss';
    dismiss.setAttribute('aria-label', 'Dismiss');
    dismiss.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>`;
    dismiss.addEventListener('click', () => remove(el));

    el.append(iconEl, body, dismiss);
    container.appendChild(el);

    if (duration > 0) setTimeout(() => remove(el), duration);
  }

  function remove(el) {
    if (!el.parentNode) return;
    el.classList.add('removing');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }

  return {
    success: (title, msg) => show('success', title, msg),
    error:   (title, msg) => show('error', title, msg),
    warning: (title, msg) => show('warning', title, msg),
  };
})();

/* =========================================================================
   Modal helpers
   ========================================================================= */
function openModal(id) {
  const el = document.getElementById(id);
  el.classList.add('open');
  // Focus first focusable element
  const focusable = el.querySelector('input, select, textarea, button:not(.modal-close)');
  if (focusable) setTimeout(() => focusable.focus(), 60);
  // Trap: close on backdrop click
  el.addEventListener('mousedown', (e) => {
    if (e.target === el) closeModal(id);
  });
}

function closeModal(id) {
  const el = document.getElementById(id);
  el.classList.remove('open');
}

// Close modals on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-backdrop.open').forEach(m => {
      m.classList.remove('open');
    });
  }
});

/* =========================================================================
   Sorting helpers
   ========================================================================= */
function applySort(list) {
  const col = state.sortCol;
  const dir = state.sortDir === 'asc' ? 1 : -1;
  return [...list].sort((a, b) => {
    const va = (a[col] || '').toString().toLowerCase();
    const vb = (b[col] || '').toString().toLowerCase();
    if (va < vb) return -1 * dir;
    if (va > vb) return  1 * dir;
    return 0;
  });
}

function applySearch(list, q) {
  if (!q) return list;
  const lower = q.toLowerCase();
  return list.filter(s =>
    (s.student_id || '').toLowerCase().includes(lower) ||
    (s.name || '').toLowerCase().includes(lower) ||
    (s.email || '').toLowerCase().includes(lower) ||
    (s.phone || '').toLowerCase().includes(lower)
  );
}

/* =========================================================================
   Stats bar
   ========================================================================= */
function updateStats(students) {
  const total = students.length;
  const withEmail = students.filter(s => s.email).length;
  const withPhone = students.filter(s => s.phone).length;

  const setEl = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  setEl('stat-total', total);
  setEl('stat-email', withEmail);
  setEl('stat-phone', withPhone);
  setEl('stat-both', students.filter(s => s.email && s.phone).length);
}

/* =========================================================================
   Table rendering
   ========================================================================= */
function renderTable() {
  const tbody = document.getElementById('student-tbody');
  if (!tbody) return;

  // Update sort header indicators
  document.querySelectorAll('th[data-col]').forEach(th => {
    const icon = th.querySelector('.sort-icon');
    if (!icon) return;
    if (th.dataset.col === state.sortCol) {
      th.classList.add('sorted');
      icon.textContent = state.sortDir === 'asc' ? '↑' : '↓';
    } else {
      th.classList.remove('sorted');
      icon.textContent = '↕';
    }
  });

  const display = applySort(applySearch(state.students, state.searchQuery));
  state.filtered = display;

  // Update result count
  const countEl = document.getElementById('result-count');
  if (countEl) {
    if (state.searchQuery) {
      countEl.textContent = `${display.length} of ${state.students.length} students`;
    } else {
      countEl.textContent = `${state.students.length} student${state.students.length !== 1 ? 's' : ''}`;
    }
  }

  tbody.innerHTML = '';

  if (state.loading) {
    // Skeleton rows
    for (let i = 0; i < 4; i++) {
      const tr = document.createElement('tr');
      tr.className = 'skeleton-row';
      ['60%','80%','50%','70%','40%','80px'].forEach(w => {
        const td = document.createElement('td');
        const sk = document.createElement('span');
        sk.className = 'skeleton';
        sk.style.width = w;
        td.appendChild(sk);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    return;
  }

  if (display.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 6;
    td.innerHTML = '';

    if (state.students.length === 0) {
      // True empty state
      const wrap = document.createElement('div');
      wrap.className = 'empty-state';
      wrap.innerHTML = `
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round"
              d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
          </svg>
        </div>`;
      const h3 = document.createElement('h3');
      h3.textContent = 'No students yet';
      const p = document.createElement('p');
      p.textContent = 'Get started by adding your first student record.';
      const addBtn = document.createElement('button');
      addBtn.className = 'btn btn-primary';
      addBtn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 5a1 1 0 011 1v3h3a1 1 0 110 2h-3v3a1 1 0 11-2 0v-3H6a1 1 0 110-2h3V6a1 1 0 011-1z" clip-rule="evenodd"/></svg> Add Student`;
      addBtn.addEventListener('click', () => openModal('modal-add'));
      wrap.appendChild(h3);
      wrap.appendChild(p);
      wrap.appendChild(addBtn);
      td.appendChild(wrap);
    } else {
      // Search returned nothing
      const wrap = document.createElement('div');
      wrap.className = 'empty-state';
      wrap.innerHTML = `
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
        </div>`;
      const h3 = document.createElement('h3');
      h3.textContent = 'No results found';
      const p = document.createElement('p');
      p.textContent = `No students match "${state.searchQuery}". Try a different search term.`;
      wrap.appendChild(h3);
      wrap.appendChild(p);
      td.appendChild(wrap);
    }

    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // Render rows
  display.forEach(student => {
    const tr = document.createElement('tr');
    tr.dataset.id = student.student_id;

    // ID
    const tdId = document.createElement('td');
    tdId.className = 'cell-id';
    tdId.textContent = student.student_id;

    // Name
    const tdName = document.createElement('td');
    tdName.className = 'cell-name';
    tdName.textContent = student.name;

    // DOB
    const tdDob = document.createElement('td');
    tdDob.className = 'cell-dob';
    tdDob.textContent = formatDate(student.date_of_birth);

    // Contact
    const tdContact = document.createElement('td');
    tdContact.className = 'cell-contact';
    if (student.email) {
      const span = document.createElement('span');
      span.className = 'contact-email';
      span.textContent = student.email;
      tdContact.appendChild(span);
    }
    if (student.phone) {
      const span = document.createElement('span');
      span.className = 'contact-phone';
      span.textContent = student.phone;
      tdContact.appendChild(span);
    }
    if (!student.email && !student.phone) {
      const span = document.createElement('span');
      span.className = 'badge-none';
      span.textContent = '—';
      tdContact.appendChild(span);
    }

    // Actions
    const tdAct = document.createElement('td');
    tdAct.className = 'cell-actions';

    const viewBtn = document.createElement('button');
    viewBtn.className = 'btn-icon';
    viewBtn.title = 'View details';
    viewBtn.setAttribute('aria-label', `View ${student.name}`);
    viewBtn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/></svg>`;
    viewBtn.addEventListener('click', () => showDetail(student));

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-icon';
    editBtn.title = 'Edit student';
    editBtn.setAttribute('aria-label', `Edit ${student.name}`);
    editBtn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>`;
    editBtn.addEventListener('click', () => openEditModal(student));

    const delBtn = document.createElement('button');
    delBtn.className = 'btn-icon danger';
    delBtn.title = 'Delete student';
    delBtn.setAttribute('aria-label', `Delete ${student.name}`);
    delBtn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`;
    delBtn.addEventListener('click', () => openDeleteConfirm(student));

    tdAct.append(viewBtn, editBtn, delBtn);
    tr.append(tdId, tdName, tdDob, tdContact, tdAct);
    tbody.appendChild(tr);
  });
}

function formatDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  if (!y || !m || !d) return iso;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[parseInt(m, 10) - 1]} ${parseInt(d, 10)}, ${y}`;
}

/* =========================================================================
   Load / refresh
   ========================================================================= */
async function loadStudents() {
  state.loading = true;
  renderTable();

  try {
    state.students = await api.list();
    updateStats(state.students);
  } catch (err) {
    toast.error('Failed to load students', err.message);
    state.students = [];
  } finally {
    state.loading = false;
    renderTable();
  }
}

/* =========================================================================
   Detail modal
   ========================================================================= */
function showDetail(student) {
  const modal = document.getElementById('modal-detail');

  const set = (id, val, cls) => {
    const el = modal.querySelector(`[data-field="${id}"]`);
    if (!el) return;
    el.textContent = val || '—';
    el.className = `detail-value${cls ? ' ' + cls : ''}${!val ? ' none' : ''}`;
  };

  set('student_id', student.student_id, 'mono');
  set('name', student.name);
  set('date_of_birth', formatDate(student.date_of_birth));
  set('email', student.email);
  set('phone', student.phone);

  // Wire the Edit button inside detail modal
  const editBtn = modal.querySelector('#detail-edit-btn');
  if (editBtn) {
    editBtn.onclick = () => {
      closeModal('modal-detail');
      openEditModal(student);
    };
  }

  openModal('modal-detail');
}

/* =========================================================================
   Add student modal
   ========================================================================= */
function clearForm(formId) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.reset();
  form.querySelectorAll('.form-control').forEach(el => el.classList.remove('error'));
  form.querySelectorAll('.form-error').forEach(el => {
    el.textContent = '';
    el.classList.remove('visible');
  });
}

function setFieldError(form, fieldName, message) {
  const input = form.querySelector(`[name="${fieldName}"]`);
  const errorEl = form.querySelector(`[data-error="${fieldName}"]`);
  if (input) input.classList.add('error');
  if (errorEl) { errorEl.textContent = message; errorEl.classList.add('visible'); }
}

function clearFieldErrors(form) {
  form.querySelectorAll('.form-control').forEach(el => el.classList.remove('error'));
  form.querySelectorAll('.form-error').forEach(el => {
    el.textContent = '';
    el.classList.remove('visible');
  });
}

function collectFormPayload(form) {
  const data = new FormData(form);
  const payload = {};
  for (const [k, v] of data.entries()) {
    payload[k] = v.trim() === '' ? null : v.trim();
  }
  return payload;
}

async function handleAddSubmit(e) {
  e.preventDefault();
  const form = document.getElementById('form-add');
  clearFieldErrors(form);

  const payload = collectFormPayload(form);
  const submitBtn = form.querySelector('[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Adding…';

  try {
    await api.create(payload);
    closeModal('modal-add');
    clearForm('form-add');
    toast.success('Student added', `${payload.name} was added successfully.`);
    await loadStudents();
  } catch (err) {
    if (err instanceof ApiError) {
      // Try to map Pydantic validation errors to fields
      handleValidationError(form, err);
    } else {
      toast.error('Failed to add student', err.message);
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Add Student';
  }
}

/* =========================================================================
   Edit student modal
   ========================================================================= */
function openEditModal(student) {
  const form = document.getElementById('form-edit');
  clearFieldErrors(form);

  // Pre-fill fields
  const set = (name, val) => {
    const el = form.querySelector(`[name="${name}"]`);
    if (el) el.value = val || '';
  };
  set('name', student.name);
  set('date_of_birth', student.date_of_birth);
  set('email', student.email || '');
  set('phone', student.phone || '');

  // Store current student_id on the form for submission
  form.dataset.studentId = student.student_id;

  // Update modal title to show which student we're editing
  const titleEl = document.querySelector('#modal-edit .modal-title');
  if (titleEl) titleEl.textContent = `Edit — ${student.name}`;

  openModal('modal-edit');
}

async function handleEditSubmit(e) {
  e.preventDefault();
  const form = document.getElementById('form-edit');
  clearFieldErrors(form);

  const studentId = form.dataset.studentId;
  if (!studentId) { toast.error('No student selected', ''); return; }

  // Build the payload with only the fields that are set.
  // If a field is cleared to empty, send null explicitly so the backend
  // contact guard can evaluate the resulting state.
  const raw = collectFormPayload(form);
  const payload = {};
  for (const [k, v] of Object.entries(raw)) {
    // Always include the field — the backend handles null-clearing
    payload[k] = v;
  }

  const submitBtn = form.querySelector('[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Saving…';

  try {
    await api.update(studentId, payload);
    closeModal('modal-edit');
    toast.success('Student updated', 'Changes were saved successfully.');
    await loadStudents();
  } catch (err) {
    if (err instanceof ApiError) {
      handleValidationError(form, err);
    } else {
      toast.error('Failed to save changes', err.message);
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Save Changes';
  }
}

/* =========================================================================
   Validation error display
   ========================================================================= */
function handleValidationError(form, err) {
  const data = err.data || {};

  if (err.status === 409) {
    // Duplicate student_id — only relevant on create form
    const idInput = form.querySelector('[name="student_id"]');
    if (idInput) {
      setFieldError(form, 'student_id', err.message);
    } else {
      toast.error('Conflict', err.message);
    }
    return;
  }

  if (err.status === 422 && data.detail && Array.isArray(data.detail)) {
    let shown = false;
    data.detail.forEach(issue => {
      const loc = issue.loc || [];
      const fieldName = loc[loc.length - 1];
      const msg = issue.msg || 'Invalid value';
      if (fieldName && form.querySelector(`[name="${fieldName}"]`)) {
        setFieldError(form, fieldName, msg.replace(/^Value error, /, ''));
        shown = true;
      }
    });
    if (!shown) {
      // Model-level validator — show as general error
      const firstMsg = data.detail[0]?.msg || err.message;
      toast.error('Validation error', firstMsg.replace(/^Value error, /, ''));
    }
    return;
  }

  // Generic error (422 string, 500, etc.)
  toast.error('Error', err.message);
}

/* =========================================================================
   Delete confirmation modal
   ========================================================================= */
let pendingDeleteId = null;

function openDeleteConfirm(student) {
  pendingDeleteId = student.student_id;

  const modal = document.getElementById('modal-delete');
  const nameEl = modal.querySelector('.confirm-name');
  const idEl   = modal.querySelector('.confirm-student-id');
  if (nameEl) nameEl.textContent = student.name;
  if (idEl) idEl.textContent = student.student_id;

  openModal('modal-delete');
}

async function handleDeleteConfirm() {
  if (!pendingDeleteId) return;
  const id = pendingDeleteId;
  pendingDeleteId = null;
  closeModal('modal-delete');

  try {
    const deleted = await api.delete(id);
    if (deleted) {
      toast.success('Student deleted', `Record ${id} was removed.`);
      await loadStudents();
    } else {
      toast.warning('Not found', `Student ${id} was already removed.`);
      await loadStudents();
    }
  } catch (err) {
    toast.error('Delete failed', err.message);
  }
}

/* =========================================================================
   Search & sort wiring
   ========================================================================= */
function wireSearch() {
  const input = document.getElementById('search-input');
  if (!input) return;
  input.addEventListener('input', () => {
    state.searchQuery = input.value;
    renderTable();
  });
}

function wireSort() {
  document.querySelectorAll('th[data-col]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (state.sortCol === col) {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortCol = col;
        state.sortDir = 'asc';
      }
      renderTable();
    });
    th.setAttribute('tabindex', '0');
    th.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); th.click(); }
    });
  });
}

/* =========================================================================
   Mobile sidebar toggle
   ========================================================================= */
function wireSidebar() {
  const menuBtn = document.getElementById('sidebar-toggle');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (!menuBtn || !sidebar) return;

  menuBtn.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    overlay.classList.toggle('open');
  });
  overlay.addEventListener('click', () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
  });
}

/* =========================================================================
   Boot — wire all events and load data
   ========================================================================= */
document.addEventListener('DOMContentLoaded', () => {
  // Sidebar
  wireSidebar();

  // Search
  wireSearch();

  // Sort headers
  wireSort();

  // Refresh button
  const refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', loadStudents);

  // Add student
  const addBtn = document.getElementById('btn-add');
  if (addBtn) addBtn.addEventListener('click', () => {
    clearForm('form-add');
    openModal('modal-add');
  });

  // Add form submit
  const formAdd = document.getElementById('form-add');
  if (formAdd) formAdd.addEventListener('submit', handleAddSubmit);

  // Edit form submit
  const formEdit = document.getElementById('form-edit');
  if (formEdit) formEdit.addEventListener('submit', handleEditSubmit);

  // Modal close buttons
  document.querySelectorAll('[data-close-modal]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.closeModal));
  });

  // Delete confirm button
  const confirmDelBtn = document.getElementById('btn-confirm-delete');
  if (confirmDelBtn) confirmDelBtn.addEventListener('click', handleDeleteConfirm);

  // Initial data load
  loadStudents();
});
