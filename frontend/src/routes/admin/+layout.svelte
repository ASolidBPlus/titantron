<script lang="ts">
	import { page } from '$app/state';
	import { getAdminStatus, adminLogin, adminLogout } from '$lib/api/client';

	let { children } = $props();

	let loading = $state(true);
	let required = $state(false);
	let authenticated = $state(false);
	let password = $state('');
	let error = $state('');
	let loggingIn = $state(false);

	const tabs = [
		{ href: '/admin', label: 'Dashboard' },
		{ href: '/admin/matching', label: 'Matching' },
		{ href: '/admin/setup', label: 'Setup' },
		{ href: '/admin/settings', label: 'Settings' },
		{ href: '/admin/test-scrape', label: 'Test Scrape' },
	];

	function isActive(href: string): boolean {
		if (href === '/admin') return page.url.pathname === '/admin';
		return page.url.pathname.startsWith(href);
	}

	async function checkAuth() {
		try {
			const status = await getAdminStatus();
			required = status.required;
			authenticated = status.authenticated;
		} catch {
			// If we can't reach the backend, assume auth is required to be safe
			required = true;
			authenticated = false;
		} finally {
			loading = false;
		}
	}

	async function handleLogin(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		loggingIn = true;
		try {
			await adminLogin(password);
			authenticated = true;
			password = '';
		} catch {
			error = 'Invalid password';
		} finally {
			loggingIn = false;
		}
	}

	async function handleLogout() {
		await adminLogout();
		authenticated = false;
	}

	$effect(() => {
		checkAuth();
	});
</script>

{#if loading}
	<div class="min-h-[calc(100vh-3.5rem)] flex items-center justify-center">
		<p class="text-titan-text-muted">Loading...</p>
	</div>
{:else if required && !authenticated}
	<div class="min-h-[calc(100vh-3.5rem)] flex items-center justify-center">
		<div class="bg-titan-surface border border-titan-border rounded-lg p-8 w-full max-w-sm">
			<h1 class="text-xl font-bold mb-1">Admin Panel</h1>
			<p class="text-sm text-titan-text-muted mb-6">Enter the admin password to continue.</p>
			<form onsubmit={handleLogin}>
				<input
					type="password"
					bind:value={password}
					placeholder="Password"
					class="w-full px-3 py-2 bg-titan-bg border border-titan-border rounded text-sm focus:outline-none focus:border-titan-accent"
					autofocus
				/>
				{#if error}
					<p class="text-red-400 text-sm mt-2">{error}</p>
				{/if}
				<button
					type="submit"
					disabled={loggingIn || !password}
					class="w-full mt-4 px-4 py-2 bg-titan-accent text-black font-medium rounded hover:bg-titan-accent/90 disabled:opacity-50 text-sm"
				>
					{loggingIn ? 'Logging in...' : 'Log In'}
				</button>
			</form>
		</div>
	</div>
{:else}
	<div class="min-h-[calc(100vh-3.5rem)]">
		<div class="h-0.5 bg-titan-accent"></div>
		<div class="border-b border-titan-border bg-titan-surface">
			<div class="max-w-5xl mx-auto px-4 flex items-center h-11">
				<span class="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded bg-titan-accent/20 text-titan-accent mr-3">ADMIN</span>
				<div class="flex items-center gap-1 flex-1">
					{#each tabs as tab}
						<a
							href={tab.href}
							class="px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px {isActive(tab.href)
								? 'border-titan-accent text-titan-accent'
								: 'border-transparent text-titan-text-muted hover:text-titan-text hover:border-titan-border'}"
						>
							{tab.label}
						</a>
					{/each}
				</div>
				<div class="flex items-center gap-3">
					<a
						href="/"
						class="text-xs text-titan-text-muted hover:text-titan-text transition-colors"
					>&larr; Browse</a>
					{#if required}
						<button
							onclick={handleLogout}
							class="text-xs text-titan-text-muted hover:text-titan-text transition-colors"
						>
							Logout
						</button>
					{/if}
				</div>
			</div>
		</div>
		{@render children()}
	</div>
{/if}
