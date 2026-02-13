<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getAuthStatus, getConfiguredLibraries, syncLibrary, getSyncStatus } from '$lib/api/client';
	import type { ConfiguredLibrary } from '$lib/api/client';

	let loading = $state(true);
	let connected = $state(false);
	let libraries = $state<ConfiguredLibrary[]>([]);
	let syncingLibraryId = $state<number | null>(null);
	let syncMessage = $state('');

	async function handleSync(libraryId: number) {
		syncingLibraryId = libraryId;
		syncMessage = 'Starting sync...';
		try {
			await syncLibrary(libraryId);
			// Poll for completion
			while (true) {
				await new Promise((r) => setTimeout(r, 1000));
				const status = await getSyncStatus();
				if (!status.is_running) {
					syncMessage = status.message || 'Sync complete';
					break;
				}
				syncMessage = status.message || `Syncing ${status.progress}/${status.total}...`;
			}
			libraries = await getConfiguredLibraries();
		} catch (e: any) {
			syncMessage = `Sync failed: ${e.message}`;
		} finally {
			setTimeout(() => {
				syncingLibraryId = null;
				syncMessage = '';
			}, 3000);
		}
	}

	onMount(async () => {
		try {
			const status = await getAuthStatus();
			connected = status.connected;
			if (!connected) {
				goto('/admin/setup');
				return;
			}
			libraries = await getConfiguredLibraries();
		} catch {
			goto('/admin/setup');
			return;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Admin - Titantron</title>
</svelte:head>

{#if loading}
	<div class="flex items-center justify-center h-[calc(100vh-6.5rem)]">
		<p class="text-titan-text-muted">Loading...</p>
	</div>
{:else}
	<div class="max-w-4xl mx-auto p-6">
		<header class="mb-8">
			<h1 class="text-3xl font-bold">
				<span class="text-titan-accent">TITAN</span><span class="text-titan-gold">TRON</span>
			</h1>
			<p class="text-titan-text-muted mt-1">Pro Wrestling Video Organizer</p>
		</header>

		{#if libraries.length === 0}
			<div class="bg-titan-surface border border-titan-border rounded-lg p-6 text-center">
				<p class="text-titan-text-muted">No libraries configured yet.</p>
				<a href="/admin/setup" class="inline-block mt-3 px-4 py-2 bg-titan-accent rounded font-medium hover:opacity-90">
					Set Up Libraries
				</a>
			</div>
		{:else}
			<!-- Quick Actions -->
			<div class="grid gap-4 sm:grid-cols-2 mb-8">
				<a href="/browse" class="bg-titan-surface border border-titan-border rounded-lg p-5 hover:bg-titan-surface-hover transition-colors block">
					<h3 class="font-semibold text-lg mb-1">Browse Events</h3>
					<p class="text-sm text-titan-text-muted">View matched events and match cards</p>
				</a>
				<a href="/admin/matching" class="bg-titan-surface border border-titan-border rounded-lg p-5 hover:bg-titan-surface-hover transition-colors block">
					<h3 class="font-semibold text-lg mb-1">Match Videos</h3>
					<p class="text-sm text-titan-text-muted">Match videos to Cagematch events</p>
				</a>
			</div>

			<!-- Libraries -->
			<section>
				<h2 class="text-xl font-semibold mb-4">Libraries</h2>
				<div class="grid gap-4">
					{#each libraries as lib}
						<div class="bg-titan-surface border border-titan-border rounded-lg p-4">
							<div class="flex items-center justify-between">
								<div>
									<h3 class="font-semibold">{lib.name}</h3>
									<p class="text-sm text-titan-text-muted">{lib.promotion_name}</p>
								</div>
								<div class="flex items-center gap-4">
									<button
										onclick={() => handleSync(lib.id)}
										disabled={syncingLibraryId !== null}
										class="text-sm px-3 py-1 bg-titan-accent rounded hover:opacity-90 disabled:opacity-50"
									>
										{syncingLibraryId === lib.id ? 'Syncing...' : 'Sync'}
									</button>
									<div class="text-right">
										<p class="text-lg font-bold">{lib.video_count}</p>
										<p class="text-xs text-titan-text-muted">videos</p>
									</div>
								</div>
							</div>
							{#if syncingLibraryId === lib.id && syncMessage}
								<p class="text-xs text-titan-accent mt-2">{syncMessage}</p>
							{:else if lib.last_synced}
								<p class="text-xs text-titan-text-muted mt-2">
									Last synced: {new Date(lib.last_synced).toLocaleString()}
								</p>
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{/if}
	</div>
{/if}
