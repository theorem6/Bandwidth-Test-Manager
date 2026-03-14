<script lang="ts">
  import { auth } from './lib/auth';
  import { loginWithCredentials } from './lib/api';

  let username = '';
  let password = '';
  let error = '';
  let loading = false;

  async function submit() {
    error = '';
    const u = username.trim();
    const p = password;
    if (!u || !p) {
      error = 'Enter username and password';
      return;
    }
    loading = true;
    try {
      const user = await loginWithCredentials(u, p);
      auth.setUser(user);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Login failed';
    } finally {
      loading = false;
    }
  }
</script>

<div class="login-page">
  <div class="login-card card shadow">
    <div class="card-body p-4">
      <h2 class="h4 mb-3"><i class="bi bi-speedometer2 me-2"></i>Bandwidth Test Manager</h2>
      <p class="text-muted small mb-4">Sign in to continue.</p>
      <form on:submit|preventDefault={submit}>
        <div class="mb-3">
          <label for="login-user" class="form-label">Username</label>
          <input id="login-user" type="text" class="form-control" bind:value={username} placeholder="bwadmin" autocomplete="username" />
        </div>
        <div class="mb-4">
          <label for="login-pass" class="form-label">Password</label>
          <input id="login-pass" type="password" class="form-control" bind:value={password} placeholder="••••••••" autocomplete="current-password" />
        </div>
        {#if error}
          <div class="alert alert-danger py-2 mb-3" role="alert">{error}</div>
        {/if}
        <button type="submit" class="btn btn-primary w-100" disabled={loading}>
          {#if loading}
            <span class="spinner-border spinner-border-sm me-1" role="status"></span>
          {/if}
          Sign in
        </button>
      </form>
      <p class="small text-muted mt-3 mb-0">Admin: bwadmin / unl0ck — Read-only: user / user</p>
    </div>
  </div>
</div>

<style>
  .login-page {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f0f2f5;
    padding: 1rem;
  }
  .login-card {
    width: 100%;
    max-width: 360px;
    border: none;
    border-radius: 12px;
  }
</style>
