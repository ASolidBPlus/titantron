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
	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let showAnalysisMenu = $state(false);

	// Waveform container tracking
	let waveformOuter = $state<HTMLDivElement>(null!);
	let outerWidth = $state(700);
	let resizeObserver: ResizeObserver | null = null;

	// Hover thumbnail state
	let hoverInfo = $state<{
		x: number;       // position in viewport relative to outer container
		time: string;
		music: number;
		thumbStyle: { url: string; bgPosition: string; bgSize: string } | null;
	} | null>(null);

	const WAVEFORM_HEIGHT = 160;

	// Thumbnail dimensions for hover preview
	const thumbPixelW = trickplay.width;
	const thumbPixelH = trickplay.height;
	const sheetPixelW = trickplay.width * trickplay.tile_width;
	const sheetPixelH = trickplay.height * trickplay.tile_height;
	const tilesPerSheet = trickplay.tile_width * trickplay.tile_height;

	// Hover thumbnail display size
	const hoverThumbH = 90;
	const hoverScale = hoverThumbH / thumbPixelH;
	const hoverThumbW = Math.round(thumbPixelW * hoverScale);

	// Waveform inner width (zoomed)
	let waveformWidth = $derived(outerWidth * zoomLevel);

	// Visual detections
	let visualDetections = $derived<Detection[]>(results?.visual ?? []);

	// Bell detections
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

	// Duration in seconds
	let durationSecs = $derived(durationTicks / 10_000_000);

	// Downsampled spectrum — target 2px per point at current zoom
	let downsampled = $derived(downsampleSpectrum(spectrum, waveformWidth * 2, durationSecs));

	// SVG paths
	let areaPath = $derived(buildAreaPath(downsampled, waveformWidth, WAVEFORM_HEIGHT));
	let linePath = $derived(buildLinePath(downsampled, waveformWidth, WAVEFORM_HEIGHT));

	// Playhead x position
	let playheadX = $derived((currentTimeTicks / durationTicks) * waveformWidth);

	// Current music confidence at playhead position
	let currentMusic = $derived.by(() => {
		if (spectrum.length === 0) return null;
		const currentSecs = currentTimeTicks / 10_000_000;
		let closest = spectrum[0];
		let minDist = Math.abs(currentSecs - closest.t);
		for (const pt of spectrum) {
			const dist = Math.abs(currentSecs - pt.t);
			if (dist < minDist) {
				minDist = dist;
				closest = pt;
			}
		}
		return closest.music;
	});

	// Notify parent when detections change
	$effect(() => {
		if (allDetections.length > 0) {
			onDetectionsReady?.(allDetections);
		}
	});

	// --- Downsampling & SVG path helpers ---

	function downsampleSpectrum(
		spec: SpectrumPoint[],
		targetPoints: number,
		durSecs: number,
	): { x: number; value: number }[] {
		if (spec.length === 0 || durSecs <= 0) return [];
		if (spec.length <= targetPoints) {
			return spec.map(p => ({ x: p.t / durSecs, value: p.music }));
		}

		const bucketCount = Math.max(1, Math.floor(targetPoints));
		const bucketDur = durSecs / bucketCount;
		const out: { x: number; value: number }[] = [];

		let si = 0;
		for (let b = 0; b < bucketCount; b++) {
			const bucketStart = b * bucketDur;
			const bucketEnd = bucketStart + bucketDur;
			let maxVal = 0;

			while (si < spec.length && spec[si].t < bucketEnd) {
				if (spec[si].t >= bucketStart) {
					maxVal = Math.max(maxVal, spec[si].music);
				}
				si++;
			}
			if (si > 0 && spec[si - 1].t >= bucketEnd) si--;

			out.push({ x: (bucketStart + bucketDur / 2) / durSecs, value: maxVal });
		}
		return out;
	}

	function buildAreaPath(
		points: { x: number; value: number }[],
		width: number,
		height: number,
	): string {
		if (points.length === 0) return '';
		const margin = 2;
		const usable = height - margin;

		let d = `M 0 ${height}`;
		for (const p of points) {
			const px = p.x * width;
			const py = height - p.value * usable;
			d += ` L ${px.toFixed(1)} ${py.toFixed(1)}`;
		}
		d += ` L ${width} ${height} Z`;
		return d;
	}

	function buildLinePath(
		points: { x: number; value: number }[],
		width: number,
		height: number,
	): string {
		if (points.length === 0) return '';
		const margin = 2;
		const usable = height - margin;

		const first = points[0];
		let d = `M ${(first.x * width).toFixed(1)} ${(height - first.value * usable).toFixed(1)}`;
		for (let i = 1; i < points.length; i++) {
			const p = points[i];
			const px = p.x * width;
			const py = height - p.value * usable;
			d += ` L ${px.toFixed(1)} ${py.toFixed(1)}`;
		}
		return d;
	}

	// --- Thumbnail helpers ---

	function getThumbnailStyle(thumbIndex: number): { url: string; bgPosition: string; bgSize: string } {
		const sheetIndex = Math.floor(thumbIndex / tilesPerSheet);
		const tileOnSheet = thumbIndex % tilesPerSheet;
		const col = tileOnSheet % trickplay.tile_width;
		const row = Math.floor(tileOnSheet / trickplay.tile_width);

		return {
			url: `${trickplay.base_url}${sheetIndex}.jpg`,
			bgPosition: `-${col * thumbPixelW * hoverScale}px -${row * thumbPixelH * hoverScale}px`,
			bgSize: `${sheetPixelW * hoverScale}px ${sheetPixelH * hoverScale}px`,
		};
	}

	function getThumbIndexForTime(timeSecs: number): number {
		const intervalSecs = trickplay.interval / 1000;
		return Math.min(
			Math.max(0, Math.floor(timeSecs / intervalSecs)),
			trickplay.thumbnail_count - 1,
		);
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

	function formatTimeSecs(secs: number): string {
		const h = Math.floor(secs / 3600);
		const m = Math.floor((secs % 3600) / 60);
		const s = Math.floor(secs % 60);
		if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
		return `${m}:${String(s).padStart(2, '0')}`;
	}

	// --- Waveform interaction ---

	function handleWaveformClick(e: MouseEvent) {
		const target = e.currentTarget as HTMLElement;
		const rect = target.getBoundingClientRect();
		const scrollLeft = waveformOuter?.scrollLeft ?? 0;
		const clickX = e.clientX - rect.left + scrollLeft;
		const fraction = clickX / waveformWidth;
		const ticks = Math.floor(fraction * durationTicks);
		onSeekTo(Math.max(0, Math.min(ticks, durationTicks)));
	}

	function handleWaveformHover(e: MouseEvent) {
		if (spectrum.length === 0) return;
		const target = e.currentTarget as HTMLElement;
		const rect = target.getBoundingClientRect();
		const scrollLeft = waveformOuter?.scrollLeft ?? 0;
		const hoverX = e.clientX - rect.left + scrollLeft;
		const fraction = hoverX / waveformWidth;
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

		// Get trickplay thumbnail for this time
		const thumbIdx = getThumbIndexForTime(timeSecs);
		const thumbStyle = getThumbnailStyle(thumbIdx);

		hoverInfo = {
			x: e.clientX - (waveformOuter?.getBoundingClientRect().left ?? 0),
			time: formatTimeSecs(timeSecs),
			music: closest.music,
			thumbStyle: thumbStyle,
		};
	}

	function handleWaveformLeave() {
		hoverInfo = null;
	}

	// --- Analysis controls ---

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
		resizeObserver = new ResizeObserver((entries) => {
			for (const entry of entries) {
				outerWidth = entry.contentRect.width;
			}
		});

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

	// Observe outer container for resize
	$effect(() => {
		if (waveformOuter && resizeObserver) {
			resizeObserver.observe(waveformOuter);
			outerWidth = waveformOuter.clientWidth || 700;
			return () => resizeObserver?.unobserve(waveformOuter);
		}
	});

	onDestroy(() => {
		stopPolling();
		resizeObserver?.disconnect();
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
</script>

<div class="bg-titan-surface border border-titan-border rounded-lg">
	<!-- Header -->
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
				<!-- Zoom controls -->
				<span class="text-xs text-titan-text-muted">|</span>
				<div class="flex items-center gap-1">
					<button
						onclick={() => { zoomLevel = Math.max(1, zoomLevel / 2); }}
						disabled={zoomLevel <= 1}
						class="text-xs px-1.5 py-0.5 bg-titan-border rounded hover:bg-titan-surface-hover disabled:opacity-30"
					>-</button>
					<span class="text-xs text-titan-text-muted w-8 text-center">{zoomLevel}x</span>
					<button
						onclick={() => { zoomLevel = Math.min(16, zoomLevel * 2); }}
						disabled={zoomLevel >= 16}
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

	<!-- Waveform -->
	{#if status.status === 'completed' && results}
		{#if spectrum.length > 0}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="relative overflow-x-auto overflow-y-hidden cursor-crosshair"
				bind:this={waveformOuter}
				onclick={handleWaveformClick}
				onmousemove={handleWaveformHover}
				onmouseleave={handleWaveformLeave}
			>
				<svg
					width={waveformWidth}
					height={WAVEFORM_HEIGHT}
					viewBox="0 0 {waveformWidth} {WAVEFORM_HEIGHT}"
					preserveAspectRatio="none"
					class="block"
				>
					<defs>
						<linearGradient id="waveformGrad" x1="0" y1="0" x2="0" y2="1">
							<stop offset="0%" stop-color="#22c55e" stop-opacity="0.9" />
							<stop offset="100%" stop-color="#22c55e" stop-opacity="0.05" />
						</linearGradient>
					</defs>

					<!-- Filled area -->
					{#if areaPath}
						<path d={areaPath} fill="url(#waveformGrad)" />
						<path d={linePath} fill="none" stroke="#22c55e" stroke-width="1.5" stroke-opacity="0.7" />
					{/if}

					<!-- Bell markers (amber vertical lines) -->
					{#each bellDetections as bell}
						{@const bx = (bell.timestamp_ticks / durationTicks) * waveformWidth}
						<line
							x1={bx} y1="0" x2={bx} y2={WAVEFORM_HEIGHT}
							stroke="#f59e0b" stroke-width="1.5" stroke-opacity="0.8"
						/>
					{/each}

					<!-- Playhead (red vertical line) -->
					<line
						x1={playheadX} y1="0" x2={playheadX} y2={WAVEFORM_HEIGHT}
						stroke="#e63946" stroke-width="2" stroke-opacity="0.9"
					/>
				</svg>

				<!-- Hover tooltip with thumbnail preview -->
				{#if hoverInfo}
					<div
						class="absolute z-30 pointer-events-none flex flex-col items-center gap-1"
						style="left: {hoverInfo.x}px; top: 0; transform: translateX(-50%)"
					>
						<!-- Thumbnail -->
						{#if hoverInfo.thumbStyle}
							<div
								class="rounded border border-titan-border shadow-lg"
								style="width: {hoverThumbW}px; height: {hoverThumbH}px;
									background-image: url('{hoverInfo.thumbStyle.url}');
									background-position: {hoverInfo.thumbStyle.bgPosition};
									background-size: {hoverInfo.thumbStyle.bgSize};
									background-repeat: no-repeat;"
							></div>
						{/if}
						<!-- Info -->
						<div class="bg-titan-bg/95 border border-titan-border rounded px-2 py-0.5 text-[10px] whitespace-nowrap">
							<span class="text-titan-text">{hoverInfo.time}</span>
							<span class="text-titan-text-muted mx-1">&middot;</span>
							<span style="color: rgba(34, 197, 94, {0.5 + hoverInfo.music * 0.5})">{(hoverInfo.music * 100).toFixed(0)}% music</span>
						</div>
					</div>
				{/if}
			</div>
		{:else}
			<div bind:this={waveformOuter} class="flex items-center justify-center h-12 text-xs text-titan-text-muted">
				No audio spectrum data available
			</div>
		{/if}

		<!-- Info bar -->
		<div class="flex items-center gap-2 px-3 py-1.5 text-[10px] text-titan-text-muted border-t border-titan-border">
			{#if currentMusic !== null}
				<span style="color: rgba(34, 197, 94, {0.5 + currentMusic * 0.5})">{(currentMusic * 100).toFixed(0)}% music</span>
				<span>&middot;</span>
			{/if}
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
	{/if}
</div>
