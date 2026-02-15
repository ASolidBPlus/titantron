<script lang="ts">
	import { onMount } from 'svelte';
	import { ratingColor } from '$lib/utils/rating';
	import {
		getConfiguredLibraries,
		triggerMatching,
		getMatchingStatus,
		getLibraryVideos,
		getVideoCandidates,
		confirmMatch,
		rejectMatch,
		assignMatch,
		rematchVideo,
		bulkConfirm,
		bulkReject,
		searchEvents,
	} from '$lib/api/client';
	import type { ConfiguredLibrary, EventSearchResult } from '$lib/api/client';
	import type { VideoItem, MatchCandidate, MatchStatus } from '$lib/types';

	let libraries = $state<ConfiguredLibrary[]>([]);
	let selectedLibraryId = $state<number | null>(null);
	let matchStatus = $state<MatchStatus | null>(null);
	let videos = $state<VideoItem[]>([]);
	let filterStatus = $state<string>('');
	let loading = $state(true);
	let loadingVideos = $state(false);
	let showLog = $state(false);

	// Candidate review modal state
	let reviewVideoId = $state<number | null>(null);
	let reviewVideoTitle = $state('');
	let reviewCandidates = $state<MatchCandidate[]>([]);
	let loadingCandidates = $state(false);

	// Manual event search in modal
	let eventSearchQuery = $state('');
	let eventSearchResults = $state<EventSearchResult[]>([]);
	let searchingEvents = $state(false);

	// Bulk selection
	let selectedVideoIds = $state<Set<number>>(new Set());
	let selectMode = $state(false);

	let logContainer: HTMLDivElement | undefined = $state();
	let pollInterval: ReturnType<typeof setInterval> | null = null;

	onMount(() => {
		(async () => {
			try {
				libraries = await getConfiguredLibraries();
				matchStatus = await getMatchingStatus();
				if (matchStatus?.is_running) {
					showLog = true;
					startPolling();
				}
			} catch {
				// ignore
			} finally {
				loading = false;
			}
		})();

		return () => {
			if (pollInterval) clearInterval(pollInterval);
		};
	});

	function scrollLogToBottom() {
		if (logContainer) {
			logContainer.scrollTop = logContainer.scrollHeight;
		}
	}

	function startPolling() {
		if (pollInterval) return;
		pollInterval = setInterval(async () => {
			matchStatus = await getMatchingStatus();
			setTimeout(scrollLogToBottom, 50);
			if (!matchStatus?.is_running) {
				if (pollInterval) clearInterval(pollInterval);
				pollInterval = null;
				if (selectedLibraryId) {
					await loadVideos();
				}
			}
		}, 1500);
	}

	async function handleMatch(libraryId: number) {
		try {
			await triggerMatching(libraryId);
			matchStatus = await getMatchingStatus();
			showLog = true;
			startPolling();
		} catch (e: any) {
			alert(e.message || 'Failed to start matching');
		}
	}

	async function loadVideos() {
		if (!selectedLibraryId) return;
		loadingVideos = true;
		selectedVideoIds = new Set();
		try {
			videos = await getLibraryVideos(selectedLibraryId, filterStatus || undefined);
		} catch {
			videos = [];
		} finally {
			loadingVideos = false;
		}
	}

	async function selectLibrary(libId: number) {
		selectedLibraryId = libId;
		await loadVideos();
	}

	async function changeFilter(status: string) {
		filterStatus = status;
		selectMode = false;
		selectedVideoIds = new Set();
		await loadVideos();
	}

	async function handleConfirm(videoId: number) {
		await confirmMatch(videoId);
		await loadVideos();
	}

	async function handleReject(videoId: number) {
		await rejectMatch(videoId);
		await loadVideos();
	}

	async function handleRematch(videoId: number) {
		try {
			await rematchVideo(videoId);
			await loadVideos();
		} catch (e: any) {
			alert(e.message || 'Failed to rematch');
		}
	}

	async function openCandidates(video: VideoItem) {
		reviewVideoId = video.id;
		reviewVideoTitle = video.title;
		eventSearchQuery = '';
		eventSearchResults = [];
		loadingCandidates = true;
		try {
			const result = await getVideoCandidates(video.id);
			reviewCandidates = result.candidates;
		} catch {
			reviewCandidates = [];
		} finally {
			loadingCandidates = false;
		}
	}

	function closeCandidates() {
		reviewVideoId = null;
		reviewCandidates = [];
		eventSearchQuery = '';
		eventSearchResults = [];
	}

	async function handleAssign(videoId: number, cagematchEventId: number) {
		try {
			await assignMatch(videoId, cagematchEventId);
			closeCandidates();
			await loadVideos();
		} catch (e: any) {
			alert(e.message || 'Failed to assign');
		}
	}

	let searchDebounce: ReturnType<typeof setTimeout> | null = null;
	async function handleEventSearch() {
		if (searchDebounce) clearTimeout(searchDebounce);
		if (eventSearchQuery.length < 2) {
			eventSearchResults = [];
			return;
		}
		searchDebounce = setTimeout(async () => {
			searchingEvents = true;
			try {
				eventSearchResults = await searchEvents(eventSearchQuery);
			} catch {
				eventSearchResults = [];
			} finally {
				searchingEvents = false;
			}
		}, 300);
	}

	// Bulk operations
	function toggleSelectMode() {
		selectMode = !selectMode;
		if (!selectMode) selectedVideoIds = new Set();
	}

	function toggleVideoSelection(id: number) {
		const next = new Set(selectedVideoIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedVideoIds = next;
	}

	function selectAll() {
		selectedVideoIds = new Set(videos.map(v => v.id));
	}

	function selectNone() {
		selectedVideoIds = new Set();
	}

	async function handleBulkConfirm() {
		if (selectedVideoIds.size === 0) return;
		try {
			await bulkConfirm([...selectedVideoIds]);
			selectMode = false;
			selectedVideoIds = new Set();
			await loadVideos();
		} catch (e: any) {
			alert(e.message || 'Failed to bulk confirm');
		}
	}

	async function handleBulkReject() {
		if (selectedVideoIds.size === 0) return;
		if (!confirm(`Reject ${selectedVideoIds.size} matches? This will reset them to unmatched.`)) return;
		try {
			await bulkReject([...selectedVideoIds]);
			selectMode = false;
			selectedVideoIds = new Set();
			await loadVideos();
		} catch (e: any) {
			alert(e.message || 'Failed to bulk reject');
		}
	}

	function statusColor(status: string): string {
		switch (status) {
			case 'confirmed': return 'bg-green-800/50 text-green-300';
			case 'auto_matched': return 'bg-blue-800/50 text-blue-300';
			case 'suggested': return 'bg-yellow-800/50 text-yellow-300';
			case 'unmatched': return 'bg-red-800/50 text-red-300';
			default: return 'bg-gray-800/50 text-gray-300';
		}
	}

	function logLineColor(msg: string): string {
		if (msg.startsWith('Auto-matched:')) return 'text-blue-300';
		if (msg.startsWith('Suggested:')) return 'text-yellow-300';
		if (msg.startsWith('No match:')) return 'text-red-300';
		if (msg.startsWith('ERROR:')) return 'text-red-400 font-bold';
		if (msg.startsWith('Done:')) return 'text-green-300 font-bold';
		return 'text-titan-text-muted';
	}

	const statusFilters = [
		{ value: '', label: 'All' },
		{ value: 'unmatched', label: 'Unmatched' },
		{ value: 'suggested', label: 'Suggested' },
		{ value: 'auto_matched', label: 'Auto-matched' },
		{ value: 'confirmed', label: 'Confirmed' },
	];
</script>

<svelte:head>
	<title>Matching - Titantron</title>
</svelte:head>

<div class="max-w-5xl mx-auto p-6">
	<h1 class="text-2xl font-bold mb-6">Video Matching</h1>

	{#if loading}
		<p class="text-titan-text-muted">Loading...</p>
	{:else}
		<!-- Matching Status Banner -->
		{#if matchStatus?.is_running}
			<div class="bg-blue-900/30 border border-blue-700 rounded-lg p-4 mb-6">
				<div class="flex items-center gap-3 mb-3">
					<div class="animate-spin h-5 w-5 border-2 border-blue-400 border-t-transparent rounded-full"></div>
					<span class="flex-1 truncate">{matchStatus.message || 'Matching in progress...'}</span>
				</div>
				{#if matchStatus.progress !== null && matchStatus.total}
					<div class="w-full bg-blue-950 rounded-full h-2 mb-2">
						<div
							class="bg-blue-400 h-2 rounded-full transition-all duration-300"
							style="width: {(matchStatus.progress / matchStatus.total) * 100}%"
						></div>
					</div>
					<p class="text-xs text-blue-300">{matchStatus.progress} / {matchStatus.total} videos processed</p>
				{/if}
			</div>
		{:else if matchStatus?.results}
			<div class="bg-titan-surface border border-titan-border rounded-lg p-4 mb-6">
				<div class="flex items-center justify-between">
					<div>
						<p class="font-medium mb-2">Last Match Result</p>
						<div class="flex gap-6 text-sm">
							<span>Total: <strong>{matchStatus.results.total}</strong></span>
							<span class="text-blue-300">Auto: <strong>{matchStatus.results.auto_matched}</strong></span>
							<span class="text-yellow-300">Suggested: <strong>{matchStatus.results.suggested}</strong></span>
							<span class="text-red-300">Unmatched: <strong>{matchStatus.results.unmatched}</strong></span>
						</div>
					</div>
					<button
						onclick={() => showLog = !showLog}
						class="text-xs px-3 py-1.5 bg-titan-border rounded hover:bg-titan-surface-hover"
					>
						{showLog ? 'Hide' : 'Show'} Log
					</button>
				</div>
			</div>
		{/if}

		<!-- Log Viewer -->
		{#if showLog && matchStatus?.log && matchStatus.log.length > 0}
			<div class="bg-titan-bg border border-titan-border rounded-lg mb-6 overflow-hidden">
				<div class="flex items-center justify-between px-4 py-2 border-b border-titan-border bg-titan-surface">
					<span class="text-sm font-medium">Matching Log</span>
					<button onclick={() => showLog = false} class="text-titan-text-muted hover:text-titan-text text-sm">&times;</button>
				</div>
				<div
					bind:this={logContainer}
					class="p-3 max-h-64 overflow-y-auto font-mono text-xs leading-relaxed"
				>
					{#each matchStatus.log as entry}
						<div class="{logLineColor(entry.message)}">
							<span class="text-titan-text-muted opacity-50">{entry.time.split('T')[1]}</span>
							{entry.message}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Library Selection -->
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-6">
			{#each libraries as lib}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-4 {selectedLibraryId === lib.id ? 'ring-2 ring-titan-accent' : ''}">
					<h3 class="font-semibold">{lib.name}</h3>
					<p class="text-sm text-titan-text-muted">{lib.promotion_name}</p>
					<p class="text-sm text-titan-text-muted mt-1">{lib.video_count} videos</p>
					<div class="flex gap-2 mt-3">
						<button
							onclick={() => selectLibrary(lib.id)}
							class="text-xs px-3 py-1.5 bg-titan-border rounded hover:bg-titan-surface-hover"
						>
							View Videos
						</button>
						<button
							onclick={() => handleMatch(lib.id)}
							disabled={matchStatus?.is_running}
							class="text-xs px-3 py-1.5 bg-titan-accent rounded hover:opacity-90 disabled:opacity-50"
						>
							Run Matching
						</button>
					</div>
				</div>
			{/each}
		</div>

		<!-- Videos Table -->
		{#if selectedLibraryId}
			<div class="mb-4 flex items-center justify-between gap-4">
				<div class="flex gap-2 flex-wrap">
					{#each statusFilters as f}
						<button
							onclick={() => changeFilter(f.value)}
							class="text-xs px-3 py-1.5 rounded transition-colors {filterStatus === f.value ? 'bg-titan-accent text-white' : 'bg-titan-surface border border-titan-border text-titan-text-muted hover:text-titan-text'}"
						>
							{f.label}
						</button>
					{/each}
				</div>
				{#if videos.length > 0}
					<button
						onclick={toggleSelectMode}
						class="text-xs px-3 py-1.5 rounded {selectMode ? 'bg-titan-accent text-white' : 'bg-titan-surface border border-titan-border text-titan-text-muted hover:text-titan-text'}"
					>
						{selectMode ? 'Cancel' : 'Select'}
					</button>
				{/if}
			</div>

			<!-- Bulk action bar -->
			{#if selectMode}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-3 mb-4 flex items-center gap-3">
					<span class="text-sm text-titan-text-muted">{selectedVideoIds.size} selected</span>
					<button onclick={selectAll} class="text-xs px-2 py-1 bg-titan-border rounded hover:bg-titan-surface-hover">All</button>
					<button onclick={selectNone} class="text-xs px-2 py-1 bg-titan-border rounded hover:bg-titan-surface-hover">None</button>
					<div class="flex-1"></div>
					<button
						onclick={handleBulkConfirm}
						disabled={selectedVideoIds.size === 0}
						class="text-xs px-3 py-1.5 bg-green-800/50 text-green-300 rounded hover:bg-green-700/50 disabled:opacity-50"
					>
						Confirm Selected
					</button>
					<button
						onclick={handleBulkReject}
						disabled={selectedVideoIds.size === 0}
						class="text-xs px-3 py-1.5 bg-red-800/50 text-red-300 rounded hover:bg-red-700/50 disabled:opacity-50"
					>
						Reject Selected
					</button>
				</div>
			{/if}

			{#if loadingVideos}
				<p class="text-titan-text-muted">Loading videos...</p>
			{:else if videos.length === 0}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-6 text-center">
					<p class="text-titan-text-muted">No videos found{filterStatus ? ` with status "${filterStatus}"` : ''}.</p>
				</div>
			{:else}
				<div class="space-y-2">
					{#each videos as video}
						<div class="bg-titan-surface border border-titan-border rounded-lg p-4 {selectMode && selectedVideoIds.has(video.id) ? 'ring-2 ring-titan-accent' : ''}">
							<div class="flex items-center justify-between gap-4">
								{#if selectMode}
									<button
										onclick={() => toggleVideoSelection(video.id)}
										class="shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center {selectedVideoIds.has(video.id) ? 'border-titan-accent bg-titan-accent text-white' : 'border-titan-border'}"
									>
										{#if selectedVideoIds.has(video.id)}&#10003;{/if}
									</button>
								{/if}
								<div class="flex-1 min-w-0">
									<p class="font-medium truncate">{video.title}</p>
									<div class="flex gap-3 text-sm text-titan-text-muted mt-1">
										{#if video.extracted_date}
											<span>{video.extracted_date}</span>
										{/if}
										{#if video.matched_event_name}
											<span class="text-titan-text">&rarr; {video.matched_event_name}</span>
										{/if}
									</div>
								</div>
								<div class="flex items-center gap-2 shrink-0">
									<span class="text-xs px-2 py-1 rounded {statusColor(video.match_status)}">
										{video.match_status}
									</span>
									{#if video.match_confidence}
										<span class="text-xs text-titan-text-muted">{(video.match_confidence * 100).toFixed(0)}%</span>
									{/if}
									{#if video.match_status === 'suggested' || video.match_status === 'auto_matched'}
										<button onclick={() => handleConfirm(video.id)} class="text-xs px-2 py-1 bg-green-800/50 text-green-300 rounded hover:bg-green-700/50" title="Confirm">
											&#10003;
										</button>
										<button onclick={() => handleReject(video.id)} class="text-xs px-2 py-1 bg-red-800/50 text-red-300 rounded hover:bg-red-700/50" title="Reject">
											&#10007;
										</button>
									{/if}
									{#if video.match_status !== 'confirmed'}
										<button onclick={() => openCandidates(video)} class="text-xs px-2 py-1 bg-titan-border rounded hover:bg-titan-surface-hover" title="Find matches">
											Search
										</button>
									{/if}
									{#if video.match_status === 'confirmed'}
										<button onclick={() => handleReject(video.id)} class="text-xs px-2 py-1 bg-titan-border rounded hover:bg-titan-surface-hover text-titan-text-muted" title="Unmatch">
											Unmatch
										</button>
									{/if}
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		{/if}
	{/if}
</div>

<!-- Candidate Review Modal -->
{#if reviewVideoId !== null}
	<div class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" role="dialog">
		<div class="bg-titan-surface border border-titan-border rounded-lg max-w-2xl w-full max-h-[80vh] overflow-y-auto">
			<div class="p-5 border-b border-titan-border flex items-center justify-between sticky top-0 bg-titan-surface z-10">
				<div>
					<h3 class="font-semibold">Match Candidates</h3>
					<p class="text-sm text-titan-text-muted truncate">{reviewVideoTitle}</p>
				</div>
				<button onclick={closeCandidates} class="text-titan-text-muted hover:text-titan-text text-xl">&times;</button>
			</div>
			<div class="p-5">
				{#if loadingCandidates}
					<p class="text-titan-text-muted">Searching Cagematch...</p>
				{:else if reviewCandidates.length === 0}
					<p class="text-titan-text-muted mb-4">No candidates found for this date range.</p>
				{:else}
					<div class="space-y-2 mb-6">
						{#each reviewCandidates as candidate}
							<div class="bg-titan-bg border border-titan-border rounded-lg p-4 flex items-center justify-between">
								<div class="flex-1 min-w-0">
									<p class="font-medium">{candidate.name}</p>
									<div class="flex gap-3 text-sm text-titan-text-muted mt-1">
										<span>{candidate.date}</span>
										{#if candidate.location}
											<span>{candidate.location}</span>
										{/if}
									</div>
								</div>
								<div class="flex items-center gap-3 shrink-0 ml-4">
									<div class="text-right">
										<span class="font-bold {candidate.score >= 0.75 ? 'text-green-400' : candidate.score >= 0.5 ? 'text-yellow-400' : 'text-red-400'}">
											{(candidate.score * 100).toFixed(0)}%
										</span>
										{#if candidate.rating}
											<span class="text-xs block" style="color: {ratingColor(candidate.rating)}">{candidate.rating.toFixed(1)}</span>
										{/if}
									</div>
									<button
										onclick={() => handleAssign(reviewVideoId!, candidate.cagematch_event_id)}
										class="text-xs px-3 py-1.5 bg-titan-accent rounded hover:opacity-90"
									>
										Assign
									</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}

				<!-- Manual event search -->
				<div class="border-t border-titan-border pt-4">
					<p class="text-sm font-medium mb-2">Search events manually</p>
					<input
						type="text"
						bind:value={eventSearchQuery}
						oninput={handleEventSearch}
						placeholder="Search by event name..."
						class="w-full bg-titan-bg border border-titan-border rounded px-3 py-2 text-sm text-titan-text placeholder:text-titan-text-muted focus:outline-none focus:ring-1 focus:ring-titan-accent"
					/>
					{#if searchingEvents}
						<p class="text-xs text-titan-text-muted mt-2">Searching...</p>
					{/if}
					{#if eventSearchResults.length > 0}
						<div class="space-y-2 mt-3">
							{#each eventSearchResults as ev}
								<div class="bg-titan-bg border border-titan-border rounded-lg p-3 flex items-center justify-between">
									<div class="flex-1 min-w-0">
										<p class="text-sm font-medium">{ev.name}</p>
										<div class="flex gap-3 text-xs text-titan-text-muted mt-1">
											{#if ev.date}<span>{ev.date}</span>{/if}
											{#if ev.location}<span>{ev.location}</span>{/if}
										</div>
									</div>
									<button
										onclick={() => handleAssign(reviewVideoId!, ev.cagematch_event_id)}
										class="text-xs px-3 py-1.5 bg-titan-accent rounded hover:opacity-90 shrink-0 ml-3"
									>
										Assign
									</button>
								</div>
							{/each}
						</div>
					{:else if eventSearchQuery.length >= 2 && !searchingEvents}
						<p class="text-xs text-titan-text-muted mt-2">No events found in local database.</p>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}
