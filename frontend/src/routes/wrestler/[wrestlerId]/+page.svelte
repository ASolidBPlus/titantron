<script lang="ts">
	import { page } from '$app/state';
	import { getWrestler, getWrestlerMatches } from '$lib/api/client';
	import type { WrestlerProfile, WrestlerMatchEntry, MatchParticipant } from '$lib/types';
	import { ratingColor } from '$lib/utils/rating';

	const wrestlerId = $derived(Number(page.params.wrestlerId));

	let loading = $state(true);
	let wrestler = $state<WrestlerProfile | null>(null);
	let matches = $state<WrestlerMatchEntry[]>([]);
	let matchTotal = $state(0);
	let matchOffset = $state(0);
	let loadingMore = $state(false);
	let error = $state('');

	$effect(() => {
		const id = wrestlerId;
		loading = true;
		error = '';
		wrestler = null;
		matches = [];
		matchTotal = 0;
		matchOffset = 0;

		Promise.all([
			getWrestler(id),
			getWrestlerMatches(id, 50, 0),
		]).then(([profile, history]) => {
			wrestler = profile;
			matches = history.matches;
			matchTotal = history.total;
			matchOffset = history.matches.length;
		}).catch(() => {
			error = 'Failed to load wrestler';
		}).finally(() => {
			loading = false;
		});
	});

	async function loadMore() {
		loadingMore = true;
		try {
			const history = await getWrestlerMatches(wrestlerId, 50, matchOffset);
			matches = [...matches, ...history.matches];
			matchOffset += history.matches.length;
		} catch (e) {
			console.error('Failed to load more matches:', e);
		} finally {
			loadingMore = false;
		}
	}

	interface SideGroup {
		teamName: string | null;
		competitors: MatchParticipant[];
		managers: MatchParticipant[];
	}

	function getSides(participants: MatchParticipant[]): SideGroup[] {
		const sideMap = new Map<number, MatchParticipant[]>();
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

	function formatDate(dateStr: string): string {
		return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
		});
	}

	const infoItems = $derived.by(() => {
		if (!wrestler) return [];
		const items: { label: string; value: string }[] = [];
		if (wrestler.birth_place) items.push({ label: 'From', value: wrestler.birth_place });
		if (wrestler.birth_date) items.push({ label: 'Born', value: formatDate(wrestler.birth_date) });
		if (wrestler.height) items.push({ label: 'Height', value: wrestler.height });
		if (wrestler.weight) items.push({ label: 'Weight', value: wrestler.weight });
		if (wrestler.style) items.push({ label: 'Style', value: wrestler.style });
		if (wrestler.debut) items.push({ label: 'Debut', value: wrestler.debut });
		if (wrestler.trainers) items.push({ label: 'Trainers', value: wrestler.trainers });
		if (wrestler.nicknames) items.push({ label: 'Nicknames', value: wrestler.nicknames });
		if (wrestler.signature_moves) items.push({ label: 'Signatures', value: wrestler.signature_moves });
		if (wrestler.alter_egos) items.push({ label: 'Also known as', value: wrestler.alter_egos });
		return items;
	});
</script>

<svelte:head>
	<title>{wrestler?.name || 'Wrestler'} - Titantron</title>
</svelte:head>

<div class="max-w-4xl mx-auto p-6">
	{#if loading}
		<p class="text-titan-text-muted">Loading...</p>
	{:else if error && !wrestler}
		<p class="text-red-400">{error}</p>
	{:else if wrestler}
		<!-- Profile Header -->
		<div class="bg-titan-surface border border-titan-border rounded-lg p-6 mb-6">
			<div class="flex gap-6">
				{#if wrestler.image_url}
					<img
						src={wrestler.image_url}
						alt={wrestler.name}
						class="w-32 h-40 rounded-lg object-cover shrink-0"
					/>
				{/if}
				<div class="flex-1 min-w-0">
					<div class="flex items-start justify-between gap-4">
						<h1 class="text-2xl font-bold break-words">{wrestler.name}</h1>
						{#if wrestler.cagematch_wrestler_id}
							<a
								href="https://www.cagematch.net/?id=2&nr={wrestler.cagematch_wrestler_id}"
								target="_blank"
								rel="noopener noreferrer"
								class="text-xs text-titan-text-muted hover:text-titan-accent shrink-0"
							>
								Cagematch
							</a>
						{/if}
					</div>
					{#if !wrestler.is_linked}
						<p class="text-xs text-titan-text-muted mt-1 italic">No Cagematch profile linked</p>
					{/if}
					<div class="flex items-center gap-4 mt-2 text-sm text-titan-text-muted">
						<span>{wrestler.match_count} matches in library</span>
						{#if wrestler.rating}
							<span>
								<span class="font-bold" style="color: {ratingColor(wrestler.rating)}">{wrestler.rating.toFixed(2)}</span>
								{#if wrestler.votes}
									<span class="text-xs">({wrestler.votes} votes)</span>
								{/if}
							</span>
						{/if}
					</div>

					{#if infoItems.length > 0}
						<div class="grid grid-cols-2 gap-x-6 gap-y-1.5 mt-4 text-sm">
							{#each infoItems as item}
								<div>
									<span class="text-titan-text-muted">{item.label}:</span>
									<span class="ml-1">{item.value}</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Match History -->
		<h2 class="text-lg font-semibold mb-3">Matches in Library</h2>
		{#if matches.length === 0}
			<p class="text-titan-text-muted">No matches found in library.</p>
		{:else}
			<div class="space-y-2">
				{#each matches as match}
					{@const sides = getSides(match.participants)}
					<div class="bg-titan-surface border border-titan-border rounded-lg p-4">
						<div class="flex items-start justify-between gap-4">
							<div class="flex-1 min-w-0">
								<!-- Event link + date -->
								<div class="flex items-center gap-2 mb-1">
									<a
										href="/browse/event/{match.event.cagematch_event_id}"
										class="text-sm text-titan-text-muted hover:text-titan-accent"
									>
										{match.event.name}
									</a>
									<span class="text-xs text-titan-text-muted">{formatDate(match.event.date)}</span>
								</div>

								{#if match.title_name || match.match_type}
									<p class="text-xs mb-1">
										{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
										{#if match.title_name && match.match_type}{' '}{/if}
										{#if match.match_type}<span class="text-titan-text-muted">{match.match_type}</span>{/if}
									</p>
								{/if}

								<!-- Participants -->
								<div class="text-sm break-words">
									{#each sides as side, sideIndex}
										{#if side.teamName}<span class="text-titan-text-muted text-xs">{side.teamName} (</span>{/if}{#each side.competitors as p, i}{#if p.cagematch_wrestler_id === wrestlerId}<span class="font-bold {match.is_winner ? 'text-titan-gold' : ''}">{p.name}</span>{:else if p.cagematch_wrestler_id}<a href="/wrestler/{p.cagematch_wrestler_id}" class="{p.is_winner ? 'text-titan-gold' : ''} hover:underline">{p.name}</a>{:else}<span class="{p.is_winner ? 'text-titan-gold' : ''} italic">{p.name}</span>{/if}{#if i < side.competitors.length - 1}<span class="text-titan-text-muted">{' & '}</span>{/if}{/each}{#if side.teamName}<span class="text-titan-text-muted text-xs">)</span>{/if}{#if side.managers.length > 0}<span class="text-titan-text-muted text-xs">{' '}(w/{' '}{#each side.managers as mgr, i}{#if mgr.cagematch_wrestler_id}<a href="/wrestler/{mgr.cagematch_wrestler_id}" class="hover:underline">{mgr.name}</a>{:else}{mgr.name}{/if}{#if i < side.managers.length - 1}{', '}{/if}{/each})</span>{/if}
										{#if sideIndex < sides.length - 1}
											<span class="text-titan-accent font-bold mx-1">vs.</span>
										{/if}
									{/each}
								</div>
							</div>
							<div class="text-right shrink-0">
								{#if match.rating}
									<span class="font-bold" style="color: {ratingColor(match.rating)}">{match.rating.toFixed(2)}</span>
								{/if}
								{#if match.duration}
									<span class="text-xs text-titan-text-muted block">{match.duration}</span>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>

			{#if matchOffset < matchTotal}
				<div class="mt-4 text-center">
					<button
						onclick={loadMore}
						disabled={loadingMore}
						class="px-4 py-2 bg-titan-surface border border-titan-border rounded hover:border-titan-accent disabled:opacity-50"
					>
						{loadingMore ? 'Loading...' : `Load More (${matchTotal - matchOffset} remaining)`}
					</button>
				</div>
			{/if}
		{/if}
	{/if}
</div>
