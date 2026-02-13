<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getAuthStatus } from '$lib/api/client';

	onMount(async () => {
		try {
			const status = await getAuthStatus();
			if (status.connected) {
				goto('/browse', { replaceState: true });
			} else {
				goto('/admin/setup', { replaceState: true });
			}
		} catch {
			goto('/admin/setup', { replaceState: true });
		}
	});
</script>

<div class="flex items-center justify-center h-[calc(100vh-3.5rem)]">
	<p class="text-titan-text-muted">Loading...</p>
</div>
