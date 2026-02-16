<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import Hls from 'hls.js';
	import {
		getPlayerInfo,
		getChapters,
		createChapter,
		deleteChapter,
		getBellSamples,
		createBellSample,
		updateBellSample,
		deleteBellSample,
		getBellSampleCount,
		reportPlaybackStart,
		reportPlaybackProgress,
		reportPlaybackStopped,
	} from '$lib/api/client';
	import type { PlayerInfo, Chapter, BellSample, WrestlingMatch } from '$lib/types';
	import PlayerControls from '$lib/components/player/PlayerControls.svelte';
	import DetectionFilmstrip from '$lib/components/player/DetectionFilmstrip.svelte';

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
	let progressInterval: ReturnType<typeof setInterval> | null = null;
	let markingMatch = $state<number | null>(null);
	let detections = $state<import('$lib/types').Detection[]>([]);
	let bellSamples = $state<BellSample[]>([]);
	let bellStartTicks = $state<number | null>(null);
	let bellTotalCount = $state<number | null>(null);

	let sortedChapters = $derived(
		[...chapters].sort((a, b) => a.start_ticks - b.start_ticks)
	);

	onMount(() => {
		(async () => {
			try {
				playerInfo = await getPlayerInfo(videoId);
				chapters = playerInfo.chapters;
				bellSamples = await getBellSamples(videoId);
				getBellSampleCount().then(r => { bellTotalCount = r.total; }).catch(() => {});
			} catch (e) {
				error = 'Failed to load player info';
			} finally {
				loading = false;
			}
			await new Promise((r) => setTimeout(r, 0));
			if (playerInfo && videoEl) {
				initPlayer();
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
				hls.on(Hls.Events.MANIFEST_PARSED, () => {
					videoEl.play().catch(() => {});
				});
				hls.on(Hls.Events.ERROR, (_event, data) => {
					if (data.fatal) {
						error = `Playback error: ${data.type}`;
					}
				});
			} else if (videoEl.canPlayType('application/vnd.apple.mpegurl')) {
				videoEl.src = streamUrl;
				videoEl.addEventListener('loadedmetadata', () => videoEl.play().catch(() => {}));
			} else {
				error = 'HLS playback not supported';
			}
		} else {
			videoEl.src = streamUrl;
			videoEl.addEventListener('loadedmetadata', () => videoEl.play().catch(() => {}));
			videoEl.addEventListener('error', () => {
				error = 'Failed to play video — format may not be supported by your browser';
			});
		}

		reportPlaybackStart(videoId, {
			position_ticks: 0,
			play_session_id: playerInfo.stream.play_session_id,
		}).catch(() => {});

		progressInterval = setInterval(() => {
			if (!playerInfo || !videoEl) return;
			reportPlaybackProgress(videoId, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				is_paused: videoEl.paused,
				play_session_id: playerInfo.stream.play_session_id,
			});
		}, 10_000);
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
				if (e.shiftKey) {
					seekToPrevChapter();
				} else {
					videoEl.currentTime = Math.max(0, videoEl.currentTime - 10);
				}
				break;
			case 'ArrowRight':
				if (e.shiftKey) {
					seekToNextChapter();
				} else {
					videoEl.currentTime = Math.min(videoEl.duration || 0, videoEl.currentTime + 10);
				}
				break;
			case 'f':
			case 'F':
				toggleFullscreen();
				break;
			case 'm':
			case 'M':
				videoEl.muted = !videoEl.muted;
				break;
		}
	}

	function seekToPrevChapter() {
		if (!videoEl || chapters.length === 0) return;
		const currentTicks = Math.floor(videoEl.currentTime * 10_000_000);
		const buffer = 20_000_000;
		for (let i = chapters.length - 1; i >= 0; i--) {
			if (chapters[i].start_ticks < currentTicks - buffer) {
				videoEl.currentTime = chapters[i].start_ticks / 10_000_000;
				return;
			}
		}
		videoEl.currentTime = 0;
	}

	function seekToNextChapter() {
		if (!videoEl || chapters.length === 0) return;
		const currentTicks = Math.floor(videoEl.currentTime * 10_000_000);
		for (const chapter of chapters) {
			if (chapter.start_ticks > currentTicks + 10_000_000) {
				videoEl.currentTime = chapter.start_ticks / 10_000_000;
				return;
			}
		}
	}

	function toggleFullscreen() {
		if (document.fullscreenElement) {
			document.exitFullscreen();
		} else {
			playerContainer?.requestFullscreen();
		}
	}

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

	async function markMatch(match: WrestlingMatch) {
		markingMatch = match.id;
		try {
			await createChapter(videoId, {
				title: matchTitle(match),
				start_ticks: Math.floor(currentTime * 10_000_000),
				match_id: match.id,
			});
			await reloadChapters();
		} catch (e) {
			console.error('Failed to create chapter:', e);
		} finally {
			markingMatch = null;
		}
	}

	async function handleDeleteChapter(chapterId: number) {
		try {
			await deleteChapter(videoId, chapterId);
			await reloadChapters();
		} catch (e) {
			console.error('Failed to delete chapter:', e);
		}
	}

	async function reloadChapters() {
		if (!playerInfo) return;
		chapters = await getChapters(playerInfo.video.id);
	}

	async function handleBellMark() {
		if (!videoEl) return;
		const nowTicks = Math.floor(videoEl.currentTime * 10_000_000);
		if (bellStartTicks === null) {
			bellStartTicks = nowTicks;
		} else {
			const start = bellStartTicks;
			const end = nowTicks;
			bellStartTicks = null;
			if (end <= start) return;
			try {
				await createBellSample(videoId, { start_ticks: start, end_ticks: end });
				await reloadBellSamples();
			} catch (e) {
				console.error('Failed to create bell sample:', e);
			}
		}
	}

	async function reloadBellSamples() {
		bellSamples = await getBellSamples(videoId);
		getBellSampleCount().then(r => { bellTotalCount = r.total; }).catch(() => {});
	}

	async function handleDeleteBellSample(sampleId: number) {
		try {
			await deleteBellSample(videoId, sampleId);
			await reloadBellSamples();
		} catch (e) {
			console.error('Failed to delete bell sample:', e);
		}
	}

	async function handleUpdateBellLabel(sampleId: number, label: string | null) {
		try {
			await updateBellSample(videoId, sampleId, { label });
			await reloadBellSamples();
		} catch (e) {
			console.error('Failed to update bell sample:', e);
		}
	}

	function handleBeforeUnload() {
		if (playerInfo && videoEl) {
			reportPlaybackStopped(videoId, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				play_session_id: playerInfo.stream.play_session_id,
			}).catch(() => {});
		}
	}

	onDestroy(() => {
		hls?.destroy();
		if (progressInterval) clearInterval(progressInterval);
		if (playerInfo && videoEl) {
			reportPlaybackStopped(videoId, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				play_session_id: playerInfo.stream.play_session_id,
			}).catch(() => {});
		}
	});
</script>

<svelte:head>
	<title>{playerInfo?.video.title || 'Player'} - Titantron</title>
</svelte:head>

<svelte:window onkeydown={handleKeydown} onbeforeunload={handleBeforeUnload} />

{#if loading}
	<div class="flex items-center justify-center py-20">
		<p class="text-titan-text-muted">Loading...</p>
	</div>
{:else if error}
	<div class="flex items-center justify-center py-20">
		<p class="text-red-400">{error}</p>
	</div>
{:else if playerInfo}
	<div class="max-w-6xl mx-auto px-4 py-4">
		<div class="flex gap-6">
			<!-- Left: Video player -->
			<div class="flex-1 min-w-0">
				<div class="relative bg-black rounded-lg" bind:this={playerContainer} data-player-container>
					<!-- 16:9 aspect ratio container -->
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
						{chapters}
						trickplay={playerInfo.trickplay}
						{detections}
					/>
					</div>
				</div>

				<!-- Video title + event link + bell sample controls -->
				<div class="mt-3 flex items-start justify-between gap-4">
					<div>
						<h1 class="text-lg font-semibold">{playerInfo.video.title}</h1>
						{#if playerInfo.event}
							<a href="/browse/event/{playerInfo.event.cagematch_event_id}" class="text-sm text-titan-text-muted hover:text-titan-accent">
								{playerInfo.event.name} &middot; {playerInfo.event.date}
							</a>
						{/if}
					</div>
					<div class="flex items-center gap-2 shrink-0">
						<button
							onclick={handleBellMark}
							class="text-xs px-3 py-1.5 rounded font-medium {bellStartTicks !== null
								? 'bg-red-500 text-white animate-pulse'
								: 'bg-titan-surface text-titan-text-muted hover:text-white'}"
						>
							{#if bellStartTicks !== null}
								Stop Bell ({formatTicks(Math.floor(currentTime * 10_000_000))})
							{:else}
								Mark Bell
							{/if}
						</button>
						{#if bellStartTicks !== null}
							<button
								onclick={() => { bellStartTicks = null; }}
								class="text-xs px-2 py-1.5 rounded text-titan-text-muted hover:text-white hover:bg-titan-surface"
							>
								Cancel
							</button>
						{/if}
						{#if bellTotalCount !== null}
							<span class="text-xs text-titan-text-muted">{bellTotalCount} bells</span>
						{/if}
					</div>
				</div>

				<!-- Detection Filmstrip -->
				{#if playerInfo.trickplay && playerInfo.video.duration_ticks}
					<div class="mt-3">
						<DetectionFilmstrip
							{videoId}
							trickplay={playerInfo.trickplay}
							durationTicks={playerInfo.video.duration_ticks}
							currentTimeTicks={Math.floor(currentTime * 10_000_000)}
							onSeekTo={(ticks) => { videoEl.currentTime = ticks / 10_000_000; }}
							onDetectionsReady={(d) => { detections = d; }}
						/>
					</div>
				{/if}

				<!-- Chapters list (below video) -->
				{#if sortedChapters.length > 0}
					<div class="mt-4">
						<h3 class="text-sm font-medium text-titan-text-muted mb-2">Chapters ({sortedChapters.length})</h3>
						<div class="space-y-1">
							{#each sortedChapters as chapter}
								<div class="flex items-center gap-2 bg-titan-surface rounded px-3 py-2 group">
									<button
										onclick={() => { videoEl.currentTime = chapter.start_ticks / 10_000_000; }}
										class="text-xs font-mono text-titan-accent hover:underline shrink-0"
									>
										{formatTicks(chapter.start_ticks)}
									</button>
									<span class="text-sm truncate flex-1 min-w-0">{chapter.title}</span>
									<button
										onclick={() => handleDeleteChapter(chapter.id)}
										class="text-xs text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 shrink-0"
										title="Delete chapter"
									>
										&times;
									</button>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Bell Samples list -->
				{#if bellSamples.length > 0}
					<div class="mt-4">
						<h3 class="text-sm font-medium text-titan-text-muted mb-2">Bell Samples ({bellSamples.length})</h3>
						<div class="space-y-1">
							{#each bellSamples as sample}
								<div class="flex items-center gap-2 bg-titan-surface rounded px-3 py-2 group">
									<button
										onclick={() => { videoEl.currentTime = sample.start_ticks / 10_000_000; }}
										class="text-xs font-mono text-titan-accent hover:underline shrink-0"
									>
										{formatTicks(sample.start_ticks)}
									</button>
									<span class="text-xs text-titan-text-muted">-</span>
									<button
										onclick={() => { videoEl.currentTime = sample.end_ticks / 10_000_000; }}
										class="text-xs font-mono text-titan-accent hover:underline shrink-0"
									>
										{formatTicks(sample.end_ticks)}
									</button>
									<span class="text-xs text-titan-text-muted shrink-0">
										{((sample.end_ticks - sample.start_ticks) / 10_000_000).toFixed(1)}s
									</span>
									<select
										value={sample.label ?? ''}
										onchange={(e) => {
											const val = (e.target as HTMLSelectElement).value || null;
											handleUpdateBellLabel(sample.id, val);
										}}
										class="text-xs bg-titan-bg border border-titan-surface rounded px-1 py-0.5 text-titan-text-muted flex-1 min-w-0"
									>
										<option value="">(none)</option>
										<option value="match_start">match_start</option>
										<option value="match_end">match_end</option>
										<option value="timekeeper">timekeeper</option>
									</select>
									<button
										onclick={() => handleDeleteBellSample(sample.id)}
										class="text-xs text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 shrink-0"
										title="Delete sample"
									>
										&times;
									</button>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>

			<!-- Right: Match card sidebar -->
			{#if playerInfo.event}
				<div class="w-[320px] shrink-0">
					<h2 class="text-sm font-medium text-titan-text-muted mb-3">Match Card</h2>
					<div class="space-y-2">
						{#each playerInfo.event.matches as match}
							{@const linkedChapter = sortedChapters.find(c => c.match_id === match.id)}
							<div class="bg-titan-surface rounded-lg p-3">
								{#if match.title_name || match.match_type}
									<p class="text-xs text-titan-text-muted mb-1">
										{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
										{#if match.title_name && match.match_type}{' '}{/if}
										{#if match.match_type}{match.match_type}{/if}
									</p>
								{/if}
								<p class="text-sm mb-2">{matchTitle(match)}</p>
								<div class="flex items-center gap-2">
									{#if linkedChapter}
										<button
											onclick={() => { videoEl.currentTime = linkedChapter.start_ticks / 10_000_000; }}
											class="text-xs px-2.5 py-1 bg-titan-accent/20 text-titan-accent rounded hover:bg-titan-accent/30"
										>
											{formatTicks(linkedChapter.start_ticks)}
										</button>
										<button
											onclick={() => handleDeleteChapter(linkedChapter.id)}
											class="text-xs px-2 py-1 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded"
											title="Remove chapter"
										>
											&times;
										</button>
									{:else}
										<button
											onclick={() => markMatch(match)}
											disabled={markingMatch === match.id}
											class="text-xs px-2.5 py-1 bg-titan-accent rounded hover:opacity-90 disabled:opacity-50 font-medium"
										>
											{markingMatch === match.id ? 'Marking...' : 'Mark'}
										</button>
										<span class="text-xs text-titan-text-muted">at {formatTicks(Math.floor(currentTime * 10_000_000))}</span>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}
