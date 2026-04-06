<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchVoiceSchema, type VoiceDomainSchema } from './lib/api';

  let schema: VoiceDomainSchema | null = null;
  let error = '';
  let loading = true;

  onMount(async () => {
    try {
      schema = await fetchVoiceSchema();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load';
    } finally {
      loading = false;
    }
  });
</script>

<div class="voice-ref">
  <p class="text-muted small mb-4">
    Minimal voice / SIP domain model (bounded contexts: identity & tenancy, numbers, emergency, porting). This page loads
    <code>/api/voice/schema</code> — no live carrier calls.
  </p>

  {#if loading}
    <p class="text-muted">Loading schema…</p>
  {:else if error}
    <div class="alert alert-danger">{error}</div>
  {:else if schema}
    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">Bounded contexts</h2>
      <div class="table-responsive">
        <table class="table table-sm table-bordered align-middle">
          <thead><tr><th>Context</th><th>Entities</th></tr></thead>
          <tbody>
            {#each schema.bounded_contexts as bc}
              <tr>
                <td><strong>{bc.label}</strong><br /><span class="small text-muted">{bc.id}</span></td>
                <td>{bc.entities.join(', ')}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">Entities</h2>
      <div class="table-responsive">
        <table class="table table-sm table-bordered">
          <thead><tr><th>Entity</th><th>Purpose</th></tr></thead>
          <tbody>
            {#each Object.entries(schema.entities) as [name, desc]}
              <tr><td><code>{name}</code></td><td>{desc}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">State machines</h2>
      {#each Object.entries(schema.state_machines) as [smKey, smVal]}
        {#if smKey === 'notes'}
          <ul class="small text-warning-emphasis">
            {#each smVal as n}<li>{n}</li>{/each}
          </ul>
        {:else}
          <p class="mb-1"><strong>{smKey}</strong></p>
          <ul class="small">
            {#each smVal as v}<li><code>{v}</code></li>{/each}
          </ul>
        {/if}
      {/each}
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">Carrier comparison</h2>
      <div class="table-responsive">
        <table class="table table-sm table-bordered">
          <thead>
            <tr>
              <th>Dimension</th>
              <th>Bandwidth</th>
              <th>Telnyx</th>
              <th>Twilio</th>
            </tr>
          </thead>
          <tbody>
            {#each schema.carrier_comparison as row}
              <tr>
                <td>{row.dimension}</td>
                <td>{row.bandwidth}</td>
                <td>{row.telnyx}</td>
                <td>{row.twilio}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="small">{schema.pragmatic_recommendation}</p>
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">ArcGIS</h2>
      <p class="small">{schema.arcgis.note}</p>
      <ul class="small">
        {#each schema.arcgis.uses as u}<li>{u}</li>{/each}
      </ul>
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">Phased rollout</h2>
      <ul class="small">
        {#each schema.phased_rollout as p}
          <li><strong>Phase {p.phase}</strong> — {p.scope}</li>
        {/each}
      </ul>
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">Build order</h2>
      <ol class="small">
        {#each schema.first_build_in_code as step}<li>{step}</li>{/each}
      </ol>
    </section>

    <section class="mb-4">
      <h2 class="h6 text-uppercase text-muted">Enums (API)</h2>
      <pre class="small bg-body-secondary p-2 rounded border">{JSON.stringify(schema.enums, null, 2)}</pre>
    </section>
  {/if}
</div>

<style>
  .voice-ref :global(pre) { max-height: 320px; overflow: auto; }
  .voice-ref :global(.text-warning-emphasis) { color: var(--bs-warning-text-emphasis, #664d03); }
</style>
