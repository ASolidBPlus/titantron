<script lang="ts">
	import type { Detection } from '$lib/types';

	interface Props {
		detections: Detection[];
		onSeekTo: (ticks: number) => void;
		onAcceptChapter: (ticks: number, title: string) => void;
	}

	let {
		detections,
		onSeekTo,
		onAcceptChapter,
	}: Props = $props();

	// Filter toggles
	let showTypes = $state<Record<string, boolean>>({
		scene_change: true,
		dark_frame: true,
		graphics_change: true,
		bell: true,
		music_start: true,
	});

	let filteredDetections = $derived(
		detections.filter(d => showTypes[d.type] !== false)
	);

	// Inline chapter title editing
	let editingIdx = $state<number | null>(null);
	let editTitle = $state('');

	function formatTime(ticks: number): string {
		const totalSeconds = Math.floor(ticks / 10_000_000);
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
		return `${m}:${String(s).padStart(2, '0')}`;
	}

	function typeLabel(type: string): string {
		switch (type) {
			case 'scene_change': return 'Scene Change';
			case 'dark_frame': return 'Dark Frame';
			case 'graphics_change': return 'Graphics';
			case 'bell': return 'Bell';
			case 'music_start': return 'Music Start';
			default: return type;
		}
	}

	function typeColor(type: string): string {
		switch (type) {
			case 'scene_change': return 'bg-blue-500/20 text-blue-400';
			case 'dark_frame': return 'bg-gray-500/20 text-gray-400';
			case 'graphics_change': return 'bg-purple-500/20 text-purple-400';
			case 'bell': return 'bg-amber-500/20 text-amber-400';
			case 'music_start': return 'bg-green-500/20 text-green-400';
			default: return 'bg-gray-500/20 text-gray-400';
		}
	}

	function defaultTitle(type: string): string {
		switch (type) {
			case 'bell': return 'Match Start';
			case 'music_start': return 'Entrance';
			case 'scene_change': return 'Segment Break';
			case 'dark_frame': return 'Segment Break';
			case 'graphics_change': return 'Graphics';
			default: return 'Chapter';
		}
	}

	function startAccept(idx: number, type: string) {
		editingIdx = idx;
		editTitle = defaultTitle(type);
	}

	function confirmAccept(ticks: number) {
		if (editTitle.trim()) {
			onAcceptChapter(ticks, editTitle.trim());
		}
		editingIdx = null;
		editTitle = '';
	}

	function cancelAccept() {
		editingIdx = null;
		editTitle = '';
	}

	const allTypes = ['scene_change', 'dark_frame', 'graphics_change', 'bell', 'music_start'] as const;
</script>

<div class="bg-titan-surface border border-titan-border rounded-lg overflow-hidden">
	<!-- Header with filter toggles -->
	<div class="flex items-center gap-2 px-3 py-2 border-b border-titan-border flex-wrap">
		<span class="text-xs font-medium text-titan-text-muted">Detections</span>
		<span class="text-xs text-titan-text-muted">({filteredDetections.length})</span>
		<div class="flex-1"></div>
		<div class="flex items-center gap-1.5">
			{#each allTypes as t}
				{@const count = detections.filter(d => d.type === t).length}
				{#if count > 0}
					<button
						onclick={() => { showTypes[t] = !showTypes[t]; }}
						class="text-[10px] px-1.5 py-0.5 rounded transition-opacity {showTypes[t] ? typeColor(t) : 'bg-titan-border text-titan-text-muted opacity-40'}"
					>
						{typeLabel(t)} ({count})
					</button>
				{/if}
			{/each}
		</div>
	</div>

	<!-- Detection table -->
	<div class="max-h-[400px] overflow-y-auto">
		{#if filteredDetections.length === 0}
			<p class="text-sm text-titan-text-muted text-center py-6">No detections to show</p>
		{:else}
			<table class="w-full text-sm">
				<thead class="sticky top-0 bg-titan-surface border-b border-titan-border">
					<tr class="text-xs text-titan-text-muted">
						<th class="text-left py-1.5 px-3 font-medium w-20">Time</th>
						<th class="text-left py-1.5 px-3 font-medium">Type</th>
						<th class="text-left py-1.5 px-3 font-medium w-16">Conf</th>
						<th class="text-right py-1.5 px-3 font-medium w-48">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredDetections as det, i}
						<tr class="border-b border-titan-border/50 hover:bg-titan-surface-hover group">
							<td class="py-1.5 px-3">
								<button
									onclick={() => onSeekTo(det.timestamp_ticks)}
									class="text-xs font-mono text-titan-accent hover:underline"
								>
									{formatTime(det.timestamp_ticks)}
								</button>
							</td>
							<td class="py-1.5 px-3">
								<span class="text-[10px] px-1.5 py-0.5 rounded {typeColor(det.type)}">
									{typeLabel(det.type)}
								</span>
							</td>
							<td class="py-1.5 px-3 text-xs text-titan-text-muted">
								{(det.confidence * 100).toFixed(0)}%
							</td>
							<td class="py-1.5 px-3 text-right">
								{#if editingIdx === i}
									<div class="flex items-center gap-1 justify-end">
										<input
											type="text"
											bind:value={editTitle}
											onkeydown={(e) => { if (e.key === 'Enter') confirmAccept(det.timestamp_ticks); if (e.key === 'Escape') cancelAccept(); }}
											class="w-32 text-xs bg-titan-bg border border-titan-border rounded px-2 py-1 focus:outline-none focus:border-titan-accent"
											autofocus
										/>
										<button
											onclick={() => confirmAccept(det.timestamp_ticks)}
											class="text-[10px] px-1.5 py-1 bg-titan-accent text-white rounded hover:opacity-90"
										>
											Add
										</button>
										<button
											onclick={cancelAccept}
											class="text-[10px] px-1.5 py-1 bg-titan-border rounded hover:bg-titan-surface-hover"
										>
											Cancel
										</button>
									</div>
								{:else}
									<button
										onclick={() => startAccept(i, det.type)}
										class="text-[10px] px-2 py-1 bg-titan-accent/15 text-titan-accent rounded hover:bg-titan-accent/25 opacity-0 group-hover:opacity-100 transition-opacity"
									>
										Accept as Chapter
									</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>
</div>
