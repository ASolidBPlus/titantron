<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		connect,
		getAuthStatus,
		getJellyfinLibraries,
		getConfiguredLibraries,
		configureLibrary,
		deleteLibrary,
		syncLibrary,
		getSyncStatus,
		type JellyfinLibrary,
		type ConfiguredLibrary,
		type SyncStatus
	} from '$lib/api/client';

	type Step = 'connect' | 'libraries' | 'done';

	let step = $state<Step>('connect');
	let error = $state('');
	let loading = $state(false);

	// Connect step
	let serverUrl = $state('');
	let username = $state('');
	let password = $state('');

	// Libraries step
	let jellyfinLibraries = $state<JellyfinLibrary[]>([]);
	let configuredLibraries = $state<ConfiguredLibrary[]>([]);
	let selectedLibraryId = $state('');
	let promotionId = $state('');
	let promotionName = $state('');
	let promotionAbbr = $state('');

	// Sync
	let syncStatusData = $state<SyncStatus | null>(null);
	let syncPolling = $state(false);

	onMount(async () => {
		try {
			const status = await getAuthStatus();
			if (status.connected) {
				step = 'libraries';
				await loadLibraries();
			}
		} catch {
			// Not connected, stay on connect step
		}
	});

	async function handleConnect() {
		error = '';
		loading = true;
		try {
			await connect({ url: serverUrl, username, password });
			step = 'libraries';
			await loadLibraries();
		} catch (e: any) {
			error = e.message || 'Failed to connect';
		} finally {
			loading = false;
		}
	}

	async function loadLibraries() {
		try {
			jellyfinLibraries = await getJellyfinLibraries();
			configuredLibraries = await getConfiguredLibraries();
		} catch (e: any) {
			error = e.message || 'Failed to load libraries';
		}
	}

	async function handleAddLibrary() {
		if (!selectedLibraryId || !promotionId || !promotionName) return;
		error = '';
		loading = true;
		try {
			const lib = jellyfinLibraries.find((l) => l.id === selectedLibraryId);
			await configureLibrary({
				jellyfin_library_id: selectedLibraryId,
				jellyfin_library_name: lib?.name ?? 'Unknown',
				cagematch_promotion_id: parseInt(promotionId),
				promotion_name: promotionName,
				promotion_abbreviation: promotionAbbr
			});
			selectedLibraryId = '';
			promotionId = '';
			promotionName = '';
			promotionAbbr = '';
			await loadLibraries();
		} catch (e: any) {
			error = e.message || 'Failed to add library';
		} finally {
			loading = false;
		}
	}

	async function handleDeleteLibrary(id: number) {
		try {
			await deleteLibrary(id);
			await loadLibraries();
		} catch (e: any) {
			error = e.message || 'Failed to delete library';
		}
	}

	async function handleSync(libraryId: number) {
		error = '';
		try {
			await syncLibrary(libraryId);
			syncPolling = true;
			pollSyncStatus();
		} catch (e: any) {
			error = e.message || 'Failed to start sync';
		}
	}

	async function pollSyncStatus() {
		while (syncPolling) {
			try {
				syncStatusData = await getSyncStatus();
				if (!syncStatusData.is_running) {
					syncPolling = false;
					await loadLibraries();
				}
			} catch {
				syncPolling = false;
			}
			if (syncPolling) {
				await new Promise((r) => setTimeout(r, 1000));
			}
		}
	}

	function handleDone() {
		goto('/');
	}

	// Filter out already-configured libraries
	let availableLibraries = $derived(
		jellyfinLibraries.filter(
			(jl) => !configuredLibraries.some((cl) => cl.jellyfin_library_id === jl.id)
		)
	);
</script>

<svelte:head>
	<title>Setup - Titantron</title>
</svelte:head>

<div class="max-w-2xl mx-auto p-6">
	<header class="mb-8">
		<h1 class="text-3xl font-bold">
			<span class="text-titan-accent">TITAN</span><span class="text-titan-gold">TRON</span>
		</h1>
		<p class="text-titan-text-muted mt-1">Setup</p>
	</header>

	{#if error}
		<div class="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">
			{error}
		</div>
	{/if}

	{#if step === 'connect'}
		<div class="bg-titan-surface border border-titan-border rounded-lg p-6">
			<h2 class="text-xl font-semibold mb-4">Connect to Jellyfin</h2>
			<form onsubmit={(e) => { e.preventDefault(); handleConnect(); }} class="space-y-4">
				<div>
					<label for="server-url" class="block text-sm text-titan-text-muted mb-1">Server URL</label>
					<input
						id="server-url"
						type="url"
						bind:value={serverUrl}
						placeholder="http://localhost:8096"
						required
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text placeholder:text-titan-text-muted/50 focus:outline-none focus:border-titan-accent"
					/>
				</div>
				<div>
					<label for="username" class="block text-sm text-titan-text-muted mb-1">Username</label>
					<input
						id="username"
						type="text"
						bind:value={username}
						required
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text focus:outline-none focus:border-titan-accent"
					/>
				</div>
				<div>
					<label for="password" class="block text-sm text-titan-text-muted mb-1">Password</label>
					<input
						id="password"
						type="password"
						bind:value={password}
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text focus:outline-none focus:border-titan-accent"
					/>
				</div>
				<button
					type="submit"
					disabled={loading}
					class="w-full py-2 bg-titan-accent rounded font-medium hover:opacity-90 disabled:opacity-50"
				>
					{loading ? 'Connecting...' : 'Connect'}
				</button>
			</form>
		</div>
	{:else if step === 'libraries'}
		<div class="space-y-6">
			<!-- Configured libraries -->
			{#if configuredLibraries.length > 0}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-6">
					<h2 class="text-xl font-semibold mb-4">Configured Libraries</h2>
					<div class="space-y-3">
						{#each configuredLibraries as lib}
							<div class="flex items-center justify-between bg-titan-bg rounded p-3">
								<div>
									<p class="font-medium">{lib.name}</p>
									<p class="text-sm text-titan-text-muted">
										{lib.promotion_name}
										{#if lib.promotion_abbreviation}({lib.promotion_abbreviation}){/if}
										&middot; {lib.video_count} videos
									</p>
								</div>
								<div class="flex items-center gap-2">
									<button
										onclick={() => handleSync(lib.id)}
										disabled={syncPolling}
										class="px-3 py-1 text-sm bg-titan-surface-hover border border-titan-border rounded hover:border-titan-accent disabled:opacity-50"
									>
										Sync
									</button>
									<button
										onclick={() => handleDeleteLibrary(lib.id)}
										class="px-3 py-1 text-sm text-red-400 border border-red-800 rounded hover:bg-red-900/30"
									>
										Remove
									</button>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Sync status -->
			{#if syncStatusData?.is_running}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-4">
					<p class="text-sm text-titan-text-muted">{syncStatusData.message}</p>
					{#if syncStatusData.total}
						<div class="mt-2 w-full bg-titan-bg rounded-full h-2">
							<div
								class="bg-titan-accent h-2 rounded-full transition-all"
								style="width: {((syncStatusData.progress ?? 0) / syncStatusData.total) * 100}%"
							></div>
						</div>
						<p class="text-xs text-titan-text-muted mt-1">
							{syncStatusData.progress} / {syncStatusData.total}
						</p>
					{/if}
				</div>
			{/if}

			<!-- Add library -->
			{#if availableLibraries.length > 0}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-6">
					<h2 class="text-xl font-semibold mb-4">Add Library</h2>
					<form onsubmit={(e) => { e.preventDefault(); handleAddLibrary(); }} class="space-y-4">
						<div>
							<label for="library-select" class="block text-sm text-titan-text-muted mb-1">Jellyfin Library</label>
							<select
								id="library-select"
								bind:value={selectedLibraryId}
								required
								class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text focus:outline-none focus:border-titan-accent"
							>
								<option value="">Select a library...</option>
								{#each availableLibraries as lib}
									<option value={lib.id}>{lib.name} ({lib.collection_type})</option>
								{/each}
							</select>
						</div>
						<div class="grid grid-cols-2 gap-4">
							<div>
								<label for="promo-name" class="block text-sm text-titan-text-muted mb-1">Promotion Name</label>
								<input
									id="promo-name"
									type="text"
									bind:value={promotionName}
									placeholder="World Wrestling Entertainment"
									required
									class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text placeholder:text-titan-text-muted/50 focus:outline-none focus:border-titan-accent"
								/>
							</div>
							<div>
								<label for="promo-abbr" class="block text-sm text-titan-text-muted mb-1">Abbreviation</label>
								<input
									id="promo-abbr"
									type="text"
									bind:value={promotionAbbr}
									placeholder="WWE"
									class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text placeholder:text-titan-text-muted/50 focus:outline-none focus:border-titan-accent"
								/>
							</div>
						</div>
						<div>
							<label for="promo-id" class="block text-sm text-titan-text-muted mb-1">
								Cagematch Promotion ID
							</label>
							<input
								id="promo-id"
								type="number"
								bind:value={promotionId}
								placeholder="e.g. 1 for WWE, 2287 for AEW"
								required
								class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-titan-text placeholder:text-titan-text-muted/50 focus:outline-none focus:border-titan-accent"
							/>
							<p class="text-xs text-titan-text-muted mt-1">
								Find the ID in the Cagematch URL: cagematch.net/?id=8&nr=<strong>ID</strong>
							</p>
						</div>
						<button
							type="submit"
							disabled={loading || !selectedLibraryId || !promotionId || !promotionName}
							class="w-full py-2 bg-titan-accent rounded font-medium hover:opacity-90 disabled:opacity-50"
						>
							{loading ? 'Adding...' : 'Add Library'}
						</button>
					</form>
				</div>
			{/if}

			<!-- Done button -->
			{#if configuredLibraries.length > 0}
				<button
					onclick={handleDone}
					class="w-full py-3 bg-titan-gold text-titan-bg rounded font-bold hover:opacity-90"
				>
					Done — Go to Dashboard
				</button>
			{/if}
		</div>
	{/if}
</div>
