<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { Chapter, TrickplayInfo, Detection } from '$lib/types';

	interface Props {
		videoEl: HTMLVideoElement;
		currentTime: number;
		duration: number;
		isPlaying: boolean;
		chapters: Chapter[];
		trickplay: TrickplayInfo | null;
		streamInfo: { api_key: string; server_url: string };
		detections?: Detection[];
	}

	let {
		videoEl,
		currentTime,
		duration,
		isPlaying,
		chapters,
		trickplay,
		streamInfo,
		detections = [],
	}: Props = $props();

	let showControls = $state(true);
	let hideTimer: ReturnType<typeof setTimeout> | null = null;
	let volume = $state(1);
	let isMuted = $state(false);
	let seekBarEl: HTMLDivElement;
	let hoverPosition = $state<number | null>(null);
	let isFullscreen = $state(false);
	let clickTimer: ReturnType<typeof setTimeout> | null = null;
	let hoveredChapterIdx = $state<number | null>(null);

	const chapterColors = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

	function formatTime(seconds: number): string {
		if (!isFinite(seconds)) return '0:00';
		const h = Math.floor(seconds / 3600);
		const m = Math.floor((seconds % 3600) / 60);
		const s = Math.floor(seconds % 60);
		if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function getTrickplayStyle(hoverRatio: number): { url: string; bgPosition: string; width: number; height: number; sheetWidth: number; sheetHeight: number } | null {
		if (!trickplay || !duration) return null;
		// Jellyfin interval is in milliseconds
		const positionMs = Math.floor(hoverRatio * duration * 1000);
		const thumbIndex = Math.floor(positionMs / trickplay.interval);
		const tilesPerSheet = trickplay.tile_width * trickplay.tile_height;
		const sheetIndex = Math.floor(thumbIndex / tilesPerSheet);
		const tileOnSheet = thumbIndex % tilesPerSheet;
		const col = tileOnSheet % trickplay.tile_width;
		const row = Math.floor(tileOnSheet / trickplay.tile_width);
		// width/height from Jellyfin are individual thumbnail dimensions
		const thumbWidth = trickplay.width;
		const thumbHeight = trickplay.height;
		const sheetWidth = trickplay.width * trickplay.tile_width;
		const sheetHeight = trickplay.height * trickplay.tile_height;

		return {
			url: `${trickplay.base_url}${sheetIndex}.jpg?api_key=${streamInfo.api_key}`,
			bgPosition: `-${col * thumbWidth}px -${row * thumbHeight}px`,
			width: thumbWidth,
			height: thumbHeight,
			sheetWidth,
			sheetHeight,
		};
	}

	function handleSeekBarHover(e: MouseEvent) {
		if (!seekBarEl) return;
		const rect = seekBarEl.getBoundingClientRect();
		hoverPosition = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
	}

	function handleSeekStart(e: MouseEvent) {
		if (!seekBarEl || !videoEl) return;
		const rect = seekBarEl.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		videoEl.currentTime = ratio * duration;

		function onMove(ev: MouseEvent) {
			const r = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
			videoEl.currentTime = r * duration;
			hoverPosition = r;
		}
		function onUp() {
			window.removeEventListener('mousemove', onMove);
			window.removeEventListener('mouseup', onUp);
		}
		window.addEventListener('mousemove', onMove);
		window.addEventListener('mouseup', onUp);
	}

	function toggleFullscreen() {
		if (document.fullscreenElement) {
			document.exitFullscreen();
		} else {
			const container = seekBarEl?.closest('[data-player-container]');
			container?.requestFullscreen();
		}
	}

	// Click = play/pause, double-click = fullscreen
	// Use a timer to distinguish: delay single-click action, cancel if double-click fires
	function handleVideoClick(e: MouseEvent) {
		// Don't trigger on controls bar clicks
		const target = e.target as HTMLElement;
		if (target.closest('button, input, [role="slider"]')) return;

		if (clickTimer) {
			// Double-click: cancel pending play/pause, toggle fullscreen
			clearTimeout(clickTimer);
			clickTimer = null;
			toggleFullscreen();
		} else {
			// Single-click: delay to check for double-click
			clickTimer = setTimeout(() => {
				clickTimer = null;
				videoEl.paused ? videoEl.play() : videoEl.pause();
			}, 200);
		}
	}

	function handleMouseMove() {
		showControls = true;
		if (hideTimer) clearTimeout(hideTimer);
		hideTimer = setTimeout(() => {
			if (isPlaying) showControls = false;
		}, 3000);
	}

	function onFullscreenChange() {
		isFullscreen = !!document.fullscreenElement;
	}

	onMount(() => {
		document.addEventListener('fullscreenchange', onFullscreenChange);
	});

	onDestroy(() => {
		document.removeEventListener('fullscreenchange', onFullscreenChange);
		if (clickTimer) clearTimeout(clickTimer);
		if (hideTimer) clearTimeout(hideTimer);
	});
</script>

<div
	class="absolute inset-0 z-20 {showControls ? 'cursor-default' : 'cursor-none'}"
	onmousemove={handleMouseMove}
	onmouseleave={() => { hoverPosition = null; }}
	onclick={handleVideoClick}
	role="presentation"
>
	<!-- Gradient overlay at bottom for controls -->
	<div class="absolute bottom-0 left-0 right-0 transition-opacity duration-300 {showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'}">
		<div class="bg-gradient-to-t from-black/80 to-transparent pt-16 pb-3 px-4">
			<!-- Seek bar -->
			<div class="relative mb-3 group">
				<!-- Trickplay thumbnail preview -->
				{#if hoverPosition !== null && trickplay}
					{@const tp = getTrickplayStyle(hoverPosition)}
					{#if tp}
						<div
							class="absolute bottom-8 -translate-x-1/2 border border-titan-border rounded overflow-hidden pointer-events-none"
							style="left: {hoverPosition * 100}%; width: {tp.width}px; height: {tp.height}px; background-image: url('{tp.url}'); background-position: {tp.bgPosition}; background-size: {tp.sheetWidth}px {tp.sheetHeight}px;"
						></div>
					{/if}
				{/if}

				<!-- Time tooltip -->
				{#if hoverPosition !== null}
					<div
						class="absolute bottom-6 -translate-x-1/2 bg-black/90 text-white text-xs px-2 py-1 rounded pointer-events-none"
						style="left: {hoverPosition * 100}%"
					>
						{formatTime(hoverPosition * duration)}
					</div>
				{/if}

				<!-- Seek bar track -->
				<div
					bind:this={seekBarEl}
					class="relative h-1 group-hover:h-2 transition-all bg-white/20 rounded cursor-pointer"
					onmousedown={handleSeekStart}
					onmousemove={handleSeekBarHover}
					onmouseleave={() => { hoverPosition = null; }}
					role="slider"
					aria-label="Seek"
					aria-valuemin={0}
					aria-valuemax={duration}
					aria-valuenow={currentTime}
					tabindex={0}
				>
					<!-- Chapter segments -->
					{#each chapters as chapter, i}
						{@const startPct = duration > 0 ? (chapter.start_ticks / 10_000_000 / duration) * 100 : 0}
						{@const endPct = chapter.end_ticks && duration > 0 ? (chapter.end_ticks / 10_000_000 / duration) * 100 : 100}
						<div
							class="absolute top-0 bottom-0 opacity-30"
							style="left: {startPct}%; width: {endPct - startPct}%; background-color: {chapterColors[i % chapterColors.length]};"
						></div>
					{/each}

					<!-- Chapter marker dots -->
					{#each chapters as chapter, i}
						{@const pct = duration > 0 ? (chapter.start_ticks / 10_000_000 / duration) * 100 : 0}
						<div
							class="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-10"
							style="left: {pct}%"
							onmouseenter={() => { hoveredChapterIdx = i; }}
							onmouseleave={() => { hoveredChapterIdx = null; }}
						>
							<div
								class="w-2.5 h-2.5 rounded-full border-2 border-white shadow transition-transform {hoveredChapterIdx === i ? 'scale-150' : 'group-hover:scale-125'}"
								style="background-color: {chapterColors[i % chapterColors.length]};"
							></div>
							{#if hoveredChapterIdx === i}
								<div class="absolute bottom-5 left-1/2 -translate-x-1/2 bg-black/90 text-white text-xs px-2 py-1 rounded whitespace-nowrap pointer-events-none z-50">
									{chapter.title}
								</div>
							{/if}
						</div>
					{/each}

					<!-- Detection tick marks -->
					{#if detections.length > 0}
						{#each detections as det}
							{@const pct = duration > 0 ? (det.timestamp_ticks / 10_000_000 / duration) * 100 : 0}
							{@const color = det.type === 'bell' ? '#f59e0b' : det.type === 'music_start' ? '#22c55e' : '#3b82f6'}
							<div
								class="absolute top-0 bottom-0 w-px opacity-50 pointer-events-none"
								style="left: {pct}%; background-color: {color};"
							></div>
						{/each}
					{/if}

					<!-- Progress -->
					<div
						class="absolute top-0 left-0 bottom-0 bg-titan-accent rounded"
						style="width: {duration > 0 ? (currentTime / duration) * 100 : 0}%"
					></div>

					<!-- Playhead dot -->
					<div
						class="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 bg-titan-accent rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
						style="left: {duration > 0 ? (currentTime / duration) * 100 : 0}%"
					></div>
				</div>
			</div>

			<!-- Controls row -->
			<div class="flex items-center gap-3">
				<!-- Play/Pause -->
				<button onclick={() => videoEl.paused ? videoEl.play() : videoEl.pause()} class="text-white hover:text-titan-accent" aria-label={isPlaying ? 'Pause' : 'Play'}>
					{#if isPlaying}
						<svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/></svg>
					{:else}
						<svg class="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
					{/if}
				</button>

				<!-- Time display -->
				<span class="text-white text-sm font-mono min-w-[100px]">
					{formatTime(currentTime)} / {formatTime(duration)}
				</span>

				<!-- Spacer -->
				<div class="flex-1"></div>

				<!-- Volume -->
				<div class="flex items-center gap-1">
					<button onclick={() => { isMuted = !isMuted; videoEl.muted = !videoEl.muted; }} class="text-white hover:text-titan-accent" aria-label={isMuted ? 'Unmute' : 'Mute'}>
						{#if isMuted || volume === 0}
							<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.796 8.796 0 0021 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06a8.99 8.99 0 003.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>
						{:else}
							<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
						{/if}
					</button>
					<input
						type="range"
						min="0"
						max="1"
						step="0.05"
						value={isMuted ? 0 : volume}
						oninput={(e) => { volume = Number(e.currentTarget.value); videoEl.volume = volume; if (volume > 0) { isMuted = false; videoEl.muted = false; } }}
						class="w-20 accent-titan-accent"
						aria-label="Volume"
					/>
				</div>

				<!-- Fullscreen -->
				<button onclick={toggleFullscreen} class="text-white hover:text-titan-accent" title="Fullscreen (F)" aria-label="Toggle fullscreen">
					{#if isFullscreen}
						<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>
					{:else}
						<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
					{/if}
				</button>
			</div>
		</div>
	</div>
</div>
