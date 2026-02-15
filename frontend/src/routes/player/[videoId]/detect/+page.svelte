<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import Hls from 'hls.js';
	import {
		getPlayerInfo,
		getChapters,
		createChapter,
		startAnalysis,
		getAnalysisStatus,
		getAnalysisResults,
		clearAnalysis,
	} from '$lib/api/client';
	import type { PlayerInfo, Chapter, Detection, AnalysisStatus, AnalysisResults } from '$lib/types';
	import PlayerControls from '$lib/components/player/PlayerControls.svelte';
	import DetectionTimeline from '$lib/components/player/DetectionTimeline.svelte';
	import DetectionList from '$lib/components/player/DetectionList.svelte';

	const videoId = Number(page.params.videoId);

	let playerInfo = $state<PlayerInfo | null>(null);
	let loading = $state(true);
	let error = $state('');
	let videoEl = $state<HTMLVideoElement>(null!);
	let playerContainer = $state<HTMLDivElement>(null!);
	let hls: Hls | null = null;
	let currentTime = $state(0);
	let duration = $state(0);
	let isPlaying = $state(false);
	let chapters = $state<Chapter[]>([]);

	// Analysis state
	let status = $state<AnalysisStatus>({ status: 'none' });
	let results = $state<AnalysisResults | null>(null);
	let pollInterval: ReturnType<typeof setInterval> | null = null;

	// Re-run dropdown
	let showRerunMenu = $state(false);

	let allDetections = $derived<Detection[]>(
		results
			? [...results.visual, ...results.audio].sort((a, b) => a.timestamp_ticks - b.timestamp_ticks)
			: []
	);

	let sortedChapters = $derived(
		[...chapters].sort((a, b) => a.start_ticks - b.start_ticks)
	);

	onMount(() => {
		(async () => {
			try {
				playerInfo = await getPlayerInfo(videoId);
				chapters = playerInfo.chapters;
			} catch (e) {
				error = 'Failed to load player info';
			} finally {
				loading = false;
			}
			await new Promise((r) => setTimeout(r, 0));
			if (playerInfo && videoEl) {
				initPlayer();
			}
			// Check for existing analysis results
			try {
				status = await getAnalysisStatus(videoId);
				if (status.status === 'completed') {
					results = await getAnalysisResults(videoId);
				} else if (status.status?.startsWith('running')) {
					startPolling();
				}
			} catch {
				// No existing analysis
			}
		})();
	});

	function initPlayer() {
		if (!playerInfo || !videoEl) return;
		const streamUrl = playerInfo.stream.url;
		if (playerInfo.stream.is_hls) {
			if (Hls.isSupported()) {
				hls = new Hls({ maxBufferLength: 30, maxMaxBufferLength: 60 });
				hls.loadSource(streamUrl);
				hls.attachMedia(videoEl);
			} else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
				videoEl.src = streamUrl;
			}
		} else {
			videoEl.src = streamUrl;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		const tag = (e.target as HTMLElement)?.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
		if (!videoEl) return;
		switch (e.key) {
			case ' ':
				e.preventDefault();
				videoEl.paused ? videoEl.play() : videoEl.pause();
				break;
			case 'ArrowLeft':
				videoEl.currentTime = Math.max(0, videoEl.currentTime - 10);
				break;
			case 'ArrowRight':
				videoEl.currentTime = Math.min(videoEl.duration || 0, videoEl.currentTime + 10);
				break;
		}
	}

	function seekTo(ticks: number) {
		if (videoEl) videoEl.currentTime = ticks / 10_000_000;
	}

	async function handleAcceptChapter(ticks: number, title: string) {
		try {
			await createChapter(videoId, { title, start_ticks: ticks });
			chapters = await getChapters(videoId);
		} catch (e) {
			console.error('Failed to create chapter:', e);
		}
	}

	function handleDetectionClick(det: Detection) {
		seekTo(det.timestamp_ticks);
	}

	async function handleRunAnalysis(phase: 'both' | 'visual' | 'audio' = 'both') {
		showRerunMenu = false;
		try {
			await startAnalysis(videoId, phase);
			status = { status: phase === 'audio' ? 'running_audio' : 'running_visual', message: `Starting ${phase} analysis...` };
			startPolling();
		} catch (e: any) {
			status = { status: 'failed', error: e.message || 'Failed to start analysis' };
		}
	}

	async function handleClear() {
		await clearAnalysis(videoId);
		status = { status: 'none' };
		results = null;
	}

	function startPolling() {
		if (pollInterval) return;
		pollInterval = setInterval(async () => {
			try {
				status = await getAnalysisStatus(videoId);
				if (status.status === 'completed') {
					stopPolling();
					results = await getAnalysisResults(videoId);
				} else if (status.status === 'failed' || status.status === 'none') {
					stopPolling();
				}
			} catch {
				stopPolling();
			}
		}, 2000);
	}

	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	function formatTime(ticks: number): string {
		const totalSeconds = Math.floor(ticks / 10_000_000);
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
		return `${m}:${String(s).padStart(2, '0')}`;
	}

	onDestroy(() => {
		hls?.destroy();
		stopPolling();
	});
</script>

<svelte:head>
	<title>Detection - {playerInfo?.video.title || 'Player'} - Titantron</title>
</svelte:head>

<svelte:window onkeydown={handleKeydown} />

{#if loading}
	<div class="flex items-center justify-center py-20">
		<p class="text-titan-text-muted">Loading...</p>
	</div>
{:else if error}
	<div class="flex items-center justify-center py-20">
		<p class="text-red-400">{error}</p>
	</div>
{:else if playerInfo}
	<div class="max-w-7xl mx-auto px-4 py-3 space-y-3">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-3">
				<a
					href="/player/{videoId}"
					class="text-sm text-titan-text-muted hover:text-titan-accent flex items-center gap-1"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
					Back to Player
				</a>
				<span class="text-titan-border">|</span>
				<h1 class="text-sm font-medium truncate">{playerInfo.video.title}</h1>
			</div>
			<div class="flex items-center gap-2">
				{#if status.status === 'completed'}
					<div class="relative">
						<button
							onclick={() => { showRerunMenu = !showRerunMenu; }}
							class="text-xs px-3 py-1.5 bg-titan-border rounded hover:bg-titan-surface-hover flex items-center gap-1"
						>
							Re-run
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
						</button>
						{#if showRerunMenu}
							<div class="absolute right-0 top-full mt-1 bg-titan-surface border border-titan-border rounded-lg shadow-lg z-50 py-1 min-w-[140px]">
								<button onclick={() => handleRunAnalysis('both')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Re-run All</button>
								<button onclick={() => handleRunAnalysis('visual')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Visual Only</button>
								<button onclick={() => handleRunAnalysis('audio')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Audio Only</button>
								<hr class="border-titan-border my-1" />
								<button onclick={handleClear} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover text-red-400">Clear Results</button>
							</div>
						{/if}
					</div>
				{:else if status.status === 'none'}
					<button
						onclick={() => handleRunAnalysis('both')}
						class="text-xs px-3 py-1.5 bg-titan-accent text-white rounded hover:opacity-90"
					>
						Run Analysis
					</button>
				{:else if status.status === 'failed'}
					<span class="text-xs text-red-400 truncate max-w-[300px]">{status.error || status.message}</span>
					<button
						onclick={() => handleRunAnalysis('both')}
						class="text-xs px-3 py-1.5 bg-titan-border rounded hover:bg-titan-surface-hover"
					>
						Retry
					</button>
				{/if}
			</div>
		</div>

		<!-- Video Player -->
		<div class="relative bg-black rounded-lg" bind:this={playerContainer} data-player-container>
			<div class="relative w-full" style="padding-bottom: 56.25%;">
				<video
					bind:this={videoEl}
					class="absolute inset-0 w-full h-full rounded-lg"
					ontimeupdate={() => { currentTime = videoEl.currentTime; }}
					ondurationchange={() => { duration = videoEl.duration; }}
					onplay={() => { isPlaying = true; }}
					onpause={() => { isPlaying = false; }}
				></video>
				<PlayerControls
					{videoEl}
					{currentTime}
					{duration}
					{isPlaying}
					chapters={sortedChapters}
					trickplay={playerInfo.trickplay}
					detections={allDetections}
				/>
			</div>
		</div>

		<!-- Analysis progress -->
		{#if status.status?.startsWith('running')}
			<div class="bg-titan-surface border border-titan-border rounded-lg p-3 flex items-center gap-3">
				<div class="animate-spin h-4 w-4 border-2 border-titan-accent border-t-transparent rounded-full shrink-0"></div>
				<span class="text-sm text-titan-text-muted flex-1">{status.message}</span>
				{#if status.progress && status.total_steps}
					<div class="w-48 bg-titan-border rounded-full h-1.5">
						<div
							class="bg-titan-accent h-1.5 rounded-full transition-all"
							style="width: {(status.progress / status.total_steps) * 100}%"
						></div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Timeline -->
		{#if status.status === 'completed' && results && playerInfo.trickplay}
			<DetectionTimeline
				trickplay={playerInfo.trickplay}
				durationTicks={playerInfo.video.duration_ticks}
				currentTimeTicks={Math.floor(currentTime * 10_000_000)}
				visualDetections={results.visual}
				audioDetections={results.audio}
				chapters={sortedChapters}
				onSeekTo={seekTo}
				onDetectionClick={handleDetectionClick}
			/>
		{/if}

		<!-- Detection list -->
		{#if status.status === 'completed' && results}
			<DetectionList
				detections={allDetections}
				onSeekTo={seekTo}
				onAcceptChapter={handleAcceptChapter}
			/>

			<!-- Summary footer -->
			<div class="flex items-center gap-4 text-xs text-titan-text-muted px-1">
				<span>{results.visual.length} visual detections</span>
				<span>{results.audio.length} audio detections</span>
				{#if results.audio_skip_reason}
					<span class="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">
						{#if results.audio_skip_reason === 'no_path_mapping'}
							Audio skipped (no path mapping)
						{:else if results.audio_skip_reason.startsWith('file_not_found:')}
							Audio skipped (file not found)
						{:else}
							Audio: {results.audio_skip_reason}
						{/if}
					</span>
				{/if}
				{#if results.completed_at}
					<span>Completed {new Date(results.completed_at).toLocaleString()}</span>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<!-- Click outside to close rerun menu -->
{#if showRerunMenu}
	<div
		class="fixed inset-0 z-40"
		onclick={() => { showRerunMenu = false; }}
		role="presentation"
	></div>
{/if}
