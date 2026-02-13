<script lang="ts">
	import { ratingColor } from '$lib/utils/rating';
	const API_BASE = '/api/v1';

	let cagematchId = $state('');
	let loading = $state(false);
	let error = $state('');
	let result = $state<any>(null);

	function extractId(input: string): string {
		const trimmed = input.trim();
		// Full URL: extract nr= param
		const match = trimmed.match(/[?&]nr=(\d+)/);
		if (match) return match[1];
		// Already a bare number
		if (/^\d+$/.test(trimmed)) return trimmed;
		return trimmed;
	}

	async function handleScrape() {
		const id = extractId(cagematchId);
		if (!id) return;
		loading = true;
		error = '';
		result = null;
		try {
			const res = await fetch(`${API_BASE}/browse/test-scrape/${id}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			result = await res.json();
		} catch (e: any) {
			error = e.message || 'Failed to scrape';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleScrape();
	}

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
</script>

<svelte:head>
	<title>Test Scrape - Titantron</title>
</svelte:head>

<div class="max-w-4xl mx-auto p-6">
	<h1 class="text-2xl font-bold mb-6">Scraper Test</h1>

	<div class="flex gap-3 mb-6">
		<input
			type="text"
			bind:value={cagematchId}
			onkeydown={handleKeydown}
			placeholder="Cagematch event ID (e.g. 1757)"
			class="flex-1 bg-titan-surface border border-titan-border rounded px-3 py-2 text-titan-text placeholder:text-titan-text-muted focus:outline-none focus:ring-1 focus:ring-titan-accent"
		/>
		<button
			onclick={handleScrape}
			disabled={loading || !cagematchId.trim()}
			class="px-4 py-2 bg-titan-accent rounded hover:opacity-90 disabled:opacity-50 shrink-0"
		>
			{loading ? 'Scraping...' : 'Scrape'}
		</button>
	</div>

	<p class="text-xs text-titan-text-muted mb-6">
		Enter a Cagematch event ID from the URL, e.g. <code class="text-titan-text">cagematch.net/?id=1&nr=<strong>1757</strong></code>
	</p>

	{#if error}
		<p class="text-red-400 mb-4">{error}</p>
	{/if}

	{#if result}
		<!-- Event Info -->
		<div class="bg-titan-surface border border-titan-border rounded-lg p-5 mb-6">
			<h2 class="text-xl font-bold mb-1">{result.event.name ?? 'Unknown'}</h2>
			<div class="flex flex-wrap gap-4 text-sm text-titan-text-muted">
				{#if result.event.date}<span>{result.event.date}</span>{/if}
				{#if result.event.promotion}<span>{result.event.promotion}</span>{/if}
				{#if result.event.location}<span>{result.event.location}</span>{/if}
				{#if result.event.arena}<span>{result.event.arena}</span>{/if}
			</div>
			<p class="text-sm text-titan-text-muted mt-2">{result.matches.length} matches</p>
		</div>

		<!-- Matches -->
		<div class="space-y-3">
			{#each result.matches as match}
				{@const sides = groupSides(match.participants)}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-4 overflow-hidden">
					<div class="flex items-start justify-between gap-4">
						<div class="flex-1 min-w-0">
							{#if match.title_name || match.match_type}
								<p class="text-xs mb-1">
									{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
									{#if match.title_name && match.match_type}{' '}{/if}
									{#if match.match_type}<span class="text-titan-text-muted">{match.match_type}</span>{/if}
								</p>
							{/if}
							<div class="font-medium break-words">
								{#each sides as side, sideIndex}
									{#if side.teamName}<span class="text-titan-text-muted text-sm">{side.teamName} (</span>{/if}{#each side.competitors as p, i}<span class="{!p.is_linked ? 'italic' : ''}">{p.name}</span>{#if i < side.competitors.length - 1}<span class="text-titan-text-muted">{' & '}</span>{/if}{/each}{#if side.teamName}<span class="text-titan-text-muted text-sm">)</span>{/if}{#if side.managers.length > 0}<span class="text-titan-text-muted text-sm">{' '}(w/{' '}{#each side.managers as mgr, i}{mgr.name}{#if i < side.managers.length - 1}{', '}{/if}{/each})</span>{/if}
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
								<span class="font-bold" style="color: {ratingColor(match.rating)}">{match.rating.toFixed(2)}</span>
								{#if match.votes}
									<span class="text-xs text-titan-text-muted block">{match.votes} votes</span>
								{/if}
							{/if}
						</div>
					</div>

					<!-- Raw data toggle -->
					<details class="mt-3">
						<summary class="text-xs text-titan-text-muted cursor-pointer hover:text-titan-text">Raw data</summary>
						<pre class="mt-2 text-xs text-titan-text-muted bg-titan-bg rounded p-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(match, null, 2)}</pre>
					</details>
				</div>
			{/each}
		</div>
	{/if}
</div>
