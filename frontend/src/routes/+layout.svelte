<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<div class="min-h-screen bg-titan-bg text-titan-text">
	{@render children()}
</div>
