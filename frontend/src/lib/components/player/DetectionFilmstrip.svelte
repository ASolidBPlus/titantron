<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { TrickplayInfo, Detection, AnalysisStatus, AnalysisResults, SpectrumPoint } from '$lib/types';
	import { startAnalysis, getAnalysisStatus, getAnalysisResults, clearAnalysis } from '$lib/api/client';

	interface Props {
		videoId: number;
		trickplay: TrickplayInfo;
		durationTicks: number;
		currentTimeTicks: number;
		onSeekTo: (ticks: number) => void;
		onDetectionsReady?: (detections: Detection[]) => void;
	}

	let {
		videoId,
		trickplay,
		durationTicks,
		currentTimeTicks,
		onSeekTo,
		onDetectionsReady,
	}: Props = $props();

	let status = $state<AnalysisStatus>({ status: 'none' });
	let results = $state<AnalysisResults | null>(null);
	let zoomLevel = $state(1);
	let scrollContainer = $state<HTMLDivElement>(null!);
	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let showAnalysisMenu = $state(false);

	// Spectrum tooltip state
	let spectrumTooltip = $state<{ x: number; y: number; time: string; music: number } | null>(null);

	// Thumbnail dimensions (width/height from Jellyfin are individual thumb size)
	const thumbPixelW = trickplay.width;
	const thumbPixelH = trickplay.height;
	const sheetPixelW = trickplay.width * trickplay.tile_width;
	const sheetPixelH = trickplay.height * trickplay.tile_height;
	const tilesPerSheet = trickplay.tile_width * trickplay.tile_height;

	// Display dimensions (scale down thumbnails)
	const displayH = 60;
	const scale = displayH / thumbPixelH;
	const displayW = Math.round(thumbPixelW * scale);

	const SPECTRUM_HEIGHT = 14;

	// Filmstrip dimensions
	let filmstripWidth = $derived(trickplay.thumbnail_count * displayW * zoomLevel);

	// Visual detections only (scene_change, dark_frame, graphics_change) — shown as subtle markers on filmstrip
	let visualDetections = $derived<Detection[]>(
		results?.visual ?? []
	);

	// Bell detections — shown as amber lines on spectrum strip
	let bellDetections = $derived<Detection[]>(
		results?.audio.filter(d => d.type === 'bell') ?? []
	);

	// All detections for parent notification
	let allDetections = $derived<Detection[]>(
		results
			? [...results.visual, ...results.audio].sort((a, b) => a.timestamp_ticks - b.timestamp_ticks)
			: []
	);

	// Spectrum data
	let spectrum = $derived<SpectrumPoint[]>(results?.audio_spectrum ?? []);
	let windowSecs = $derived(results?.audio_window_secs ?? 30);

	// Duration in seconds for spectrum calculations
	let durationSecs = $derived(durationTicks / 10_000_000);

	// Notify parent when detections change
	$effect(() => {
		if (allDetections.length > 0) {
			onDetectionsReady?.(allDetections);
		}
	});

	// Generate thumbnail data for rendering
	function getThumbnailStyle(thumbIndex: number): { url: string; bgPosition: string; bgSize: string } {
		const sheetIndex = Math.floor(thumbIndex / tilesPerSheet);
		const tileOnSheet = thumbIndex % tilesPerSheet;
		const col = tileOnSheet % trickplay.tile_width;
		const row = Math.floor(tileOnSheet / trickplay.tile_width);

		return {
			url: `${trickplay.base_url}${sheetIndex}.jpg`,
			bgPosition: `-${col * thumbPixelW * scale}px -${row * thumbPixelH * scale}px`,
			bgSize: `${sheetPixelW * scale}px ${sheetPixelH * scale}px`,
		};
	}

	// Combine skip reason from status (polling) and results (persisted)
	let audioSkipReason = $derived(results?.audio_skip_reason ?? status.audio_skip_reason);

	function audioSkipMessage(reason: string): string {
		if (reason === 'no_path_mapping') {
			return 'Audio skipped — configure path mapping in Admin \u2192 Setup';
		}
		if (reason.startsWith('file_not_found:')) {
			return 'Audio skipped — video file not accessible (check Docker volume mounts)';
		}
		if (reason.startsWith('error:')) {
			return `Audio failed: ${reason.slice(6)}`;
		}
		return `Audio skipped: ${reason}`;
	}

	function markerColor(type: string): string {
		switch (type) {
			case 'scene_change': return '#3b82f6';
			case 'dark_frame': return '#6b7280';
			case 'graphics_change': return '#a855f7';
			default: return '#8888a0';
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

	function formatTimeSecs(secs: number): string {
		const h = Math.floor(secs / 3600);
		const m = Math.floor((secs % 3600) / 60);
		const s = Math.floor(secs % 60);
		if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
		return `${m}:${String(s).padStart(2, '0')}`;
	}

	function handleSpectrumClick(e: MouseEvent) {
		const target = e.currentTarget as HTMLElement;
		const rect = target.getBoundingClientRect();
		const scrollLeft = scrollContainer?.scrollLeft ?? 0;
		const clickX = e.clientX - rect.left + scrollLeft;
		const fraction = clickX / filmstripWidth;
		const ticks = Math.floor(fraction * durationTicks);
		onSeekTo(Math.max(0, Math.min(ticks, durationTicks)));
	}

	function handleSpectrumHover(e: MouseEvent) {
		if (spectrum.length === 0) return;
		const target = e.currentTarget as HTMLElement;
		const rect = target.getBoundingClientRect();
		const scrollLeft = scrollContainer?.scrollLeft ?? 0;
		const hoverX = e.clientX - rect.left + scrollLeft;
		const fraction = hoverX / filmstripWidth;
		const timeSecs = fraction * durationSecs;

		// Find closest spectrum window
		let closest = spectrum[0];
		let minDist = Math.abs(timeSecs - closest.t);
		for (const pt of spectrum) {
			const dist = Math.abs(timeSecs - pt.t);
			if (dist < minDist) {
				minDist = dist;
				closest = pt;
			}
		}

		spectrumTooltip = {
			x: e.clientX - rect.left,
			y: rect.top - (scrollContainer?.getBoundingClientRect().top ?? 0) - 4,
			time: formatTimeSecs(timeSecs),
			music: closest.music,
		};
	}

	function handleSpectrumLeave() {
		spectrumTooltip = null;
	}

	async function handleStartAnalysis(phase: 'both' | 'visual' | 'audio' = 'both') {
		showAnalysisMenu = false;
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

	onMount(async () => {
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
	});

	onDestroy(() => {
		stopPolling();
	});

	// Close analysis menu when clicking outside
	function handleClickOutside(e: MouseEvent) {
		if (showAnalysisMenu) {
			const target = e.target as HTMLElement;
			if (!target.closest('.relative')) {
				showAnalysisMenu = false;
			}
		}
	}

	$effect(() => {
		if (showAnalysisMenu) {
			document.addEventListener('click', handleClickOutside, true);
			return () => document.removeEventListener('click', handleClickOutside, true);
		}
	});

	// Visible thumbnail range for performance (only render what's in view)
	let visibleStart = $state(0);
	let visibleEnd = $state(100);

	function handleScroll() {
		if (!scrollContainer) return;
		const scrollLeft = scrollContainer.scrollLeft;
		const containerWidth = scrollContainer.clientWidth;
		const thumbW = displayW * zoomLevel;
		visibleStart = Math.max(0, Math.floor(scrollLeft / thumbW) - 2);
		visibleEnd = Math.min(trickplay.thumbnail_count, Math.ceil((scrollLeft + containerWidth) / thumbW) + 2);
	}

	$effect(() => {
		// Re-calculate visible range when zoom changes
		zoomLevel;
		handleScroll();
	});
</script>

<div class="bg-titan-surface border border-titan-border rounded-lg">
	<!-- Header (outside overflow-hidden so dropdowns aren't clipped) -->
	<div class="relative flex items-center gap-3 px-3 py-2 border-b border-titan-border">
		<span class="text-sm font-medium text-titan-text-muted">Match Detection</span>
		<div class="flex-1"></div>

		{#if status.status === 'none'}
			<div class="relative">
				<button
					onclick={() => { showAnalysisMenu = !showAnalysisMenu; }}
					class="text-xs px-3 py-1.5 bg-titan-accent text-white rounded hover:opacity-90 transition-opacity flex items-center gap-1"
				>
					Detect Match Boundaries
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
				</button>
				{#if showAnalysisMenu}
					<div class="absolute right-0 top-full mt-1 bg-titan-surface border border-titan-border rounded-lg shadow-lg z-50 py-1 min-w-[140px]">
						<button onclick={() => handleStartAnalysis('both')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">All</button>
						<button onclick={() => handleStartAnalysis('visual')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Visual Only</button>
						<button onclick={() => handleStartAnalysis('audio')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Audio Only</button>
					</div>
				{/if}
			</div>
		{:else if status.status?.startsWith('running')}
			<div class="flex items-center gap-2 flex-1">
				<div class="animate-spin h-3.5 w-3.5 border-2 border-titan-accent border-t-transparent rounded-full"></div>
				<span class="text-xs text-titan-text-muted truncate">{status.message}</span>
				{#if status.progress && status.total_steps}
					<div class="flex-1 max-w-[200px] bg-titan-border rounded-full h-1.5">
						<div
							class="bg-titan-accent h-1.5 rounded-full transition-all"
							style="width: {(status.progress / status.total_steps) * 100}%"
						></div>
					</div>
				{/if}
			</div>
		{:else if status.status === 'completed'}
			<div class="flex items-center gap-2">
				<!-- Legend -->
				<div class="flex items-center gap-2 text-[10px] text-titan-text-muted">
					{#if spectrum.length > 0}
						<span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" style="background: #22c55e"></span>Music</span>
					{/if}
					{#if bellDetections.length > 0}
						<span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full" style="background: #f59e0b"></span>Bell</span>
					{/if}
				</div>
				<span class="text-xs text-titan-text-muted">|</span>
				<!-- Zoom controls -->
				<div class="flex items-center gap-1">
					<button
						onclick={() => { zoomLevel = Math.max(1, zoomLevel / 2); }}
						disabled={zoomLevel <= 1}
						class="text-xs px-1.5 py-0.5 bg-titan-border rounded hover:bg-titan-surface-hover disabled:opacity-30"
					>-</button>
					<span class="text-xs text-titan-text-muted w-8 text-center">{zoomLevel}x</span>
					<button
						onclick={() => { zoomLevel = Math.min(8, zoomLevel * 2); }}
						disabled={zoomLevel >= 8}
						class="text-xs px-1.5 py-0.5 bg-titan-border rounded hover:bg-titan-surface-hover disabled:opacity-30"
					>+</button>
				</div>
				<button
					onclick={handleClear}
					class="text-xs px-2 py-1 text-titan-text-muted hover:text-red-400 transition-colors"
					title="Clear analysis results"
				>Clear</button>
				<div class="relative">
					<button
						onclick={() => { showAnalysisMenu = !showAnalysisMenu; }}
						class="text-xs px-2 py-1 text-titan-text-muted hover:text-titan-text transition-colors flex items-center gap-0.5"
						title="Re-analyze"
					>
						Re-run
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
					</button>
					{#if showAnalysisMenu}
						<div class="absolute right-0 top-full mt-1 bg-titan-surface border border-titan-border rounded-lg shadow-lg z-50 py-1 min-w-[140px]">
							<button onclick={() => handleStartAnalysis('both')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">All</button>
							<button onclick={() => handleStartAnalysis('visual')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Visual Only</button>
							<button onclick={() => handleStartAnalysis('audio')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Audio Only</button>
						</div>
					{/if}
				</div>
			</div>
		{:else if status.status === 'failed'}
			<span class="text-xs text-red-400 truncate">{status.error || status.message || 'Analysis failed'}</span>
			<div class="relative">
				<button
					onclick={() => { showAnalysisMenu = !showAnalysisMenu; }}
					class="text-xs px-2 py-1 bg-titan-border rounded hover:bg-titan-surface-hover flex items-center gap-0.5"
				>
					Retry
					<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
				</button>
				{#if showAnalysisMenu}
					<div class="absolute right-0 top-full mt-1 bg-titan-surface border border-titan-border rounded-lg shadow-lg z-50 py-1 min-w-[140px]">
						<button onclick={() => handleStartAnalysis('both')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">All</button>
						<button onclick={() => handleStartAnalysis('visual')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Visual Only</button>
						<button onclick={() => handleStartAnalysis('audio')} class="w-full text-left text-xs px-3 py-1.5 hover:bg-titan-surface-hover">Audio Only</button>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Filmstrip + Spectrum -->
	{#if status.status === 'completed' && results}
		<div
			class="relative overflow-x-auto overflow-y-hidden rounded-b-lg"
			bind:this={scrollContainer}
			onscroll={handleScroll}
		>
			<div class="relative" style="width: {filmstripWidth}px; height: {displayH + SPECTRUM_HEIGHT + 16}px">
				<!-- Thumbnail strip -->
				<div class="flex" style="height: {displayH}px">
					{#each Array(trickplay.thumbnail_count) as _, i}
						{#if i >= visibleStart && i < visibleEnd}
							{@const style = getThumbnailStyle(i)}
							<div
								class="shrink-0 cursor-pointer hover:brightness-125 transition-[filter]"
								style="width: {displayW * zoomLevel}px; height: {displayH}px;
									background-image: url('{style.url}');
									background-position: {style.bgPosition};
									background-size: {style.bgSize};
									background-repeat: no-repeat;"
								onclick={() => onSeekTo(i * trickplay.interval * 10_000)}
								role="button"
								tabindex="-1"
							></div>
						{:else}
							<div
								class="shrink-0"
								style="width: {displayW * zoomLevel}px; height: {displayH}px;"
							></div>
						{/if}
					{/each}
				</div>

				<!-- Visual detection markers (subtle, on filmstrip) -->
				{#each visualDetections as detection}
					{@const leftPx = (detection.timestamp_ticks / durationTicks) * filmstripWidth}
					<div
						class="absolute top-0 w-0.5 pointer-events-none"
						style="left: {leftPx}px; height: {displayH}px;
							background-color: {markerColor(detection.type)};
							opacity: {0.2 + detection.confidence * 0.3};"
					></div>
				{/each}

				<!-- Music spectrum strip -->
				{#if spectrum.length > 0}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="relative cursor-pointer"
						style="height: {SPECTRUM_HEIGHT}px; width: {filmstripWidth}px; top: 0;"
						onclick={handleSpectrumClick}
						onmousemove={handleSpectrumHover}
						onmouseleave={handleSpectrumLeave}
					>
						<!-- Render spectrum segments -->
						{#each spectrum as point, i}
							{@const segStartFrac = point.t / durationSecs}
							{@const nextT = i < spectrum.length - 1 ? spectrum[i + 1].t : point.t + windowSecs}
							{@const segWidthFrac = (nextT - point.t) / durationSecs}
							<div
								class="absolute top-0"
								style="left: {segStartFrac * 100}%;
									width: {segWidthFrac * 100}%;
									height: {SPECTRUM_HEIGHT}px;
									background-color: rgba(34, 197, 94, {point.music * 0.8});"
							></div>
						{/each}

						<!-- Bell markers on spectrum -->
						{#each bellDetections as bell}
							{@const leftPx = (bell.timestamp_ticks / durationTicks) * filmstripWidth}
							<div
								class="absolute top-0 w-0.5"
								style="left: {leftPx}px; height: {SPECTRUM_HEIGHT}px;
									background-color: #f59e0b;"
								title="Bell ({(bell.confidence * 100).toFixed(0)}%) at {formatTime(bell.timestamp_ticks)}"
							></div>
						{/each}
					</div>
				{/if}

				<!-- Current playback position (spans filmstrip + spectrum) -->
				<div
					class="absolute top-0 w-0.5 bg-titan-accent z-20 pointer-events-none"
					style="left: {(currentTimeTicks / durationTicks) * filmstripWidth}px; height: {displayH + (spectrum.length > 0 ? SPECTRUM_HEIGHT : 0)}px"
				></div>

				<!-- Spectrum tooltip -->
				{#if spectrumTooltip}
					<div
						class="absolute z-30 bg-titan-bg border border-titan-border rounded px-2 py-1 -translate-x-1/2 pointer-events-none text-[10px] whitespace-nowrap"
						style="left: {spectrumTooltip.x}px; top: {spectrumTooltip.y - 28}px"
					>
						<span class="text-titan-text">{spectrumTooltip.time}</span>
						<span class="text-titan-text-muted mx-1">&middot;</span>
						<span style="color: rgba(34, 197, 94, {0.5 + spectrumTooltip.music * 0.5})">{(spectrumTooltip.music * 100).toFixed(0)}% music</span>
						<span class="text-titan-text-muted ml-1">click to seek</span>
					</div>
				{/if}

				<!-- Info bar at bottom -->
				<div class="flex items-center h-4 px-1 text-[10px] text-titan-text-muted">
					{#if spectrum.length > 0}
						{spectrum.length} windows ({windowSecs}s)
					{/if}
					{#if bellDetections.length > 0}
						&middot; {bellDetections.length} bells
					{/if}
					{#if visualDetections.length > 0}
						&middot; {visualDetections.length} visual
					{/if}
					{#if audioSkipReason}
						<span class="ml-2 px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">
							{audioSkipMessage(audioSkipReason)}
						</span>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>
