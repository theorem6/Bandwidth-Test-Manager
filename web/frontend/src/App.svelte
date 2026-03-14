<script lang="ts">
  import { onMount } from 'svelte';
  import Dashboard from './Dashboard.svelte';
  import Scheduler from './Scheduler.svelte';
  import Settings from './Settings.svelte';
  import Setup from './Setup.svelte';
  import { getStatus, schedulerStart, schedulerStop, loginWithCredentials } from './lib/api';
  import { auth } from './lib/auth';
  import { loading } from './lib/stores';

  type View = 'dashboard' | 'scheduler' | 'settings' | 'setup';
  let currentView: View = 'dashboard';
  let scheduled = false;
  let toastMessage = '';
  let toastType: 'success' | 'error' = 'success';
  let showToast = false;
  let sidebarOpen = false;
  let showLoginModal = false;
  let loginUsername = '';
  let loginPassword = '';
  let loginError = '';
  let loginLoading = false;
  let scheduleBusy = false;
  $: loadingVal = $loading;
  $: user = $auth;

  function setToast(msg: string, type: 'success' | 'error' = 'success') {
    toastMessage = msg;
    toastType = type;
    showToast = true;
    setTimeout(() => (showToast = false), 3500);
  }

  async function loadStatus() {
    try {
      const r = await getStatus();
      scheduled = !!r.scheduled;
    } catch {
      scheduled = false;
    }
  }

  async function toggleSchedule() {
    if (scheduleBusy) return;
    scheduleBusy = true;
    try {
      if (scheduled) {
        const r = await schedulerStop();
        if (r.ok) {
          await loadStatus();
          setToast('Schedule stopped.');
        } else {
          setToast(r.error || 'Failed to stop', 'error');
        }
      } else {
        const r = await schedulerStart();
        if (r.ok) {
          await loadStatus();
          setToast(r.message || 'Schedule started. Tests run at :05 every hour.');
        } else {
          setToast(r.error || 'Failed to start', 'error');
        }
      }
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Failed', 'error');
    } finally {
      scheduleBusy = false;
    }
  }

  async function submitLogin() {
    loginError = '';
    const u = loginUsername.trim();
    const p = loginPassword;
    if (!u || !p) {
      loginError = 'Enter username and password';
      return;
    }
    loginLoading = true;
    try {
      const authUser = await loginWithCredentials(u, p);
      auth.setUser(authUser);
      showLoginModal = false;
      loginUsername = '';
      loginPassword = '';
    } catch (e) {
      loginError = e instanceof Error ? e.message : 'Login failed';
    } finally {
      loginLoading = false;
    }
  }

  onMount(() => {
    loadStatus();
    const id = setInterval(loadStatus, 30000);
    return () => clearInterval(id);
  });
</script>

{#if user}
  <!-- Logged in: full app with sidebar -->
  <div class="app">
    <nav class="navbar navbar-expand navbar-dark bg-primary">
      <div class="container-fluid">
        <button
          type="button"
          class="btn btn-link d-lg-none text-white text-decoration-none me-2 p-2"
          aria-label="Menu"
          on:click={() => (sidebarOpen = !sidebarOpen)}
        >
          <i class="bi bi-list" style="font-size:1.5rem"></i>
        </button>
        <a class="navbar-brand fw-bold" href="/netperf/"><i class="bi bi-speedometer2 me-2"></i>Bandwidth Test Manager</a>
        <div class="navbar-nav ms-auto align-items-center">
          <span class="navbar-text me-2 me-md-3">
            <span class="badge-dot {scheduled ? 'running' : 'stopped'}"></span>
            <span>{scheduled ? 'Running' : 'Stopped'}</span>
          </span>
          <span class="navbar-text me-2 text-white-50 small">{user.username} ({user.role})</span>
          <button type="button" class="btn btn-outline-light btn-sm" on:click={() => auth.logout()} title="Sign out">Sign out</button>
        </div>
      </div>
    </nav>

    <button type="button" class="sidebar-backdrop" class:open={sidebarOpen} on:click={() => (sidebarOpen = false)} aria-label="Close menu" title="Close menu"></button>
    <div class="d-flex">
      <aside class="sidebar" class:open={sidebarOpen} role="navigation">
        <nav class="nav flex-column pt-3">
          <a href="/netperf/" class="nav-link" class:active={currentView === 'dashboard'} on:click|preventDefault={() => { currentView = 'dashboard'; sidebarOpen = false; }}>
            <i class="bi bi-graph-up"></i> Dashboard
          </a>
          <a href="/netperf/" class="nav-link" class:active={currentView === 'scheduler'} on:click|preventDefault={() => { currentView = 'scheduler'; sidebarOpen = false; }}>
            <i class="bi bi-clock-history"></i> Scheduler
          </a>
          <a href="/netperf/" class="nav-link" class:active={currentView === 'settings'} on:click|preventDefault={() => { currentView = 'settings'; sidebarOpen = false; }}>
            <i class="bi bi-gear"></i> Settings
          </a>
          <a href="/netperf/" class="nav-link" class:active={currentView === 'setup'} on:click|preventDefault={() => { currentView = 'setup'; sidebarOpen = false; }}>
            <i class="bi bi-tools"></i> Setup
          </a>
        </nav>
      </aside>

      <main class="content">
        <h1 class="h4 mb-3 mb-md-4 text-dark">
          {currentView === 'dashboard' ? 'Dashboard' : currentView === 'scheduler' ? 'Scheduler' : currentView === 'settings' ? 'Settings' : 'Setup'}
        </h1>
        {#if currentView === 'dashboard'}
          <Dashboard onToast={setToast} showAdminActions={true} />
        {:else if currentView === 'scheduler'}
          <Scheduler {loadStatus} onToast={setToast} />
        {:else if currentView === 'settings'}
          <Settings onToast={setToast} />
        {:else}
          <Setup onToast={setToast} />
        {/if}
      </main>
    </div>
  </div>
{:else}
  <!-- Landing: read-only dashboard, no menu, toggle + Login button -->
  <div class="app landing">
    <nav class="navbar navbar-expand navbar-dark bg-primary">
      <div class="container-fluid">
        <a class="navbar-brand fw-bold" href="/netperf/"><i class="bi bi-speedometer2 me-2"></i>Bandwidth Test Manager</a>
        <div class="navbar-nav ms-auto align-items-center gap-2">
          <span class="navbar-text me-2">
            <span class="badge-dot {scheduled ? 'running' : 'stopped'}"></span>
            <span>{scheduled ? 'Tests on' : 'Tests off'}</span>
          </span>
          <button
            type="button"
            class="btn btn-sm {scheduled ? 'btn-outline-light' : 'btn-light'}"
            disabled={scheduleBusy}
            on:click={toggleSchedule}
            title={scheduled ? 'Stop scheduled tests' : 'Start scheduled tests'}
          >
            {#if scheduleBusy}
              <span class="spinner-border spinner-border-sm me-1" role="status"></span>
            {/if}
            {scheduled ? 'Turn off' : 'Turn on'}
          </button>
          <button type="button" class="btn btn-light btn-sm" on:click={() => (showLoginModal = true)}>Login</button>
        </div>
      </div>
    </nav>

    <main class="content content-full">
      <h1 class="h4 mb-3 mb-md-4 text-dark">Dashboard</h1>
      <Dashboard onToast={setToast} showAdminActions={false} />
    </main>
  </div>
{/if}

{#if showLoginModal}
  <div class="modal-overlay" role="dialog" aria-modal="true" aria-label="Login">
    <div class="modal-card card shadow">
      <div class="card-body p-4">
        <h2 class="h5 mb-3">Admin login</h2>
        <p class="text-muted small mb-3">Sign in to access Scheduler, Settings, and Setup.</p>
        <form on:submit|preventDefault={submitLogin}>
          <div class="mb-3">
            <label for="login-user" class="form-label">Username</label>
            <input id="login-user" type="text" class="form-control" bind:value={loginUsername} placeholder="bwadmin" autocomplete="username" />
          </div>
          <div class="mb-3">
            <label for="login-pass" class="form-label">Password</label>
            <input id="login-pass" type="password" class="form-control" bind:value={loginPassword} placeholder="••••••••" autocomplete="current-password" />
          </div>
          {#if loginError}
            <div class="alert alert-danger py-2 mb-3" role="alert">{loginError}</div>
          {/if}
          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary" disabled={loginLoading}>
              {#if loginLoading}
                <span class="spinner-border spinner-border-sm me-1" role="status"></span>
              {/if}
              Sign in
            </button>
            <button type="button" class="btn btn-outline-secondary" on:click={() => { showLoginModal = false; loginError = ''; }}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  </div>
{/if}

{#if showToast}
  <div class="toast-msg toast align-items-center text-white border-0 {toastType === 'error' ? 'bg-danger' : 'bg-success'}">
    <div class="d-flex"><div class="toast-body">{toastMessage}</div></div>
  </div>
{/if}
{#if loadingVal}
  <div class="loading-overlay">
    <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading</span></div>
  </div>
{/if}

<style>
  :global(body) { background: #f0f2f5; min-height: 100vh; overflow-x: hidden; margin: 0; }
  .app { min-height: 100vh; }
  .app.landing .content-full { max-width: 1400px; margin: 0 auto; }
  :global(.navbar) { box-shadow: 0 2px 8px rgba(0,0,0,.1); }
  .sidebar {
    width: 220px; min-height: calc(100vh - 56px); background: #1e3a5f; flex-shrink: 0;
    transition: transform 0.2s ease;
  }
  :global(.sidebar .nav-link) {
    color: rgba(255,255,255,.85); padding: 0.6rem 1rem; border-radius: 8px; margin: 2px 8px;
  }
  :global(.sidebar .nav-link:hover) { background: rgba(255,255,255,.1); color: #fff; }
  :global(.sidebar .nav-link.active) { background: #0d6efd; color: #fff; }
  :global(.sidebar .nav-link i) { margin-right: 10px; }
  .content { flex: 1; min-width: 0; padding: 1rem 1.25rem; max-width: 1400px; }
  :global(.badge-dot) { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  :global(.badge-dot.running) { background: #198754; }
  :global(.badge-dot.stopped) { background: #6c757d; }
  .sidebar-backdrop { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 40; border: none; cursor: pointer; }
  .sidebar-backdrop.open { display: block; }
  .modal-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 9998; display: flex; align-items: center; justify-content: center; padding: 1rem;
  }
  .modal-card { width: 100%; max-width: 360px; border: none; border-radius: 12px; }
  .toast-msg { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); z-index: 9999; max-width: 90vw; }
  .loading-overlay {
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,.4); z-index: 9999; display: flex; align-items: center; justify-content: center;
  }
  @media (max-width: 991.98px) {
    .sidebar { position: fixed; top: 56px; left: 0; bottom: 0; z-index: 50; transform: translateX(-100%); box-shadow: 4px 0 12px rgba(0,0,0,.15); }
    .sidebar.open { transform: translateX(0); }
    .sidebar-backdrop.open { display: block; }
  }
</style>
