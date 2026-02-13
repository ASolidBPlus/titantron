<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { getPromotionEvents } from '$lib/api/client';
	import type { Event } from '$lib/types';
	import { ratingColor } from '$lib/utils/rating';

	let loading = $state(true);
	let promotionName = $state('');
	let promotionAbbr = $state('');
	let events = $state<Event[]>([]);
	let error = $state('');

	const promotionId = Number(page.params.promotionId);

	onMount(async () => {
		try {
			const data = await getPromotionEvents(promotionId);
			promotionName = data.promotion.name;
			promotionAbbr = data.promotion.abbreviation;
			events = data.events;
		} catch (e) {
			error = 'Failed to load events';
		} finally {
			loading = false;
		}
	});

	function formatDate(dateStr: string): string {
		return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
		});
	}
</script>

<svelte:head>
	<title>{promotionName || 'Events'} - Titantron</title>
</svelte:head>

<div class="max-w-4xl mx-auto p-6">
	<div class="mb-6">
		<a href="/browse" class="text-sm text-titan-text-muted hover:text-titan-text">&larr; All Promotions</a>
	</div>

	{#if loading}
		<p class="text-titan-text-muted">Loading...</p>
	{:else if error}
		<p class="text-red-400">{error}</p>
	{:else}
		<div class="flex items-center gap-3 mb-6">
			<h1 class="text-2xl font-bold">{promotionName}</h1>
			{#if promotionAbbr}
				<span class="text-titan-text-muted">({promotionAbbr})</span>
			{/if}
		</div>

		{#if events.length === 0}
			<div class="bg-titan-surface border border-titan-border rounded-lg p-6 text-center">
				<p class="text-titan-text-muted">No matched events yet. Run matching from the Matching page first.</p>
			</div>
		{:else}
			<div class="space-y-2">
				{#each events as event}
					<a
						href="/browse/event/{event.cagematch_event_id}"
						class="bg-titan-surface border border-titan-border rounded-lg p-4 hover:bg-titan-surface-hover transition-colors flex items-center justify-between block"
					>
						<div class="flex-1 min-w-0">
							<h3 class="font-semibold truncate">{event.name}</h3>
							<div class="flex gap-4 text-sm text-titan-text-muted mt-1">
								<span>{formatDate(event.date)}</span>
								{#if event.location}
									<span>{event.location}</span>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-4 shrink-0 ml-4">
							{#if event.rating}
								<div class="text-right">
									<span class="font-bold" style="color: {ratingColor(event.rating)}">{event.rating.toFixed(1)}</span>
									{#if event.votes}
										<span class="text-xs text-titan-text-muted block">{event.votes} votes</span>
									{/if}
								</div>
							{/if}
							{#if event.video_count && event.video_count > 0}
								<span class="bg-green-800/50 text-green-300 text-xs px-2 py-1 rounded">
									{event.video_count} video{event.video_count > 1 ? 's' : ''}
								</span>
							{/if}
						</div>
					</a>
				{/each}
			</div>
		{/if}
	{/if}
</div>
