<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getAuthStatus } from '$lib/api/client';

	let loading = $state(true);
	let connected = $state(false);
	let libraries = $state<{ id: number; name: string; promotion_name: string; video_count: number; last_synced: string | null }[]>([]);

	onMount(async () => {
		try {
			const status = await getAuthStatus();
			connected = status.connected;
			if (!connected) {
				goto('/setup');
				return;
			}
			libraries = status.libraries ?? [];
		} catch {
			goto('/setup');
			return;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Titantron</title>
</svelte:head>

{#if loading}
	<div class="flex items-center justify-center h-screen">
		<p class="text-titan-text-muted">Loading...</p>
	</div>
{:else}
	<div class="max-w-4xl mx-auto p-6">
		<header class="mb-8">
			<h1 class="text-3xl font-bold">
				<span class="text-titan-accent">TITAN</span><span class="text-titan-gold">TRON</span>
			</h1>
			<p class="text-titan-text-muted mt-1">Pro Wrestling Video Organizer</p>
		</header>

		<section>
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-xl font-semibold">Libraries</h2>
				<a href="/setup" class="text-sm text-titan-accent hover:underline">Manage</a>
			</div>

			{#if libraries.length === 0}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-6 text-center">
					<p class="text-titan-text-muted">No libraries configured yet.</p>
					<a href="/setup" class="inline-block mt-3 px-4 py-2 bg-titan-accent rounded font-medium hover:opacity-90">
						Set Up Libraries
					</a>
				</div>
			{:else}
				<div class="grid gap-4">
					{#each libraries as lib}
						<div class="bg-titan-surface border border-titan-border rounded-lg p-4">
							<div class="flex items-center justify-between">
								<div>
									<h3 class="font-semibold">{lib.name}</h3>
									<p class="text-sm text-titan-text-muted">{lib.promotion_name}</p>
								</div>
								<div class="text-right">
									<p class="text-lg font-bold">{lib.video_count}</p>
									<p class="text-xs text-titan-text-muted">videos</p>
								</div>
							</div>
							{#if lib.last_synced}
								<p class="text-xs text-titan-text-muted mt-2">
									Last synced: {new Date(lib.last_synced).toLocaleString()}
								</p>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</section>
	</div>
{/if}
