<script lang="ts">
	import { page } from '$app/state';
	import { globalSearch } from '$lib/api/client';
	import type { SearchResults } from '$lib/types';
	import { ratingColor } from '$lib/utils/rating';

	let results = $state<SearchResults | null>(null);
	let loading = $state(false);
	let error = $state('');

	let query = $derived(page.url.searchParams.get('q') || '');

	async function doSearch(q: string) {
		if (q.length < 2) {
			results = null;
			return;
		}
		loading = true;
		error = '';
		try {
			results = await globalSearch(q);
		} catch (e) {
			error = 'Search failed';
			results = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		doSearch(query);
	});

	function formatDate(dateStr: string | null): string {
		if (!dateStr) return '';
		return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
		});
	}
</script>

<svelte:head>
	<title>{query ? `"${query}" - Search` : 'Search'} - Titantron</title>
</svelte:head>

<div class="max-w-4xl mx-auto p-6">
	<h1 class="text-2xl font-bold mb-6">
		{#if query}
			Results for "{query}"
		{:else}
			Search
		{/if}
	</h1>

	{#if loading}
		<p class="text-titan-text-muted">Searching...</p>
	{:else if error}
		<p class="text-red-400">{error}</p>
	{:else if results}
		{#if results.wrestlers.length === 0 && results.events.length === 0}
			<p class="text-titan-text-muted">No results found.</p>
		{/if}

		<!-- Wrestlers -->
		{#if results.wrestlers.length > 0}
			<div class="mb-8">
				<h2 class="text-lg font-semibold mb-3">Wrestlers</h2>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
					{#each results.wrestlers as w}
						{#if w.cagematch_wrestler_id}
						<a
							href="/wrestler/{w.cagematch_wrestler_id}"
							class="bg-titan-surface border border-titan-border rounded-lg p-3 flex items-center gap-3 hover:border-titan-accent transition-colors"
						>
							{#if w.image_url}
								<img src={w.image_url} alt={w.name} class="w-10 h-10 rounded-full object-cover shrink-0" />
							{:else}
								<div class="w-10 h-10 rounded-full bg-titan-border flex items-center justify-center shrink-0">
									<span class="text-titan-text-muted text-sm">{w.name[0]}</span>
								</div>
							{/if}
							<div class="min-w-0">
								<span class="font-medium block truncate">{w.name}</span>
								<span class="text-xs text-titan-text-muted">{w.match_count} matches</span>
							</div>
						</a>
						{:else}
						<div class="bg-titan-surface border border-titan-border rounded-lg p-3 flex items-center gap-3">
							<div class="w-10 h-10 rounded-full bg-titan-border flex items-center justify-center shrink-0">
								<span class="text-titan-text-muted text-sm">{w.name[0]}</span>
							</div>
							<div class="min-w-0">
								<span class="font-medium block truncate italic">{w.name}</span>
								<span class="text-xs text-titan-text-muted">{w.match_count} matches</span>
							</div>
						</div>
						{/if}
					{/each}
				</div>
			</div>
		{/if}

		<!-- Events -->
		{#if results.events.length > 0}
			<div>
				<h2 class="text-lg font-semibold mb-3">Events</h2>
				<div class="space-y-2">
					{#each results.events as ev}
						<a
							href="/browse/event/{ev.cagematch_event_id}"
							class="bg-titan-surface border border-titan-border rounded-lg p-4 flex items-center justify-between hover:border-titan-accent transition-colors block"
						>
							<div class="min-w-0">
								<span class="font-medium block truncate">{ev.name}</span>
								<div class="flex gap-3 text-xs text-titan-text-muted mt-0.5">
									{#if ev.date}<span>{formatDate(ev.date)}</span>{/if}
									{#if ev.location}<span>{ev.location}</span>{/if}
								</div>
							</div>
							{#if ev.rating}
								<span class="font-bold shrink-0 ml-4" style="color: {ratingColor(ev.rating)}">{ev.rating.toFixed(1)}</span>
							{/if}
						</a>
					{/each}
				</div>
			</div>
		{/if}
	{:else if !query}
		<p class="text-titan-text-muted">Enter a search term to find wrestlers and events.</p>
	{/if}
</div>
