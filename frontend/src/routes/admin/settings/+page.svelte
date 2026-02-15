<script lang="ts">
	import { onMount } from 'svelte';
	import { ratingColor } from '$lib/utils/rating';
	import {
		connect,
		disconnect,
		getAuthStatus,
		getAppSettings,
		updateAppSettings,
		getJellyfinLibraries,
		getConfiguredLibraries,
		configureLibrary,
		updateLibrary,
		deleteLibrary,
		syncLibrary,
		getSyncStatus,
		browseDirs,
		type JellyfinLibrary,
		type ConfiguredLibrary,
		type SyncStatus,
		type BrowseDirsResult,
	} from '$lib/api/client';

	const API_BASE = '/api/v1';

	let loading = $state(true);
	let connected = $state(false);

	// Jellyfin connection
	let serverUrl = $state('');
	let jellyfinUsername = $state('');
	let jellyfinPassword = $state('');
	let connectError = $state('');
	let connecting = $state(false);
	let jellyfinPublicUrl = $state('');

	// Libraries
	let jellyfinLibraries = $state<JellyfinLibrary[]>([]);
	let configuredLibraries = $state<ConfiguredLibrary[]>([]);
	let selectedLibraryId = $state('');
	let promotionId = $state('');
	let promotionName = $state('');
	let promotionAbbr = $state('');
	let jellyfinPathInput = $state('');
	let localPathInput = $state('');
	let addingLibrary = $state(false);
	let libraryError = $state('');

	// Library path editing
	let editingLibraryId = $state<number | null>(null);
	let editJellyfinPath = $state('');
	let editLocalPath = $state('');
	let savingPathMapping = $state(false);

	// File browser
	let browseTarget = $state<'add' | 'edit' | null>(null);
	let browseDirResult = $state<BrowseDirsResult | null>(null);
	let browseLoading = $state(false);

	async function openBrowser(target: 'add' | 'edit', startPath?: string) {
		browseTarget = target;
		browseLoading = true;
		try {
			browseDirResult = await browseDirs(startPath || '/');
		} catch {
			browseDirResult = { path: '/', parent: null, directories: [] };
		} finally {
			browseLoading = false;
		}
	}

	async function navigateBrowser(path: string) {
		browseLoading = true;
		try {
			browseDirResult = await browseDirs(path);
		} catch {
			// stay on current
		} finally {
			browseLoading = false;
		}
	}

	function selectBrowserPath() {
		if (!browseDirResult) return;
		if (browseTarget === 'add') {
			localPathInput = browseDirResult.path;
		} else if (browseTarget === 'edit') {
			editLocalPath = browseDirResult.path;
		}
		browseTarget = null;
		browseDirResult = null;
	}

	function closeBrowser() {
		browseTarget = null;
		browseDirResult = null;
	}

	// Sync
	let syncStatusData = $state<SyncStatus | null>(null);
	let syncPolling = $state(false);
	let syncingLibraryId = $state<number | null>(null);

	// Security
	let newPassword = $state('');
	let confirmPassword = $state('');
	let passwordIsSet = $state(false);

	// Scraper settings
	let scrapeRateLimit = $state(0.5);
	let scrapeBurst = $state(3);

	// Settings save
	let saving = $state(false);
	let settingsMessage = $state<{ type: 'success' | 'error'; text: string } | null>(null);

	// Section collapse state
	let showJellyfin = $state(true);
	let showLibraries = $state(true);
	let showSecurity = $state(false);
	let showScraper = $state(false);

	// Test scrape
	let cagematchId = $state('');
	let scrapeLoading = $state(false);
	let scrapeError = $state('');
	let scrapeResult = $state<any>(null);
	let showTestScrape = $state(false);

	interface Participant {
		name: string;
		cagematch_id: number | null;
		is_linked: boolean;
		side: number;
		team_name: string | null;
		role: string;
	}

	interface SideGroup {
		teamName: string | null;
		competitors: Participant[];
		managers: Participant[];
	}

	function groupSides(participants: Participant[]): SideGroup[] {
		const sideMap = new Map<number, Participant[]>();
		for (const p of participants) {
			const side = p.side ?? 1;
			if (!sideMap.has(side)) sideMap.set(side, []);
			sideMap.get(side)!.push(p);
		}
		return [...sideMap.entries()]
			.sort((a, b) => a[0] - b[0])
			.map(([, ps]) => ({
				teamName: ps.find((p) => p.role !== 'manager')?.team_name ?? null,
				competitors: ps.filter((p) => p.role !== 'manager'),
				managers: ps.filter((p) => p.role === 'manager'),
			}));
	}

	onMount(async () => {
		try {
			const [status, settings] = await Promise.all([
				getAuthStatus(),
				getAppSettings().catch(() => null),
			]);
			connected = status.connected;
			if (status.jellyfin_url) serverUrl = status.jellyfin_url;
			if (status.username) jellyfinUsername = status.username;
			if (settings) {
				jellyfinPublicUrl = settings.jellyfin_public_url;
				passwordIsSet = settings.admin_password_is_set;
				scrapeRateLimit = settings.scrape_rate_limit;
				scrapeBurst = settings.scrape_burst;
			}
			if (connected) {
				await loadLibraries();
			}
		} catch {
			// stay on defaults
		} finally {
			loading = false;
		}
	});

	async function handleConnect() {
		connectError = '';
		connecting = true;
		try {
			await connect({ url: serverUrl, username: jellyfinUsername, password: jellyfinPassword });
			connected = true;
			jellyfinPassword = '';
			await loadLibraries();
		} catch (e: any) {
			connectError = e.message || 'Failed to connect';
		} finally {
			connecting = false;
		}
	}

	async function handleDisconnect() {
		try {
			await disconnect();
			connected = false;
			jellyfinLibraries = [];
			configuredLibraries = [];
		} catch {
			// ignore
		}
	}

	async function loadLibraries() {
		const [jl, cl] = await Promise.allSettled([
			getJellyfinLibraries(),
			getConfiguredLibraries(),
		]);
		if (jl.status === 'fulfilled') jellyfinLibraries = jl.value;
		if (cl.status === 'fulfilled') configuredLibraries = cl.value;
	}

	let availableLibraries = $derived(
		jellyfinLibraries.filter(
			(jl) => !configuredLibraries.some((cl) => cl.jellyfin_library_id === jl.id)
		)
	);

	// Auto-populate jellyfin path when library is selected
	$effect(() => {
		if (selectedLibraryId) {
			const lib = jellyfinLibraries.find((l) => l.id === selectedLibraryId);
			if (lib?.paths?.length) {
				jellyfinPathInput = lib.paths[0];
			}
		}
	});

	async function handleAddLibrary() {
		if (!selectedLibraryId || !promotionId || !promotionName) return;
		libraryError = '';
		addingLibrary = true;
		try {
			const lib = jellyfinLibraries.find((l) => l.id === selectedLibraryId);
			await configureLibrary({
				jellyfin_library_id: selectedLibraryId,
				jellyfin_library_name: lib?.name ?? 'Unknown',
				cagematch_promotion_id: parseInt(promotionId),
				promotion_name: promotionName,
				promotion_abbreviation: promotionAbbr,
				jellyfin_path: jellyfinPathInput || undefined,
				local_path: localPathInput || undefined,
			});
			selectedLibraryId = '';
			promotionId = '';
			promotionName = '';
			promotionAbbr = '';
			jellyfinPathInput = '';
			localPathInput = '';
			await loadLibraries();
		} catch (e: any) {
			libraryError = e.message || 'Failed to add library';
		} finally {
			addingLibrary = false;
		}
	}

	async function handleDeleteLibrary(id: number) {
		if (!confirm('Remove this library configuration?')) return;
		try {
			await deleteLibrary(id);
			await loadLibraries();
		} catch (e: any) {
			libraryError = e.message || 'Failed to delete library';
		}
	}

	function startEditPathMapping(lib: ConfiguredLibrary) {
		editingLibraryId = lib.id;
		editJellyfinPath = lib.jellyfin_path || '';
		editLocalPath = lib.local_path || '';
	}

	function cancelEditPathMapping() {
		editingLibraryId = null;
	}

	async function savePathMapping(libraryId: number) {
		savingPathMapping = true;
		try {
			await updateLibrary(libraryId, {
				jellyfin_path: editJellyfinPath,
				local_path: editLocalPath,
			});
			editingLibraryId = null;
			await loadLibraries();
		} catch (e: any) {
			libraryError = e.message || 'Failed to update path mapping';
		} finally {
			savingPathMapping = false;
		}
	}

	async function handleSync(libraryId: number) {
		syncingLibraryId = libraryId;
		try {
			await syncLibrary(libraryId);
			syncPolling = true;
			while (syncPolling) {
				await new Promise((r) => setTimeout(r, 1000));
				try {
					syncStatusData = await getSyncStatus();
					if (!syncStatusData.is_running) {
						syncPolling = false;
						await loadLibraries();
					}
				} catch {
					syncPolling = false;
				}
			}
		} catch (e: any) {
			libraryError = e.message || 'Failed to start sync';
		} finally {
			syncingLibraryId = null;
			syncStatusData = null;
		}
	}

	async function handleSaveSettings() {
		settingsMessage = null;

		if (newPassword && newPassword !== confirmPassword) {
			settingsMessage = { type: 'error', text: 'Passwords do not match' };
			return;
		}

		saving = true;
		try {
			const updates: Record<string, any> = {
				jellyfin_public_url: jellyfinPublicUrl,
				scrape_rate_limit: scrapeRateLimit,
				scrape_burst: scrapeBurst,
			};
			if (newPassword) {
				updates.admin_password = newPassword;
			}

			const result = await updateAppSettings(updates);
			settingsMessage = { type: 'success', text: `Settings saved (${result.updated.join(', ')})` };

			if (newPassword) {
				passwordIsSet = true;
				newPassword = '';
				confirmPassword = '';
			}
		} catch (e: any) {
			settingsMessage = { type: 'error', text: `Failed to save: ${e.message}` };
		} finally {
			saving = false;
		}
	}

	// Test scrape
	function extractId(input: string): string {
		const trimmed = input.trim();
		const match = trimmed.match(/[?&]nr=(\d+)/);
		if (match) return match[1];
		if (/^\d+$/.test(trimmed)) return trimmed;
		return trimmed;
	}

	async function handleScrape() {
		const id = extractId(cagematchId);
		if (!id) return;
		scrapeLoading = true;
		scrapeError = '';
		scrapeResult = null;
		try {
			const res = await fetch(`${API_BASE}/browse/test-scrape/${id}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			scrapeResult = await res.json();
		} catch (e: any) {
			scrapeError = e.message || 'Failed to scrape';
		} finally {
			scrapeLoading = false;
		}
	}

	function handleScrapeKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleScrape();
	}
</script>

<svelte:head>
	<title>Settings - Titantron</title>
</svelte:head>

<div class="max-w-3xl mx-auto p-6 space-y-6">
	<h1 class="text-2xl font-bold">Settings</h1>

	{#if loading}
		<p class="text-titan-text-muted">Loading...</p>
	{:else}
		<!-- Section 1: Jellyfin Connection -->
		<section class="bg-titan-surface border border-titan-border rounded-lg overflow-hidden">
			<button
				onclick={() => showJellyfin = !showJellyfin}
				class="w-full flex items-center justify-between p-4 hover:bg-titan-surface-hover transition-colors text-left"
			>
				<div class="flex items-center gap-3">
					<h2 class="text-lg font-semibold">Jellyfin Connection</h2>
					{#if connected}
						<span class="text-xs px-2 py-0.5 rounded bg-green-800/50 text-green-300">Connected</span>
					{:else}
						<span class="text-xs px-2 py-0.5 rounded bg-red-800/50 text-red-300">Not Connected</span>
					{/if}
				</div>
				<span class="text-titan-text-muted text-sm">{showJellyfin ? '−' : '+'}</span>
			</button>
			{#if showJellyfin}
				<div class="px-4 pb-4 space-y-4 border-t border-titan-border pt-4">
					{#if connected}
						<div class="flex items-center justify-between">
							<div>
								<p class="text-sm"><span class="text-titan-text-muted">Server:</span> {serverUrl}</p>
								<p class="text-sm"><span class="text-titan-text-muted">User:</span> {jellyfinUsername}</p>
							</div>
							<button
								onclick={handleDisconnect}
								class="text-sm px-3 py-1.5 text-red-400 border border-red-800 rounded hover:bg-red-900/30"
							>
								Disconnect
							</button>
						</div>
					{:else}
						<form onsubmit={(e) => { e.preventDefault(); handleConnect(); }} class="space-y-3">
							<div>
								<label for="server-url" class="block text-sm text-titan-text-muted mb-1">Server URL</label>
								<input
									id="server-url"
									type="url"
									bind:value={serverUrl}
									placeholder="http://localhost:8096"
									required
									class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
								/>
							</div>
							<div class="grid grid-cols-2 gap-3">
								<div>
									<label for="jf-username" class="block text-sm text-titan-text-muted mb-1">Username</label>
									<input
										id="jf-username"
										type="text"
										bind:value={jellyfinUsername}
										required
										class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
									/>
								</div>
								<div>
									<label for="jf-password" class="block text-sm text-titan-text-muted mb-1">Password</label>
									<input
										id="jf-password"
										type="password"
										bind:value={jellyfinPassword}
										class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
									/>
								</div>
							</div>
							{#if connectError}
								<p class="text-red-400 text-sm">{connectError}</p>
							{/if}
							<button
								type="submit"
								disabled={connecting}
								class="px-4 py-2 bg-titan-accent text-black font-medium rounded text-sm hover:bg-titan-accent/90 disabled:opacity-50"
							>
								{connecting ? 'Connecting...' : 'Connect'}
							</button>
						</form>
					{/if}

					<!-- Jellyfin Public URL -->
					<div class="pt-2 border-t border-titan-border">
						<label for="jellyfin-public-url" class="block text-sm font-medium mb-1">Public URL</label>
						<p class="text-xs text-titan-text-muted mb-2">
							The URL clients use to reach Jellyfin (for streaming, posters). Leave empty to use the internal URL.
						</p>
						<input
							id="jellyfin-public-url"
							type="text"
							bind:value={jellyfinPublicUrl}
							placeholder="https://jellyfin.example.com"
							class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
						/>
					</div>
				</div>
			{/if}
		</section>

		<!-- Section 2: Libraries -->
		<section class="bg-titan-surface border border-titan-border rounded-lg overflow-hidden">
			<button
				onclick={() => showLibraries = !showLibraries}
				class="w-full flex items-center justify-between p-4 hover:bg-titan-surface-hover transition-colors text-left"
			>
				<div class="flex items-center gap-3">
					<h2 class="text-lg font-semibold">Libraries</h2>
					<span class="text-xs text-titan-text-muted">{configuredLibraries.length} configured</span>
				</div>
				<span class="text-titan-text-muted text-sm">{showLibraries ? '−' : '+'}</span>
			</button>
			{#if showLibraries}
				<div class="px-4 pb-4 space-y-4 border-t border-titan-border pt-4">
					{#if libraryError}
						<div class="p-3 bg-red-900/30 border border-red-800 rounded text-red-300 text-sm">
							{libraryError}
						</div>
					{/if}

					{#if !connected}
						<p class="text-sm text-titan-text-muted">Connect to Jellyfin first to manage libraries.</p>
					{:else}
						<!-- Configured Libraries -->
						{#if configuredLibraries.length > 0}
							<div class="space-y-3">
								{#each configuredLibraries as lib}
									<div class="bg-titan-bg border border-titan-border rounded-lg p-4">
										<div class="flex items-center justify-between mb-2">
											<div>
												<h3 class="font-semibold">{lib.name}</h3>
												<p class="text-sm text-titan-text-muted">
													{lib.promotion_name}
													{#if lib.promotion_abbreviation}({lib.promotion_abbreviation}){/if}
													&middot; {lib.video_count} videos
													{#if lib.last_synced}
														&middot; Synced {new Date(lib.last_synced).toLocaleDateString()}
													{/if}
												</p>
											</div>
											<div class="flex items-center gap-2">
												<button
													onclick={() => handleSync(lib.id)}
													disabled={syncingLibraryId !== null}
													class="text-xs px-3 py-1.5 bg-titan-surface border border-titan-border rounded hover:border-titan-accent disabled:opacity-50"
												>
													{syncingLibraryId === lib.id ? 'Syncing...' : 'Sync'}
												</button>
												<button
													onclick={() => handleDeleteLibrary(lib.id)}
													class="text-xs px-3 py-1.5 text-red-400 border border-red-800 rounded hover:bg-red-900/30"
												>
													Remove
												</button>
											</div>
										</div>

										<!-- Path mapping display/edit -->
										{#if editingLibraryId === lib.id}
											<div class="mt-3 pt-3 border-t border-titan-border space-y-2">
												<div class="grid grid-cols-2 gap-3">
													<div>
														<label class="block text-xs text-titan-text-muted mb-1">Jellyfin Path</label>
														<input
															type="text"
															bind:value={editJellyfinPath}
															placeholder="/data/wrestling"
															class="w-full bg-titan-surface border border-titan-border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-titan-accent"
														/>
													</div>
													<div>
														<label class="block text-xs text-titan-text-muted mb-1">Local Path</label>
														<div class="flex gap-2">
															<input
																type="text"
																bind:value={editLocalPath}
																placeholder="/media"
																class="flex-1 bg-titan-surface border border-titan-border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-titan-accent"
															/>
															<button
																type="button"
																onclick={() => openBrowser('edit', editLocalPath || '/')}
																class="px-2 py-1.5 bg-titan-border rounded hover:bg-titan-surface-hover text-xs shrink-0"
																title="Browse directories"
															>
																Browse
															</button>
														</div>
													</div>
												</div>
												<div class="flex gap-2">
													<button
														onclick={() => savePathMapping(lib.id)}
														disabled={savingPathMapping}
														class="text-xs px-3 py-1 bg-titan-accent text-black rounded hover:bg-titan-accent/90 disabled:opacity-50"
													>
														{savingPathMapping ? 'Saving...' : 'Save'}
													</button>
													<button
														onclick={cancelEditPathMapping}
														class="text-xs px-3 py-1 bg-titan-border rounded hover:bg-titan-surface-hover"
													>
														Cancel
													</button>
												</div>
											</div>
										{:else}
											<div class="mt-2 flex items-center gap-2 text-xs text-titan-text-muted">
												{#if lib.jellyfin_path || lib.local_path}
													<span class="font-mono">{lib.jellyfin_path || '(none)'}</span>
													<span>&rarr;</span>
													<span class="font-mono">{lib.local_path || '(none)'}</span>
												{:else}
													<span>No path mapping</span>
												{/if}
												<button
													onclick={() => startEditPathMapping(lib)}
													class="text-titan-accent hover:underline ml-1"
												>
													Edit
												</button>
											</div>
										{/if}

										<!-- Sync progress -->
										{#if syncingLibraryId === lib.id && syncStatusData?.is_running}
											<div class="mt-3 pt-3 border-t border-titan-border">
												<p class="text-xs text-titan-text-muted">{syncStatusData.message}</p>
												{#if syncStatusData.total}
													<div class="mt-1 w-full bg-titan-surface rounded-full h-1.5">
														<div
															class="bg-titan-accent h-1.5 rounded-full transition-all"
															style="width: {((syncStatusData.progress ?? 0) / syncStatusData.total) * 100}%"
														></div>
													</div>
													<p class="text-xs text-titan-text-muted mt-1">
														{syncStatusData.progress} / {syncStatusData.total}
													</p>
												{/if}
											</div>
										{/if}
									</div>
								{/each}
							</div>
						{/if}

						<!-- Add Library Form -->
						{#if availableLibraries.length > 0}
							<div class="pt-4 border-t border-titan-border">
								<h3 class="text-sm font-medium mb-3">Add Library</h3>
								<form onsubmit={(e) => { e.preventDefault(); handleAddLibrary(); }} class="space-y-3">
									<div>
										<label for="library-select" class="block text-xs text-titan-text-muted mb-1">Jellyfin Library</label>
										<select
											id="library-select"
											bind:value={selectedLibraryId}
											required
											class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
										>
											<option value="">Select a library...</option>
											{#each availableLibraries as lib}
												<option value={lib.id}>{lib.name} ({lib.collection_type})</option>
											{/each}
										</select>
									</div>
									<div class="grid grid-cols-2 gap-3">
										<div>
											<label for="promo-name" class="block text-xs text-titan-text-muted mb-1">Promotion Name</label>
											<input
												id="promo-name"
												type="text"
												bind:value={promotionName}
												placeholder="World Wrestling Entertainment"
												required
												class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
											/>
										</div>
										<div>
											<label for="promo-abbr" class="block text-xs text-titan-text-muted mb-1">Abbreviation</label>
											<input
												id="promo-abbr"
												type="text"
												bind:value={promotionAbbr}
												placeholder="WWE"
												class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
											/>
										</div>
									</div>
									<div>
										<label for="promo-id" class="block text-xs text-titan-text-muted mb-1">
											Cagematch Promotion ID
										</label>
										<input
											id="promo-id"
											type="number"
											bind:value={promotionId}
											placeholder="e.g. 1 for WWE, 2287 for AEW"
											required
											class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
										/>
										<p class="text-xs text-titan-text-muted mt-1">
											Find the ID in the Cagematch URL: cagematch.net/?id=8&nr=<strong>ID</strong>
										</p>
									</div>
									<div class="grid grid-cols-2 gap-3">
										<div>
											<label for="jellyfin-path" class="block text-xs text-titan-text-muted mb-1">Jellyfin Library Path</label>
											<input
												id="jellyfin-path"
												type="text"
												bind:value={jellyfinPathInput}
												placeholder="Auto-filled when library selected"
												readonly={!!jellyfinPathInput && !!selectedLibraryId}
												class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent {jellyfinPathInput && selectedLibraryId ? 'text-titan-text-muted' : ''}"
											/>
										</div>
										<div>
											<label for="local-path" class="block text-xs text-titan-text-muted mb-1">Local Mount Path</label>
											<div class="flex gap-2">
												<input
													id="local-path"
													type="text"
													bind:value={localPathInput}
													placeholder="/media"
													class="flex-1 bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:border-titan-accent"
												/>
												<button
													type="button"
													onclick={() => openBrowser('add', localPathInput || '/')}
													class="px-2 py-2 bg-titan-border rounded hover:bg-titan-surface-hover text-xs shrink-0"
													title="Browse directories"
												>
													Browse
												</button>
											</div>
										</div>
									</div>
									<p class="text-xs text-titan-text-muted">
										Path mapping translates Jellyfin file paths to your local Docker mount for audio analysis.
									</p>
									<button
										type="submit"
										disabled={addingLibrary || !selectedLibraryId || !promotionId || !promotionName}
										class="px-4 py-2 bg-titan-accent text-black font-medium rounded text-sm hover:bg-titan-accent/90 disabled:opacity-50"
									>
										{addingLibrary ? 'Adding...' : 'Add Library'}
									</button>
								</form>
							</div>
						{:else if configuredLibraries.length === 0}
							<p class="text-sm text-titan-text-muted">No Jellyfin libraries available. Check your Jellyfin server connection.</p>
						{/if}
					{/if}
				</div>
			{/if}
		</section>

		<!-- Section 3: Security -->
		<section class="bg-titan-surface border border-titan-border rounded-lg overflow-hidden">
			<button
				onclick={() => showSecurity = !showSecurity}
				class="w-full flex items-center justify-between p-4 hover:bg-titan-surface-hover transition-colors text-left"
			>
				<div class="flex items-center gap-3">
					<h2 class="text-lg font-semibold">Security</h2>
					{#if passwordIsSet}
						<span class="text-xs px-2 py-0.5 rounded bg-green-800/50 text-green-300">Password Set</span>
					{:else}
						<span class="text-xs px-2 py-0.5 rounded bg-yellow-800/50 text-yellow-300">No Password</span>
					{/if}
				</div>
				<span class="text-titan-text-muted text-sm">{showSecurity ? '−' : '+'}</span>
			</button>
			{#if showSecurity}
				<div class="px-4 pb-4 space-y-3 border-t border-titan-border pt-4">
					<p class="text-xs text-titan-text-muted">
						{#if passwordIsSet}
							Password is currently set. Enter a new one to change it, or leave blank to keep it.
						{:else}
							No password set. Anyone can access the admin panel.
						{/if}
					</p>
					<div class="space-y-2 max-w-sm">
						<input
							type="password"
							bind:value={newPassword}
							placeholder="New password"
							class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
						/>
						{#if newPassword}
							<input
								type="password"
								bind:value={confirmPassword}
								placeholder="Confirm password"
								class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
							/>
						{/if}
					</div>
				</div>
			{/if}
		</section>

		<!-- Section 4: Scraper -->
		<section class="bg-titan-surface border border-titan-border rounded-lg overflow-hidden">
			<button
				onclick={() => showScraper = !showScraper}
				class="w-full flex items-center justify-between p-4 hover:bg-titan-surface-hover transition-colors text-left"
			>
				<h2 class="text-lg font-semibold">Scraper</h2>
				<span class="text-titan-text-muted text-sm">{showScraper ? '−' : '+'}</span>
			</button>
			{#if showScraper}
				<div class="px-4 pb-4 space-y-4 border-t border-titan-border pt-4">
					<div>
						<p class="text-xs text-titan-text-muted mb-3">
							Rate limiting for Cagematch.net requests.
						</p>
						<div class="grid grid-cols-2 gap-4 max-w-sm">
							<div>
								<label for="rate-limit" class="block text-xs text-titan-text-muted mb-1">Rate limit (req/sec)</label>
								<input
									id="rate-limit"
									type="number"
									step="0.1"
									min="0.1"
									bind:value={scrapeRateLimit}
									class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
								/>
							</div>
							<div>
								<label for="burst" class="block text-xs text-titan-text-muted mb-1">Burst limit</label>
								<input
									id="burst"
									type="number"
									step="1"
									min="1"
									bind:value={scrapeBurst}
									class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
								/>
							</div>
						</div>
					</div>

					<!-- Test Scrape -->
					<div class="pt-4 border-t border-titan-border">
						<button
							onclick={() => showTestScrape = !showTestScrape}
							class="flex items-center gap-2 text-sm font-medium text-titan-text-muted hover:text-titan-text"
						>
							<span>{showTestScrape ? '−' : '+'}</span>
							Test Scrape
						</button>
						{#if showTestScrape}
							<div class="mt-3 space-y-3">
								<div class="flex gap-3">
									<input
										type="text"
										bind:value={cagematchId}
										onkeydown={handleScrapeKeydown}
										placeholder="Cagematch event ID or URL"
										class="flex-1 bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-titan-accent"
									/>
									<button
										onclick={handleScrape}
										disabled={scrapeLoading || !cagematchId.trim()}
										class="px-4 py-2 bg-titan-accent text-black rounded text-sm hover:opacity-90 disabled:opacity-50 shrink-0"
									>
										{scrapeLoading ? 'Scraping...' : 'Scrape'}
									</button>
								</div>
								<p class="text-xs text-titan-text-muted">
									Enter a Cagematch event ID from the URL, e.g. <code class="text-titan-text">cagematch.net/?id=1&nr=<strong>1757</strong></code>
								</p>

								{#if scrapeError}
									<p class="text-red-400 text-sm">{scrapeError}</p>
								{/if}

								{#if scrapeResult}
									<div class="bg-titan-bg border border-titan-border rounded-lg p-4">
										<h3 class="font-bold mb-1">{scrapeResult.event.name ?? 'Unknown'}</h3>
										<div class="flex flex-wrap gap-4 text-sm text-titan-text-muted">
											{#if scrapeResult.event.date}<span>{scrapeResult.event.date}</span>{/if}
											{#if scrapeResult.event.promotion}<span>{scrapeResult.event.promotion}</span>{/if}
											{#if scrapeResult.event.location}<span>{scrapeResult.event.location}</span>{/if}
											{#if scrapeResult.event.arena}<span>{scrapeResult.event.arena}</span>{/if}
										</div>
										<p class="text-sm text-titan-text-muted mt-1">{scrapeResult.matches.length} matches</p>
									</div>

									<div class="space-y-2">
										{#each scrapeResult.matches as match}
											{@const sides = groupSides(match.participants)}
											<div class="bg-titan-bg border border-titan-border rounded-lg p-3 overflow-hidden">
												<div class="flex items-start justify-between gap-4">
													<div class="flex-1 min-w-0">
														{#if match.title_name || match.match_type}
															<p class="text-xs mb-1">
																{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
																{#if match.title_name && match.match_type}{' '}{/if}
																{#if match.match_type}<span class="text-titan-text-muted">{match.match_type}</span>{/if}
															</p>
														{/if}
														<div class="font-medium text-sm break-words">
															{#each sides as side, sideIndex}
																{#if side.teamName}<span class="text-titan-text-muted text-xs">{side.teamName} (</span>{/if}{#each side.competitors as p, i}<span class="{!p.is_linked ? 'italic' : ''}">{p.name}</span>{#if i < side.competitors.length - 1}<span class="text-titan-text-muted">{' & '}</span>{/if}{/each}{#if side.teamName}<span class="text-titan-text-muted text-xs">)</span>{/if}{#if side.managers.length > 0}<span class="text-titan-text-muted text-xs">{' '}(w/{' '}{#each side.managers as mgr, i}{mgr.name}{#if i < side.managers.length - 1}{', '}{/if}{/each})</span>{/if}
																{#if sideIndex < sides.length - 1}
																	<span class="text-titan-accent font-bold mx-1">vs.</span>
																{/if}
															{/each}
														</div>
														{#if match.duration}
															<p class="text-xs text-titan-text-muted mt-1">{match.duration}</p>
														{/if}
													</div>
													<div class="text-right shrink-0">
														{#if match.rating}
															<span class="font-bold text-sm" style="color: {ratingColor(match.rating)}">{match.rating.toFixed(2)}</span>
															{#if match.votes}
																<span class="text-xs text-titan-text-muted block">{match.votes} votes</span>
															{/if}
														{/if}
													</div>
												</div>
												<details class="mt-2">
													<summary class="text-xs text-titan-text-muted cursor-pointer hover:text-titan-text">Raw data</summary>
													<pre class="mt-2 text-xs text-titan-text-muted bg-titan-surface rounded p-2 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(match, null, 2)}</pre>
												</details>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</section>

		<!-- Save button -->
		{#if settingsMessage}
			<div class="text-sm px-3 py-2 rounded {settingsMessage.type === 'success' ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'}">
				{settingsMessage.text}
			</div>
		{/if}

		<button
			onclick={handleSaveSettings}
			disabled={saving}
			class="px-6 py-2 bg-titan-accent text-black font-medium rounded hover:bg-titan-accent/90 disabled:opacity-50 text-sm"
		>
			{saving ? 'Saving...' : 'Save Settings'}
		</button>
	{/if}
</div>

<!-- Directory Browser Modal -->
{#if browseTarget}
	<div class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" role="dialog">
		<div class="bg-titan-surface border border-titan-border rounded-lg w-full max-w-md max-h-[70vh] flex flex-col">
			<div class="p-4 border-b border-titan-border flex items-center justify-between shrink-0">
				<h3 class="font-semibold text-sm">Select Directory</h3>
				<button onclick={closeBrowser} class="text-titan-text-muted hover:text-titan-text text-lg">&times;</button>
			</div>
			{#if browseLoading}
				<div class="p-4 text-titan-text-muted text-sm">Loading...</div>
			{:else if browseDirResult}
				<div class="px-4 py-2 border-b border-titan-border bg-titan-bg flex items-center gap-2 shrink-0">
					<span class="text-xs font-mono text-titan-text-muted truncate flex-1">{browseDirResult.path}</span>
				</div>
				<div class="overflow-y-auto flex-1">
					{#if browseDirResult.parent}
						<button
							onclick={() => navigateBrowser(browseDirResult!.parent!)}
							class="w-full text-left px-4 py-2 text-sm hover:bg-titan-surface-hover border-b border-titan-border/50 text-titan-text-muted"
						>
							..
						</button>
					{/if}
					{#if browseDirResult.directories.length === 0}
						<p class="px-4 py-3 text-xs text-titan-text-muted">No subdirectories</p>
					{:else}
						{#each browseDirResult.directories as dir}
							<button
								onclick={() => navigateBrowser(dir.path)}
								class="w-full text-left px-4 py-2 text-sm hover:bg-titan-surface-hover border-b border-titan-border/50"
							>
								{dir.name}/
							</button>
						{/each}
					{/if}
				</div>
				<div class="p-3 border-t border-titan-border flex justify-end gap-2 shrink-0">
					<button
						onclick={closeBrowser}
						class="text-xs px-3 py-1.5 bg-titan-border rounded hover:bg-titan-surface-hover"
					>
						Cancel
					</button>
					<button
						onclick={selectBrowserPath}
						class="text-xs px-3 py-1.5 bg-titan-accent text-black rounded hover:bg-titan-accent/90"
					>
						Select "{browseDirResult.path}"
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}
