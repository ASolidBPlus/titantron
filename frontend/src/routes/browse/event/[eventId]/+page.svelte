<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { page } from '$app/state';
	import Hls from 'hls.js';
	import {
		getEventDetail,
		scrapeEventMatches,
		getEventComments,
		getPlayerInfo,
		getChapters,
		createChapter,
		deleteChapter,
		reportPlaybackStart,
		reportPlaybackProgress,
		reportPlaybackStopped,
	} from '$lib/api/client';
	import type { EventDetail, EventComment, WrestlingMatch, MatchParticipant, PlayerInfo, Chapter, Detection } from '$lib/types';
	import PlayerControls from '$lib/components/player/PlayerControls.svelte';
	import DetectionFilmstrip from '$lib/components/player/DetectionFilmstrip.svelte';
	import { ratingColor } from '$lib/utils/rating';

	let loading = $state(true);
	let event = $state<EventDetail | null>(null);
	let error = $state('');
	let scraping = $state(false);

	const eventId = Number(page.params.eventId);

	// Player state
	let playerInfo = $state<PlayerInfo | null>(null);
	let activeVideoId = $state<number | null>(null);
	let videoEl = $state<HTMLVideoElement>(null!);
	let playerContainer = $state<HTMLDivElement>(null!);
	let hls: Hls | null = null;
	let currentTime = $state(0);
	let duration = $state(0);
	let isPlaying = $state(false);
	let chapters = $state<Chapter[]>([]);
	let progressInterval: ReturnType<typeof setInterval> | null = null;
	let markingMatch = $state<number | null>(null);
	let detections = $state<Detection[]>([]);
	let isFullscreen = $state(false);
	let showSidebar = $state(true);
	let sidebarTab = $state<'matches' | 'reviews'>('matches');
	let comments = $state<EventComment[]>([]);
	let commentsLoading = $state(false);
	let commentsLoaded = $state(false);

	let sortedChapters = $derived(
		[...chapters].sort((a, b) => a.start_ticks - b.start_ticks)
	);

	function onFullscreenChange() {
		isFullscreen = !!document.fullscreenElement;
	}

	onMount(async () => {
		document.addEventListener('fullscreenchange', onFullscreenChange);
		await loadEvent();
	});

	async function loadEvent() {
		try {
			event = await getEventDetail(eventId);
			if (event && event.matches.length === 0) {
				scraping = true;
				try {
					await scrapeEventMatches(eventId);
					event = await getEventDetail(eventId);
				} catch {
					// Non-fatal — page still shows, just without matches
				} finally {
					scraping = false;
				}
			}
		} catch (e) {
			error = 'Failed to load event';
		} finally {
			loading = false;
		}
	}

	async function handleScrapeMatches() {
		if (!event) return;
		scraping = true;
		try {
			await scrapeEventMatches(eventId);
			event = await getEventDetail(eventId);
		} catch (e) {
			error = 'Failed to scrape matches';
		} finally {
			scraping = false;
		}
	}

	async function playVideo(videoId: number) {
		// Clean up previous player
		destroyPlayer();

		activeVideoId = videoId;
		try {
			playerInfo = await getPlayerInfo(videoId);
			chapters = playerInfo.chapters;
		} catch (e) {
			error = 'Failed to load video';
			activeVideoId = null;
			return;
		}

		// Wait for DOM to render the video element
		await new Promise((r) => setTimeout(r, 0));
		if (playerInfo && videoEl) {
			initPlayer();
		}
	}

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

		reportPlaybackStart(activeVideoId!, {
			position_ticks: 0,
			play_session_id: playerInfo.stream.play_session_id,
		}).catch(() => {});

		progressInterval = setInterval(() => {
			if (!playerInfo || !videoEl) return;
			reportPlaybackProgress(activeVideoId!, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				is_paused: videoEl.paused,
				play_session_id: playerInfo.stream.play_session_id,
			});
		}, 10_000);
	}

	function stopVideo() {
		if (playerInfo && videoEl && activeVideoId) {
			reportPlaybackStopped(activeVideoId, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				play_session_id: playerInfo.stream.play_session_id,
			}).catch(() => {});
		}
		destroyPlayer();
		activeVideoId = null;
		playerInfo = null;
		chapters = [];
		detections = [];
	}

	function destroyPlayer() {
		hls?.destroy();
		hls = null;
		if (progressInterval) {
			clearInterval(progressInterval);
			progressInterval = null;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!activeVideoId || !videoEl) return;
		const tag = (e.target as HTMLElement)?.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

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
		for (let i = sortedChapters.length - 1; i >= 0; i--) {
			if (sortedChapters[i].start_ticks < currentTicks - buffer) {
				videoEl.currentTime = sortedChapters[i].start_ticks / 10_000_000;
				return;
			}
		}
		videoEl.currentTime = 0;
	}

	function seekToNextChapter() {
		if (!videoEl || chapters.length === 0) return;
		const currentTicks = Math.floor(videoEl.currentTime * 10_000_000);
		for (const chapter of sortedChapters) {
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

	function formatTicks(ticks: number): string {
		const totalSeconds = Math.floor(ticks / 10_000_000);
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function matchDisplayTitle(match: WrestlingMatch): string {
		const sideMap = new Map<number, string[]>();
		for (const p of match.participants) {
			if (p.role === 'manager') continue;
			const side = p.side ?? 1;
			if (!sideMap.has(side)) sideMap.set(side, []);
			sideMap.get(side)!.push(p.name);
		}
		return [...sideMap.values()].map(names => names.join(' & ')).join(' vs. ');
	}

	async function markMatch(match: WrestlingMatch) {
		if (!activeVideoId) return;
		markingMatch = match.id;
		try {
			await createChapter(activeVideoId, {
				title: matchDisplayTitle(match),
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
		if (!activeVideoId) return;
		try {
			await deleteChapter(activeVideoId, chapterId);
			await reloadChapters();
		} catch (e) {
			console.error('Failed to delete chapter:', e);
		}
	}

	async function reloadChapters() {
		if (!playerInfo) return;
		chapters = await getChapters(playerInfo.video.id);
	}

	async function handleAcceptChapter(ticks: number, title: string) {
		if (!activeVideoId) return;
		try {
			await createChapter(activeVideoId, { title, start_ticks: ticks });
			await reloadChapters();
		} catch (e) {
			console.error('Failed to create chapter:', e);
		}
	}

	async function loadComments() {
		if (commentsLoaded || commentsLoading) return;
		commentsLoading = true;
		try {
			comments = await getEventComments(eventId);
			commentsLoaded = true;
		} catch (e) {
			console.error('Failed to load comments:', e);
		} finally {
			commentsLoading = false;
		}
	}

	function switchToReviews() {
		sidebarTab = 'reviews';
		loadComments();
	}

	function translateUrl(text: string): string {
		return `https://translate.google.com/?sl=auto&tl=en&text=${encodeURIComponent(text)}&op=translate`;
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr + 'T00:00:00').toLocaleDateString('en-US', {
			weekday: 'long',
			year: 'numeric',
			month: 'long',
			day: 'numeric',
		});
	}

	interface SideGroup {
		teamName: string | null;
		competitors: MatchParticipant[];
		managers: MatchParticipant[];
	}

	function getSides(match: WrestlingMatch): SideGroup[] {
		const sideMap = new Map<number, MatchParticipant[]>();
		for (const p of match.participants) {
			const side = p.side ?? 1;
			if (!sideMap.has(side)) sideMap.set(side, []);
			sideMap.get(side)!.push(p);
		}
		return [...sideMap.entries()]
			.sort((a, b) => a[0] - b[0])
			.map(([, ps]) => ({
				teamName: ps.find((p) => p.role !== 'manager')?.team_name ?? null,
				competitors: ps.filter((p) => p.role !== 'manager'),
				managers: ps.filter((p) => p.role === 'manager'),
			}));
	}

	function handleBeforeUnload() {
		if (playerInfo && videoEl && activeVideoId) {
			reportPlaybackStopped(activeVideoId, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				play_session_id: playerInfo.stream.play_session_id,
			}).catch(() => {});
		}
	}

	onDestroy(() => {
		if (browser) document.removeEventListener('fullscreenchange', onFullscreenChange);
		if (playerInfo && videoEl && activeVideoId) {
			reportPlaybackStopped(activeVideoId, {
				position_ticks: Math.floor(videoEl.currentTime * 10_000_000),
				play_session_id: playerInfo.stream.play_session_id,
			}).catch(() => {});
		}
		destroyPlayer();
	});
</script>

<svelte:head>
	<title>{event?.name || 'Event'} - Titantron</title>
</svelte:head>

<svelte:window onkeydown={handleKeydown} onbeforeunload={handleBeforeUnload} />

<div class="{activeVideoId && playerInfo ? 'max-w-7xl' : 'max-w-4xl'} mx-auto p-6 transition-all">
	{#if loading}
		<p class="text-titan-text-muted">Loading...</p>
	{:else if error && !event}
		<p class="text-red-400">{error}</p>
	{:else if event}
		<div class="mb-6">
			{#if event.promotion}
				<a href="/browse/{event.promotion.cagematch_id}" class="text-sm text-titan-text-muted hover:text-titan-text">
					&larr; {event.promotion.name}
				</a>
			{/if}
		</div>

		<!-- Video Player + Sidebar (shown when playing) -->
		{#if activeVideoId && playerInfo}
			<div class="flex gap-6 mb-6">
				<!-- Left: Video player -->
				<div class="flex-1 min-w-0">
					<div class="relative bg-black rounded-lg" bind:this={playerContainer} data-player-container>
						<div class="relative w-full {isFullscreen ? 'h-screen' : ''}" style={isFullscreen ? '' : 'padding-bottom: 56.25%'}>
							<video
								bind:this={videoEl}
								class="absolute inset-0 w-full h-full object-contain rounded-lg"
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

					<!-- Now playing bar -->
					<div class="flex items-center justify-between mt-2">
						<span class="text-sm text-titan-text-muted">Now playing: {playerInfo.video.title}</span>
						<button
							onclick={stopVideo}
							class="text-xs px-2 py-1 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded"
						>
							Stop
						</button>
					</div>

					<!-- Detection Filmstrip -->
					{#if playerInfo.trickplay && playerInfo.video.duration_ticks}
						<div class="mt-3">
							<DetectionFilmstrip
								videoId={activeVideoId}
								trickplay={playerInfo.trickplay}
								durationTicks={playerInfo.video.duration_ticks}
								currentTimeTicks={Math.floor(currentTime * 10_000_000)}
								onSeekTo={(ticks) => { videoEl.currentTime = ticks / 10_000_000; }}
								onAcceptChapter={handleAcceptChapter}
								onDetectionsReady={(d) => { detections = d; }}
							/>
						</div>
					{/if}

					<!-- Chapters (below player) -->
					{#if sortedChapters.length > 0}
						<div class="mt-3">
							<h3 class="text-xs font-medium text-titan-text-muted mb-1.5">Chapters</h3>
							<div class="flex flex-wrap gap-1.5">
								{#each sortedChapters as chapter}
									<button
										onclick={() => { videoEl.currentTime = chapter.start_ticks / 10_000_000; }}
										class="text-xs px-2.5 py-1 bg-titan-surface border border-titan-border rounded hover:border-titan-accent group flex items-center gap-1.5"
									>
										<span class="text-titan-accent">&#9654;</span>
										<span class="font-mono text-titan-accent">{formatTicks(chapter.start_ticks)}</span>
										<span class="truncate max-w-[150px]">{chapter.title}</span>
										<span
											role="button"
											tabindex={0}
											class="text-red-400 hover:text-red-300 opacity-0 group-hover:opacity-100 ml-0.5"
											onclick={(e: MouseEvent) => { e.stopPropagation(); handleDeleteChapter(chapter.id); }}
											onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter') { e.stopPropagation(); handleDeleteChapter(chapter.id); } }}
										>&times;</span>
									</button>
								{/each}
							</div>
						</div>
					{/if}

					<!-- Event info (in the space below player) -->
					{#if true}
					{@const sidebarPoster = event.videos.find((v) => v.poster_url)?.poster_url}
					<div class="bg-titan-surface border border-titan-border rounded-lg p-4 mt-4">
						<div class="flex gap-4">
							{#if sidebarPoster}
								<img
									src={sidebarPoster}
									alt={event.name}
									class="w-24 h-auto rounded-lg object-cover shrink-0"
								/>
							{/if}
							<div class="flex-1 min-w-0">
								<h1 class="text-lg font-bold mb-1 break-words">{event.name}</h1>
								<div class="flex flex-wrap gap-3 text-sm text-titan-text-muted">
									<span>{formatDate(event.date)}</span>
									{#if event.location}
										<span>{event.location}</span>
									{/if}
									{#if event.arena}
										<span>{event.arena}</span>
									{/if}
								</div>
								{#if event.rating}
									<div class="mt-2">
										<span class="text-lg font-bold" style="color: {ratingColor(event.rating)}">{event.rating.toFixed(1)}</span>
										{#if event.votes}
											<span class="text-titan-text-muted text-sm ml-1">({event.votes} votes)</span>
										{/if}
									</div>
								{/if}
							</div>
						</div>
					</div>
					{/if}
				</div>

				<!-- Right: Sidebar (Match Card / Reviews) -->
				<div class="shrink-0 flex">
					<!-- Sidebar toggle -->
					<button
						onclick={() => { showSidebar = !showSidebar; }}
						class="self-start mt-1 px-1 py-2 bg-titan-surface border border-titan-border rounded-l-lg text-titan-text-muted hover:text-titan-text -mr-px z-10"
						title={showSidebar ? 'Hide sidebar' : 'Show sidebar'}
					>
						<svg class="w-4 h-4 transition-transform {showSidebar ? '' : 'rotate-180'}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
						</svg>
					</button>

					{#if showSidebar}
					<div class="w-[340px]">
						<!-- Tab header -->
						<div class="flex items-center gap-1 mb-2">
							<button
								onclick={() => { sidebarTab = 'matches'; }}
								class="text-sm font-medium px-2 py-1 rounded {sidebarTab === 'matches' ? 'text-titan-text bg-titan-surface' : 'text-titan-text-muted hover:text-titan-text'}"
							>
								Matches
							</button>
							<button
								onclick={switchToReviews}
								class="text-sm font-medium px-2 py-1 rounded {sidebarTab === 'reviews' ? 'text-titan-text bg-titan-surface' : 'text-titan-text-muted hover:text-titan-text'}"
							>
								Reviews{#if commentsLoaded} ({comments.length}){/if}
							</button>
						</div>

						{#if sidebarTab === 'matches'}
						<!-- Match card list -->
						<div class="space-y-2 overflow-y-auto max-h-[70vh] pr-1">
							{#each event.matches as match}
								{@const sides = getSides(match)}
								{@const linkedChapter = sortedChapters.find(c => c.match_id === match.id)}
								<div class="bg-titan-surface border border-titan-border rounded-lg p-3">
									{#if match.title_name || match.match_type}
										<p class="text-xs mb-1">
											{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
											{#if match.title_name && match.match_type}{' '}{/if}
											{#if match.match_type}<span class="text-titan-text-muted">{match.match_type}</span>{/if}
										</p>
									{/if}
									<div class="text-sm break-words">
										{#each sides as side, sideIndex}
											{#if side.teamName}<span class="text-titan-text-muted text-xs">{side.teamName} (</span>{/if}{#each side.competitors as p, i}{#if p.cagematch_wrestler_id}<a href="/wrestler/{p.cagematch_wrestler_id}" class="{p.is_winner ? 'text-titan-gold' : ''} hover:underline">{p.name}</a>{:else}<span class="{p.is_winner ? 'text-titan-gold' : ''} italic">{p.name}</span>{/if}{#if i < side.competitors.length - 1}<span class="text-titan-text-muted">{' & '}</span>{/if}{/each}{#if side.teamName}<span class="text-titan-text-muted text-xs">)</span>{/if}{#if side.managers.length > 0}<span class="text-titan-text-muted text-xs">{' '}(w/{' '}{#each side.managers as mgr, i}{#if mgr.cagematch_wrestler_id}<a href="/wrestler/{mgr.cagematch_wrestler_id}" class="hover:underline">{mgr.name}</a>{:else}{mgr.name}{/if}{#if i < side.managers.length - 1}{', '}{/if}{/each})</span>{/if}
											{#if sideIndex < sides.length - 1}
												<span class="text-titan-accent font-bold mx-1">vs.</span>
											{/if}
										{/each}
									</div>
									{#if match.rating}
										<div class="mt-1 flex items-center gap-2 text-xs text-titan-text-muted">
											<span class="font-bold" style="color: {ratingColor(match.rating)}">{match.rating.toFixed(2)}</span>
											{#if match.duration}<span>{match.duration}</span>{/if}
										</div>
									{/if}
									<div class="mt-2 pt-2 border-t border-titan-border/50 flex items-center gap-2">
										{#if linkedChapter}
											<button
												onclick={() => { videoEl.currentTime = linkedChapter.start_ticks / 10_000_000; }}
												class="text-xs px-2.5 py-1 bg-titan-accent/20 text-titan-accent rounded hover:bg-titan-accent/30 font-mono flex items-center gap-1"
											>
												&#9654; {formatTicks(linkedChapter.start_ticks)}
											</button>
											<button
												onclick={() => handleDeleteChapter(linkedChapter.id)}
												class="text-xs px-2 py-1 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded"
											>
												Remove
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
						{:else}
						<!-- Reviews tab -->
						<div class="overflow-y-auto max-h-[70vh] pr-1">
							{#if commentsLoading}
								<p class="text-sm text-titan-text-muted py-4 text-center">Loading reviews...</p>
							{:else if comments.length === 0}
								<p class="text-sm text-titan-text-muted py-4 text-center">No reviews found.</p>
							{:else}
								<div class="space-y-2">
									{#each comments as comment}
										<div class="bg-titan-surface border border-titan-border rounded-lg p-3">
											<div class="flex items-center justify-between mb-1">
												<span class="text-sm font-medium">{comment.username}</span>
												<div class="flex items-center gap-2">
													{#if comment.rating}
														<span class="font-bold text-sm" style="color: {ratingColor(comment.rating)}">{comment.rating.toFixed(1)}</span>
													{/if}
													{#if comment.date}
														<span class="text-xs text-titan-text-muted">{comment.date}</span>
													{/if}
												</div>
											</div>
											{#if comment.text}
												<p class="text-sm text-titan-text-muted leading-relaxed">{comment.text}</p>
												<a
													href={translateUrl(comment.text)}
													target="_blank"
													rel="noopener noreferrer"
													class="text-xs text-titan-text-muted hover:text-titan-accent mt-1 inline-block"
												>Translate</a>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>
						{/if}
					</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Event Header (hidden when playing — shown in player left column instead) -->
		{@const posterUrl = event.videos.find((v) => v.poster_url)?.poster_url}
		<div class="bg-titan-surface border border-titan-border rounded-lg p-6 mb-6" class:hidden={activeVideoId && playerInfo}>
			<div class="flex gap-6">
				{#if posterUrl}
					<img
						src={posterUrl}
						alt={event.name}
						class="w-32 h-auto rounded-lg object-cover shrink-0"
					/>
				{/if}
				<div class="flex-1 min-w-0">
					<h1 class="text-2xl font-bold mb-2 break-words">{event.name}</h1>
					<div class="flex flex-wrap gap-4 text-sm text-titan-text-muted">
						<span>{formatDate(event.date)}</span>
						{#if event.location}
							<span>{event.location}</span>
						{/if}
						{#if event.arena}
							<span>{event.arena}</span>
						{/if}
					</div>
					{#if event.rating}
						<div class="mt-3">
							<span class="text-xl font-bold" style="color: {ratingColor(event.rating)}">{event.rating.toFixed(1)}</span>
							{#if event.votes}
								<span class="text-titan-text-muted text-sm ml-1">({event.votes} votes)</span>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Linked Videos -->
		{#if event.videos.length > 0}
			<div class="mb-6">
				<h2 class="text-lg font-semibold mb-3">Linked Videos</h2>
				{#each event.videos as video}
					<div class="bg-titan-surface border border-titan-border rounded-lg p-4 flex items-center justify-between mb-2">
						<span class="truncate min-w-0">{video.title}</span>
						<div class="flex items-center gap-2 shrink-0 ml-4">
							{#if activeVideoId === video.id}
								<span class="text-xs px-3 py-1 bg-titan-accent/20 text-titan-accent rounded font-medium">Playing</span>
							{:else}
								<button
									onclick={() => playVideo(video.id)}
									class="text-sm px-3 py-1 bg-titan-accent rounded hover:opacity-90 font-medium"
								>
									Play
								</button>
							{/if}
							<span class="text-xs px-2 py-1 rounded {video.match_status === 'confirmed' ? 'bg-green-800/50 text-green-300' : video.match_status === 'auto_matched' ? 'bg-blue-800/50 text-blue-300' : 'bg-yellow-800/50 text-yellow-300'}">
								{video.match_status}
							</span>
							{#if video.match_confidence}
								<span class="text-xs text-titan-text-muted">{(video.match_confidence * 100).toFixed(0)}%</span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Match Card + Reviews (shown below when no video playing) -->
		<div class="mb-6" class:hidden={activeVideoId && playerInfo}>
			<div class="flex items-center justify-between mb-3">
				<div class="flex items-center gap-4">
					<h2 class="text-lg font-semibold">Match Card</h2>
					<button
						onclick={() => { loadComments(); }}
						class="text-sm text-titan-text-muted hover:text-titan-text"
					>
						Reviews{#if commentsLoaded} ({comments.length}){/if}
					</button>
				</div>
				<button
					onclick={handleScrapeMatches}
					disabled={scraping}
					class="text-sm px-3 py-1 bg-titan-accent rounded hover:opacity-90 disabled:opacity-50"
				>
					{scraping ? 'Scraping...' : event.matches.length > 0 ? 'Re-scrape' : 'Scrape from Cagematch'}
				</button>
			</div>

			{#if event.matches.length === 0}
				<div class="bg-titan-surface border border-titan-border rounded-lg p-6 text-center">
					<p class="text-titan-text-muted">No match card loaded. Click "Scrape from Cagematch" to fetch it.</p>
				</div>
			{:else}
				<div class="space-y-3">
					{#each event.matches as match}
						{@const sides = getSides(match)}
						{@const linkedChapter = sortedChapters.find(c => c.match_id === match.id)}
						<div class="bg-titan-surface border border-titan-border rounded-lg p-4 overflow-hidden">
							<div class="flex items-start justify-between gap-4">
								<div class="flex-1 min-w-0">
									{#if match.title_name || match.match_type}
										<p class="text-xs mb-1">
											{#if match.title_name}<span class="text-titan-gold">{match.title_name}</span>{/if}
											{#if match.title_name && match.match_type}{' '}{/if}
											{#if match.match_type}<span class="text-titan-text-muted">{match.match_type}</span>{/if}
										</p>
									{/if}
									<div class="font-medium break-words">
										{#each sides as side, sideIndex}
											{#if side.teamName}<span class="text-titan-text-muted text-sm">{side.teamName} (</span>{/if}{#each side.competitors as p, i}{#if p.cagematch_wrestler_id}<a href="/wrestler/{p.cagematch_wrestler_id}" class="{p.is_winner ? 'text-titan-gold' : ''} hover:underline">{p.name}</a>{:else}<span class="{p.is_winner ? 'text-titan-gold' : ''} italic">{p.name}</span>{/if}{#if i < side.competitors.length - 1}<span class="text-titan-text-muted">{' & '}</span>{/if}{/each}{#if side.teamName}<span class="text-titan-text-muted text-sm">)</span>{/if}{#if side.managers.length > 0}<span class="text-titan-text-muted text-sm">{' '}(w/{' '}{#each side.managers as mgr, i}{#if mgr.cagematch_wrestler_id}<a href="/wrestler/{mgr.cagematch_wrestler_id}" class="hover:underline">{mgr.name}</a>{:else}{mgr.name}{/if}{#if i < side.managers.length - 1}{', '}{/if}{/each})</span>{/if}
											{#if sideIndex < sides.length - 1}
												<span class="text-titan-accent font-bold mx-1">vs.</span>
											{/if}
										{/each}
									</div>
								</div>
								<div class="text-right shrink-0 flex flex-col items-end gap-1">
									{#if match.rating}
										<span class="font-bold" style="color: {ratingColor(match.rating)}">{match.rating.toFixed(2)}</span>
										{#if match.votes}
											<span class="text-xs text-titan-text-muted">{match.votes} votes</span>
										{/if}
									{/if}
									{#if match.duration}
										<span class="text-xs text-titan-text-muted">{match.duration}</span>
									{/if}
								</div>
							</div>

							<!-- Mark / Chapter controls (only when video is playing) -->
							{#if activeVideoId}
								<div class="mt-2 pt-2 border-t border-titan-border/50 flex items-center gap-2">
									{#if linkedChapter}
										<button
											onclick={() => { videoEl.currentTime = linkedChapter.start_ticks / 10_000_000; }}
											class="text-xs px-2.5 py-1 bg-titan-accent/20 text-titan-accent rounded hover:bg-titan-accent/30 font-mono flex items-center gap-1"
										>
											&#9654; {formatTicks(linkedChapter.start_ticks)}
										</button>
										<button
											onclick={() => handleDeleteChapter(linkedChapter.id)}
											class="text-xs px-2 py-1 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded"
										>
											Remove
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
							{/if}
						</div>
					{/each}
				</div>
			{/if}

			<!-- Reviews section (below match card, non-playing view) -->
			{#if commentsLoaded}
				<div class="mt-6">
					<h2 class="text-lg font-semibold mb-3">Reviews ({comments.length})</h2>
					{#if comments.length === 0}
						<p class="text-titan-text-muted">No reviews found on Cagematch.</p>
					{:else}
						<div class="space-y-3">
							{#each comments as comment}
								<div class="bg-titan-surface border border-titan-border rounded-lg p-4">
									<div class="flex items-center justify-between mb-2">
										<span class="font-medium">{comment.username}</span>
										<div class="flex items-center gap-3">
											{#if comment.rating}
												<span class="font-bold" style="color: {ratingColor(comment.rating)}">{comment.rating.toFixed(1)}</span>
											{/if}
											{#if comment.date}
												<span class="text-sm text-titan-text-muted">{comment.date}</span>
											{/if}
										</div>
									</div>
									{#if comment.text}
										<p class="text-titan-text-muted leading-relaxed">{comment.text}</p>
										<a
											href={translateUrl(comment.text)}
											target="_blank"
											rel="noopener noreferrer"
											class="text-xs text-titan-text-muted hover:text-titan-accent mt-1 inline-block"
										>Translate</a>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{:else if commentsLoading}
				<div class="mt-6">
					<p class="text-titan-text-muted">Loading reviews...</p>
				</div>
			{/if}
		</div>
	{/if}
</div>
