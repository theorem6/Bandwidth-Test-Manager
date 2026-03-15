<script lang="ts">
  import Dashboard from './Dashboard.svelte';
  import { getRemoteNode, updateRemoteNode, getRemoteScript } from './lib/api';
  import type { RemoteNode } from './lib/api';

  export let nodeId: string;
  export let onToast: (msg: string, type?: 'success' | 'error') => void = () => {};

  let node: RemoteNode | null = null;
  let loading = true;
  let editName = '';
  let editLocation = '';
  let editAddress = '';
  let saveLoading = false;
  let saveError = '';
  let scriptDownloading = false;

  async function loadNode() {
    loading = true;
    try {
      node = await getRemoteNode(nodeId);
      if (node) {
        editName = node.name;
        editLocation = node.location || '';
        editAddress = node.address || '';
      }
    } catch {
      node = null;
    } finally {
      loading = false;
    }
  }

  $: if (nodeId) {
    loadNode();
  }

  async function save() {
    if (!nodeId || saveLoading) return;
    saveLoading = true;
    saveError = '';
    try {
      const r = await updateRemoteNode(nodeId, {
        name: editName.trim(),
        location: editLocation.trim(),
        address: editAddress.trim(),
      });
      if (r.ok && r.node) {
        node = r.node;
        editName = node.name;
        editLocation = node.location || '';
        editAddress = node.address || '';
        onToast('Node updated.');
      } else {
        saveError = r.error || 'Update failed';
      }
    } catch (e) {
      saveError = e instanceof Error ? e.message : 'Update failed';
    } finally {
      saveLoading = false;
    }
  }

  async function downloadScript() {
    if (scriptDownloading) return;
    scriptDownloading = true;
    try {
      const script = await getRemoteScript(nodeId);
      const blob = new Blob([script], { type: 'application/x-sh' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `bwm-remote-agent-${nodeId}.sh`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onToast('Script downloaded.');
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Download failed', 'error');
    } finally {
      scriptDownloading = false;
    }
  }
</script>

{#if loading}
  <p class="text-muted">Loading node…</p>
{:else if !node}
  <p class="text-danger">Node not found.</p>
{:else}
  <div class="card mb-4">
    <div class="card-header">Configure node</div>
    <div class="card-body">
      <p class="text-muted small mb-3">Edit name, location, and IP/hostname. Run the script on the remote machine every hour (cron <code>5 * * * *</code>) so data is sent regularly.</p>
      <form on:submit|preventDefault={save} aria-label="Configure node">
        <div class="row g-2 align-items-end mb-2">
          <div class="col-md-3">
            <label class="form-label small mb-0" for="node-edit-name">Name</label>
            <input id="node-edit-name" type="text" class="form-control form-control-sm" bind:value={editName} />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-0" for="node-edit-location">Location</label>
            <input id="node-edit-location" type="text" class="form-control form-control-sm" bind:value={editLocation} placeholder="e.g. Chicago, IL" />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-0" for="node-edit-address">IP / hostname</label>
            <input id="node-edit-address" type="text" class="form-control form-control-sm font-monospace" bind:value={editAddress} placeholder="e.g. 192.168.1.1" />
          </div>
          <div class="col-auto">
            <button type="submit" class="btn btn-primary btn-sm" disabled={saveLoading}>{saveLoading ? 'Saving…' : 'Save'}</button>
            <button type="button" class="btn btn-outline-secondary btn-sm ms-1" on:click={downloadScript} disabled={scriptDownloading}>{scriptDownloading ? '…' : 'Download script'}</button>
          </div>
        </div>
        {#if saveError}
          <p class="small text-danger mb-0">{saveError}</p>
        {/if}
      </form>
    </div>
  </div>

  <Dashboard onToast={onToast} showAdminActions={false} probeId={nodeId} />
{/if}
