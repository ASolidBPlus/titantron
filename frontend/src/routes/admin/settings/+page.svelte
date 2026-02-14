<script lang="ts">
	import { onMount } from 'svelte';
	import { getAppSettings, updateAppSettings } from '$lib/api/client';
	import type { AppSettings } from '$lib/api/client';

	let loading = $state(true);
	let saving = $state(false);
	let message = $state<{ type: 'success' | 'error'; text: string } | null>(null);

	// Form fields
	let jellyfinPublicUrl = $state('');
	let newPassword = $state('');
	let confirmPassword = $state('');
	let passwordIsSet = $state(false);
	let scrapeRateLimit = $state(0.5);
	let scrapeBurst = $state(3);

	async function loadSettings() {
		try {
			const s = await getAppSettings();
			jellyfinPublicUrl = s.jellyfin_public_url;
			passwordIsSet = s.admin_password_is_set;
			scrapeRateLimit = s.scrape_rate_limit;
			scrapeBurst = s.scrape_burst;
		} catch (e: any) {
			message = { type: 'error', text: `Failed to load settings: ${e.message}` };
		} finally {
			loading = false;
		}
	}

	async function handleSave() {
		message = null;

		if (newPassword && newPassword !== confirmPassword) {
			message = { type: 'error', text: 'Passwords do not match' };
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
			message = { type: 'success', text: `Settings saved (${result.updated.join(', ')})` };

			if (newPassword) {
				passwordIsSet = true;
				newPassword = '';
				confirmPassword = '';
			}
		} catch (e: any) {
			message = { type: 'error', text: `Failed to save: ${e.message}` };
		} finally {
			saving = false;
		}
	}

	onMount(loadSettings);
</script>

<div class="max-w-2xl mx-auto p-6">
	<h1 class="text-xl font-bold mb-6">Settings</h1>

	{#if loading}
		<p class="text-titan-text-muted">Loading settings...</p>
	{:else}
		<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-8">
			<!-- Jellyfin Public URL -->
			<div>
				<label for="jellyfin-url" class="block text-sm font-medium mb-1">Jellyfin Public URL</label>
				<p class="text-xs text-titan-text-muted mb-2">
					The URL clients use to reach Jellyfin (for streaming, posters). Leave empty to use the internal URL.
				</p>
				<input
					id="jellyfin-url"
					type="text"
					bind:value={jellyfinPublicUrl}
					placeholder="https://jellyfin.example.com"
					class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
				/>
			</div>

			<!-- Admin Password -->
			<div>
				<label class="block text-sm font-medium mb-1">Admin Password</label>
				<p class="text-xs text-titan-text-muted mb-2">
					{#if passwordIsSet}
						Password is currently set. Enter a new one to change it, or leave blank to keep it.
					{:else}
						No password set. Anyone can access the admin panel.
					{/if}
				</p>
				<div class="space-y-2">
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

			<!-- Scraper Settings -->
			<div>
				<label class="block text-sm font-medium mb-1">Scraper Settings</label>
				<p class="text-xs text-titan-text-muted mb-2">
					Rate limiting for Cagematch.net requests.
				</p>
				<div class="grid grid-cols-2 gap-4">
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

			<!-- Save -->
			{#if message}
				<div class="text-sm px-3 py-2 rounded {message.type === 'success' ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'}">
					{message.text}
				</div>
			{/if}

			<button
				type="submit"
				disabled={saving}
				class="px-6 py-2 bg-titan-accent text-black font-medium rounded hover:bg-titan-accent/90 disabled:opacity-50 text-sm"
			>
				{saving ? 'Saving...' : 'Save Settings'}
			</button>
		</form>
	{/if}
</div>
