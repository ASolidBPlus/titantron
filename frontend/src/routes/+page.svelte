<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getAuthStatus } from '$lib/api/client';

	let checked = $state(false);
	let connected = $state(false);

	onMount(async () => {
		try {
			const status = await getAuthStatus();
			if (status.connected) {
				goto('/browse', { replaceState: true });
				return;
			}
		} catch {
			// Not connected, show welcome
		}
		checked = true;
	});
</script>

<svelte:head>
	<title>Titantron</title>
</svelte:head>

{#if checked}
	<div class="flex items-center justify-center min-h-[calc(100vh-3.5rem)]">
		<div class="text-center max-w-md px-6">
			<h1 class="text-5xl font-black tracking-tight mb-2">
				<span class="text-titan-accent">TITAN</span><span class="text-titan-gold">TRON</span>
			</h1>
			<p class="text-titan-text-muted mb-8">
				Pro wrestling video organizer powered by Jellyfin and Cagematch.net
			</p>
			<a
				href="/admin/settings"
				class="inline-block px-6 py-3 bg-titan-accent text-black font-bold rounded-lg hover:bg-titan-accent/90 transition-colors"
			>
				Get Started
			</a>
		</div>
	</div>
{/if}
