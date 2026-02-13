<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';

	let { children } = $props();

	const isPlayerPage = $derived(page.url.pathname.startsWith('/player'));
	const isAdminPage = $derived(page.url.pathname.startsWith('/admin'));
	const showNav = $derived(!isPlayerPage && !isAdminPage);

	let searchQuery = $state('');

	function handleSearch(e: SubmitEvent) {
		e.preventDefault();
		const q = searchQuery.trim();
		if (q.length >= 2) {
			goto(`/search?q=${encodeURIComponent(q)}`);
		}
	}
</script>

<div class="min-h-screen bg-titan-bg text-titan-text">
	{#if showNav}
		<nav class="border-b border-titan-border bg-titan-surface">
			<div class="max-w-6xl mx-auto px-4 flex items-center h-14 gap-4">
				<a href="/browse" class="font-bold text-lg shrink-0">
					<span class="text-titan-accent">TITAN</span><span class="text-titan-gold">TRON</span>
				</a>
				<a
					href="/browse"
					class="text-sm font-medium transition-colors shrink-0 {page.url.pathname.startsWith('/browse')
						? 'text-titan-accent'
						: 'text-titan-text-muted hover:text-titan-text'}"
				>
					Browse
				</a>
				<form onsubmit={handleSearch} class="flex-1 max-w-sm">
					<input
						type="text"
						bind:value={searchQuery}
						placeholder="Search wrestlers, events..."
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-1.5 text-sm text-titan-text placeholder:text-titan-text-muted focus:outline-none focus:ring-1 focus:ring-titan-accent"
					/>
				</form>
				<a
					href="/admin"
					class="text-titan-text-muted hover:text-titan-text transition-colors shrink-0"
					title="Admin"
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
						<path fill-rule="evenodd" d="M7.84 1.804A1 1 0 0 1 8.82 1h2.36a1 1 0 0 1 .98.804l.331 1.652a6.993 6.993 0 0 1 1.929 1.115l1.598-.54a1 1 0 0 1 1.186.447l1.18 2.044a1 1 0 0 1-.205 1.251l-1.267 1.113a7.047 7.047 0 0 1 0 2.228l1.267 1.113a1 1 0 0 1 .206 1.25l-1.18 2.045a1 1 0 0 1-1.187.447l-1.598-.54a6.993 6.993 0 0 1-1.929 1.115l-.33 1.652a1 1 0 0 1-.98.804H8.82a1 1 0 0 1-.98-.804l-.331-1.652a6.993 6.993 0 0 1-1.929-1.115l-1.598.54a1 1 0 0 1-1.186-.447l-1.18-2.044a1 1 0 0 1 .205-1.251l1.267-1.114a7.05 7.05 0 0 1 0-2.227L1.821 7.773a1 1 0 0 1-.206-1.25l1.18-2.045a1 1 0 0 1 1.187-.447l1.598.54A6.992 6.992 0 0 1 7.51 3.456l.33-1.652ZM10 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" clip-rule="evenodd" />
					</svg>
				</a>
			</div>
		</nav>
	{/if}
	{@render children()}
</div>
