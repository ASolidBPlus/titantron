<script lang="ts">
	import { createChapter, deleteChapter } from '$lib/api/client';
	import type { Chapter, WrestlingMatch } from '$lib/types';

	interface Props {
		videoId: number;
		chapters: Chapter[];
		matches: WrestlingMatch[];
		currentTimeTicks: number;
		durationTicks: number;
		onChaptersChanged: () => Promise<void>;
		onSeekTo: (ticks: number) => void;
		onClose: () => void;
	}

	let {
		videoId,
		chapters,
		matches,
		currentTimeTicks,
		durationTicks,
		onChaptersChanged,
		onSeekTo,
		onClose,
	}: Props = $props();

	let newTitle = $state('');
	let newStartTicks = $state(0);
	let newMatchId = $state<number | null>(null);
	let creating = $state(false);

	let sortedChapters = $derived(
		[...chapters].sort((a, b) => a.start_ticks - b.start_ticks)
	);

	function matchTitle(match: WrestlingMatch): string {
		const sideMap = new Map<number, string[]>();
		for (const p of match.participants) {
			if (p.role === 'manager') continue;
			const side = p.side ?? 1;
			if (!sideMap.has(side)) sideMap.set(side, []);
			sideMap.get(side)!.push(p.name);
		}
		return [...sideMap.values()].map(names => names.join(' & ')).join(' vs. ');
	}

	function formatTicks(ticks: number): string {
		const totalSeconds = Math.floor(ticks / 10_000_000);
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function markMatch(match: WrestlingMatch) {
		newTitle = matchTitle(match);
		newStartTicks = currentTimeTicks;
		newMatchId = match.id;
	}

	function markStart() {
		newStartTicks = currentTimeTicks;
	}

	async function handleCreate() {
		if (!newTitle.trim()) return;
		creating = true;
		try {
			await createChapter(videoId, {
				title: newTitle.trim(),
				start_ticks: newStartTicks,
				match_id: newMatchId,
			});
			newTitle = '';
			newStartTicks = 0;
			newMatchId = null;
			await onChaptersChanged();
		} catch (e) {
			console.error('Failed to create chapter:', e);
		} finally {
			creating = false;
		}
	}

	async function handleDelete(chapterId: number) {
		try {
			await deleteChapter(videoId, chapterId);
			await onChaptersChanged();
		} catch (e) {
			console.error('Failed to delete chapter:', e);
		}
	}
</script>

<div class="w-[350px] bg-titan-surface border-l border-titan-border flex flex-col h-full overflow-hidden">
	<!-- Header -->
	<div class="flex items-center justify-between p-4 border-b border-titan-border shrink-0">
		<h2 class="font-semibold">Chapters</h2>
		<button onclick={onClose} class="text-titan-text-muted hover:text-titan-text">&times;</button>
	</div>

	<div class="flex-1 overflow-y-auto p-4 space-y-6">
		<!-- Match Card -->
		{#if matches.length > 0}
			<section>
				<h3 class="text-sm font-medium text-titan-text-muted mb-2">Match Card</h3>
				<div class="space-y-2">
					{#each matches as match}
						<div class="bg-titan-bg rounded p-3">
							<div class="flex items-start justify-between gap-2">
								<div class="min-w-0">
									{#if match.title_name || match.match_type}
										<p class="text-xs text-titan-text-muted mb-0.5">
											{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
											{#if match.title_name && match.match_type}{' '}{/if}
											{#if match.match_type}{match.match_type}{/if}
										</p>
									{/if}
									<p class="text-sm break-words">{matchTitle(match)}</p>
								</div>
								<button
									onclick={() => markMatch(match)}
									class="text-xs px-2 py-1 bg-titan-accent rounded hover:opacity-90 shrink-0"
									title="Mark current position as chapter start for this match"
								>
									Mark
								</button>
							</div>
						</div>
					{/each}
				</div>
			</section>
		{/if}

		<!-- Existing Chapters -->
		<section>
			<h3 class="text-sm font-medium text-titan-text-muted mb-2">
				Chapters ({chapters.length})
			</h3>
			{#if chapters.length === 0}
				<p class="text-xs text-titan-text-muted">No chapters yet. Use "Mark" on a match above or create one manually below.</p>
			{:else}
				<div class="space-y-1">
					{#each sortedChapters as chapter}
						<div class="flex items-center gap-2 bg-titan-bg rounded px-3 py-2 group">
							<button
								onclick={() => onSeekTo(chapter.start_ticks)}
								class="text-xs font-mono text-titan-accent hover:underline shrink-0"
								title="Seek to {formatTicks(chapter.start_ticks)}"
							>
								{formatTicks(chapter.start_ticks)}
							</button>
							<span class="text-sm truncate flex-1 min-w-0">{chapter.title}</span>
							{#if chapter.match_id}
								<span class="text-xs text-titan-gold shrink-0" title="Linked to match">M</span>
							{/if}
							<button
								onclick={() => handleDelete(chapter.id)}
								class="text-xs text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 shrink-0"
								title="Delete chapter"
							>
								&times;
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<!-- Add Chapter Form -->
		<section>
			<h3 class="text-sm font-medium text-titan-text-muted mb-2">Add Chapter</h3>
			<div class="space-y-3">
				<div>
					<label class="text-xs text-titan-text-muted block mb-1">Title</label>
					<input
						type="text"
						bind:value={newTitle}
						placeholder="Chapter title..."
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-1.5 text-sm text-titan-text placeholder:text-titan-text-muted/50 focus:outline-none focus:border-titan-accent"
					/>
				</div>
				<div>
					<label class="text-xs text-titan-text-muted block mb-1">Start Time</label>
					<div class="flex items-center gap-2">
						<span class="text-sm font-mono bg-titan-bg border border-titan-border rounded px-3 py-1.5 flex-1">
							{formatTicks(newStartTicks)}
						</span>
						<button
							onclick={markStart}
							class="text-xs px-3 py-1.5 bg-titan-accent rounded hover:opacity-90"
						>
							Mark
						</button>
					</div>
				</div>
				<div>
					<label class="text-xs text-titan-text-muted block mb-1">Link to Match</label>
					<select
						bind:value={newMatchId}
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-1.5 text-sm text-titan-text focus:outline-none focus:border-titan-accent"
					>
						<option value={null}>None</option>
						{#each matches as match}
							<option value={match.id}>#{match.match_number} - {matchTitle(match)}</option>
						{/each}
					</select>
				</div>
				<button
					onclick={handleCreate}
					disabled={!newTitle.trim() || creating}
					class="w-full text-sm px-3 py-2 bg-titan-accent rounded hover:opacity-90 disabled:opacity-50 font-medium"
				>
					{creating ? 'Creating...' : 'Create Chapter'}
				</button>
			</div>
		</section>
	</div>
</div>
