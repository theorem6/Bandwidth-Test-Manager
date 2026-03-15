<script lang="ts">
  import { onMount } from 'svelte';
  import { getRemoteNodes, createRemoteNode, deleteRemoteNode, getRemoteScript } from './lib/api';
  import type { RemoteNode } from './lib/api';

  export let onToast: (msg: string, type?: 'success' | 'error') => void = () => {};
  /** Call when user clicks a node to open its dashboard. */
  export let onOpenNode: (nodeId: string, nodeName: string) => void = () => {};

  let nodes: RemoteNode[] = [];
  let loading = true;
  let error = '';
  let addName = '';
  let addLocation = '';
  let addLoading = false;
  let addError = '';
  let createdToken: string | null = null;
  let createdNode: (RemoteNode & { token?: string }) | null = null;
  let scriptDownloading: string | null = null;
  let deleteConfirm: string | null = null;

  async function loadNodes() {
    loading = true;
    error = '';
    try {
      const r = await getRemoteNodes();
      nodes = r.nodes || [];
    } catch (e) {
      nodes = [];
      error = e instanceof Error ? e.message : 'Failed to load nodes';
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadNodes();
  });

  async function handleAdd() {
    const name = addName.trim();
    if (!name) {
      addError = 'Name is required';
      return;
    }
    addLoading = true;
    addError = '';
    createdToken = null;
    createdNode = null;
    try {
      const r = await createRemoteNode(name, addLocation.trim());
      if (r.ok && r.node) {
        createdNode = r.node;
        createdToken = r.node.token || null;
        addName = '';
        addLocation = '';
        onToast(r.message || 'Node created. Download the script and run it on the remote machine.');
        loadNodes();
      } else {
        addError = r.error || 'Failed to create node';
      }
    } catch (e) {
      addError = e instanceof Error ? e.message : 'Failed';
    } finally {
      addLoading = false;
    }
  }

  function clearCreated() {
    createdToken = null;
    createdNode = null;
  }

  async function downloadScript(nodeId: string) {
    if (scriptDownloading) return;
    scriptDownloading = nodeId;
    try {
      const script = await getRemoteScript(nodeId);
      const blob = new Blob([script], { type: 'application/x-sh' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `bwm-remote-agent-${nodeId}.sh`;
      a.click();
      URL.revokeObjectURL(url);
      onToast('Script downloaded.');
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Download failed', 'error');
    } finally {
      scriptDownloading = null;
    }
  }

  async function handleDelete(nodeId: string) {
    try {
      const r = await deleteRemoteNode(nodeId);
      if (r.ok) {
        onToast('Node removed.');
        deleteConfirm = null;
        loadNodes();
      } else {
        onToast(r.error || 'Delete failed', 'error');
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : 'Failed', 'error');
    }
  }

  function formatLastSeen(iso: string) {
    if (!iso) return 'Never';
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch {
      return iso;
    }
  }
</script>

<div class="card mb-4">
  <div class="card-header">Remote nodes</div>
  <div class="card-body">
    <p class="text-muted small mb-3">
      Deploy a script on remote machines (POPs, customer sites) to run speedtest/iperf and report results back to this server. Each node has its own dashboard.
    </p>
    {#if loading}
      <p class="text-muted mb-0">Loading…</p>
    {:else if error}
      <p class="text-danger mb-0">{error}</p>
    {:else}
      <div class="table-responsive">
        <table class="table table-sm table-borderless mb-0">
          <thead>
            <tr>
              <th>Name</th>
              <th>Location</th>
              <th>Last seen</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each nodes as node (node.node_id)}
              <tr>
                <td>
                  <button type="button" class="btn btn-link p-0 text-decoration-none text-start border-0" on:click={() => onOpenNode(node.node_id, node.name)}>
                    {node.name}
                  </button>
                </td>
                <td class="text-muted small">{node.location || '—'}</td>
                <td class="small">{formatLastSeen(node.last_seen_at)}</td>
                <td class="text-end">
                  <button type="button" class="btn btn-outline-primary btn-sm me-1" on:click={() => downloadScript(node.node_id)} disabled={scriptDownloading === node.node_id} title="Download agent script">
                    {scriptDownloading === node.node_id ? '…' : 'Download script'}
                  </button>
                  {#if deleteConfirm === node.node_id}
                    <button type="button" class="btn btn-danger btn-sm" on:click={() => handleDelete(node.node_id)}>Confirm delete</button>
                    <button type="button" class="btn btn-outline-secondary btn-sm ms-1" on:click={() => deleteConfirm = null}>Cancel</button>
                  {:else}
                    <button type="button" class="btn btn-outline-danger btn-sm" on:click={() => deleteConfirm = node.node_id} title="Remove node">Delete</button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if nodes.length === 0}
        <p class="text-muted small mb-0 mt-2">No remote nodes yet. Add one below.</p>
      {/if}
    {/if}
  </div>
</div>

<div class="card mb-4">
  <div class="card-header">Add remote node</div>
  <div class="card-body">
    <p class="text-muted small mb-3">Create a node to get a unique script and token. Run the script on the remote machine (e.g. via cron) so it reports back here.</p>
    <form on:submit|preventDefault={handleAdd} aria-label="Add remote node">
      <div class="row g-2 align-items-end mb-2">
        <div class="col-md-4">
          <label class="form-label small mb-0" for="remote-node-name">Name</label>
          <input id="remote-node-name" type="text" class="form-control form-control-sm" bind:value={addName} placeholder="e.g. Chicago POP" />
        </div>
        <div class="col-md-4">
          <label class="form-label small mb-0" for="remote-node-location">Location (optional)</label>
          <input id="remote-node-location" type="text" class="form-control form-control-sm" bind:value={addLocation} placeholder="e.g. Chicago, IL" />
        </div>
        <div class="col-auto">
          <button type="submit" class="btn btn-primary btn-sm" disabled={addLoading}>Add node</button>
        </div>
      </div>
      {#if addError}
        <p class="small text-danger mb-0">{addError}</p>
      {/if}
    </form>

    {#if createdNode && createdToken}
      <div class="alert alert-success small mt-3 mb-0">
        <strong>Node created:</strong> {createdNode.name} (ID: {createdNode.node_id})<br />
        <strong>Token (save it; shown once):</strong> <code class="user-select-all">{createdToken}</code><br />
        <button type="button" class="btn btn-sm btn-outline-dark mt-2" on:click={() => createdNode && downloadScript(createdNode.node_id)} disabled={scriptDownloading === (createdNode?.node_id ?? '')}>
          Download script for this node
        </button>
        <button type="button" class="btn btn-sm btn-outline-secondary mt-2 ms-2" on:click={clearCreated}>Done</button>
      </div>
    {/if}
  </div>
</div>
