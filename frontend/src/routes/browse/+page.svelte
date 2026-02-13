<script lang="ts">
	import { onMount } from 'svelte';
	import { getPromotions } from '$lib/api/client';
	import type { Promotion } from '$lib/types';

	let loading = $state(true);
	let promotions = $state<Promotion[]>([]);
	let error = $state('');

	onMount(async () => {
		try {
			promotions = await getPromotions();
		} catch (e) {
			error = 'Failed to load promotions';
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Browse - Titantron</title>
</svelte:head>

<div class="max-w-4xl mx-auto p-6">
	<h1 class="text-2xl font-bold mb-6">Browse Promotions</h1>

	{#if loading}
		<p class="text-titan-text-muted">Loading...</p>
	{:else if error}
		<p class="text-red-400">{error}</p>
	{:else if promotions.length === 0}
		<div class="bg-titan-surface border border-titan-border rounded-lg p-6 text-center">
			<p class="text-titan-text-muted">No promotions configured yet.</p>
			<a href="/admin/setup" class="inline-block mt-3 px-4 py-2 bg-titan-accent rounded font-medium hover:opacity-90">
				Set Up Libraries
			</a>
		</div>
	{:else}
		<div class="grid gap-4">
			{#each promotions as promo}
				<a
					href="/browse/{promo.cagematch_id}"
					class="bg-titan-surface border border-titan-border rounded-lg p-5 hover:bg-titan-surface-hover transition-colors block"
				>
					<div class="flex items-center justify-between">
						<div>
							<h2 class="text-lg font-semibold">{promo.name}</h2>
							{#if promo.abbreviation}
								<span class="text-sm text-titan-text-muted">{promo.abbreviation}</span>
							{/if}
						</div>
						<div class="flex gap-6 text-right">
							<div>
								<p class="text-lg font-bold">{promo.event_count}</p>
								<p class="text-xs text-titan-text-muted">events</p>
							</div>
							<div>
								<p class="text-lg font-bold">{promo.video_count}</p>
								<p class="text-xs text-titan-text-muted">videos</p>
							</div>
						</div>
					</div>
				</a>
			{/each}
		</div>
	{/if}
</div>
