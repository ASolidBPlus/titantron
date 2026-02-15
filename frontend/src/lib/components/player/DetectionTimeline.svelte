<script lang="ts">
	import type { TrickplayInfo, Detection, Chapter } from '$lib/types';

	interface Props {
		trickplay: TrickplayInfo;
		durationTicks: number;
		currentTimeTicks: number;
		visualDetections: Detection[];
		audioDetections: Detection[];
		chapters: Chapter[];
		onSeekTo: (ticks: number) => void;
		onDetectionClick: (detection: Detection) => void;
	}

	let {
		trickplay,
		durationTicks,
		currentTimeTicks,
		visualDetections,
		audioDetections,
		chapters,
		onSeekTo,
		onDetectionClick,
	}: Props = $props();

	let zoomLevel = $state(2);
	let scrollContainer = $state<HTMLDivElement>(null!);

	// Thumbnail dimensions
	const thumbPixelW = trickplay.width;
	const thumbPixelH = trickplay.height;
	const sheetPixelW = trickplay.width * trickplay.tile_width;
	const sheetPixelH = trickplay.height * trickplay.tile_height;
	const tilesPerSheet = trickplay.tile_width * trickplay.tile_height;

	// Display dimensions (scale thumbs for trickplay lane)
	const thumbDisplayH = 45;
	const thumbScale = thumbDisplayH / thumbPixelH;
	const thumbDisplayW = Math.round(thumbPixelW * thumbScale);

	// Total timeline width
	let timelineWidth = $derived(trickplay.thumbnail_count * thumbDisplayW * zoomLevel);

	// Lane heights
	const TRICKPLAY_LANE_H = thumbDisplayH;
	const MARKER_LANE_H = 24;
	const CHAPTER_LANE_H = 24;
	const TOTAL_H = TRICKPLAY_LANE_H + MARKER_LANE_H * 2 + CHAPTER_LANE_H + 4; // 4px for gaps

	function getThumbnailStyle(thumbIndex: number): { url: string; bgPosition: string; bgSize: string } {
		const sheetIndex = Math.floor(thumbIndex / tilesPerSheet);
		const tileOnSheet = thumbIndex % tilesPerSheet;
		const col = tileOnSheet % trickplay.tile_width;
		const row = Math.floor(tileOnSheet / trickplay.tile_width);
		return {
			url: `${trickplay.base_url}${sheetIndex}.jpg`,
			bgPosition: `-${col * thumbPixelW * thumbScale * zoomLevel}px -${row * thumbPixelH * thumbScale * zoomLevel}px`,
			bgSize: `${sheetPixelW * thumbScale * zoomLevel}px ${sheetPixelH * thumbScale * zoomLevel}px`,
		};
	}

	function markerColor(type: string): string {
		switch (type) {
			case 'scene_change': return '#3b82f6';
			case 'dark_frame': return '#6b7280';
			case 'graphics_change': return '#a855f7';
			case 'bell': return '#f59e0b';
			case 'music_start': return '#22c55e';
			default: return '#8888a0';
		}
	}

	const chapterColors = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

	function ticksToX(ticks: number): number {
		if (durationTicks <= 0) return 0;
		return (ticks / durationTicks) * timelineWidth;
	}

	function handleLaneClick(e: MouseEvent, lane: HTMLDivElement) {
		const rect = lane.getBoundingClientRect();
		const scrollLeft = scrollContainer?.scrollLeft ?? 0;
		const x = e.clientX - rect.left + scrollLeft;
		const ratio = x / timelineWidth;
		const ticks = Math.floor(ratio * durationTicks);
		onSeekTo(Math.max(0, Math.min(durationTicks, ticks)));
	}

	// Visible thumbnail range for performance
	let visibleStart = $state(0);
	let visibleEnd = $state(100);

	function handleScroll() {
		if (!scrollContainer) return;
		const scrollLeft = scrollContainer.scrollLeft;
		const containerWidth = scrollContainer.clientWidth;
		const thumbW = thumbDisplayW * zoomLevel;
		visibleStart = Math.max(0, Math.floor(scrollLeft / thumbW) - 2);
		visibleEnd = Math.min(trickplay.thumbnail_count, Math.ceil((scrollLeft + containerWidth) / thumbW) + 2);
	}

	$effect(() => {
		zoomLevel;
		handleScroll();
	});
</script>

<div class="bg-titan-surface border border-titan-border rounded-lg overflow-hidden">
	<!-- Zoom controls -->
	<div class="flex items-center gap-3 px-3 py-1.5 border-b border-titan-border">
		<span class="text-xs text-titan-text-muted font-medium">Timeline</span>
		<div class="flex-1"></div>
		<!-- Legend -->
		<div class="flex items-center gap-2.5 text-[10px] text-titan-text-muted">
			<span class="flex items-center gap-1">
				<span class="w-1.5 h-1.5 rounded-full" style="background: #3b82f6"></span>
				Scene
			</span>
			<span class="flex items-center gap-1">
				<span class="w-1.5 h-1.5 rounded-full" style="background: #6b7280"></span>
				Dark
			</span>
			<span class="flex items-center gap-1">
				<span class="w-1.5 h-1.5 rounded-full" style="background: #a855f7"></span>
				Graphics
			</span>
			<span class="flex items-center gap-1">
				<span class="w-1.5 h-1.5 rounded-full" style="background: #f59e0b"></span>
				Bell
			</span>
			<span class="flex items-center gap-1">
				<span class="w-1.5 h-1.5 rounded-full" style="background: #22c55e"></span>
				Music
			</span>
		</div>
		<span class="text-titan-border">|</span>
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
	</div>

	<!-- Scrollable timeline -->
	<div
		class="relative overflow-x-auto"
		bind:this={scrollContainer}
		onscroll={handleScroll}
	>
		<div class="relative" style="width: {timelineWidth}px; height: {TOTAL_H}px">
			<!-- Lane labels (sticky left) -->
			<div class="absolute left-0 top-0 bottom-0 w-14 bg-titan-surface/90 backdrop-blur-sm z-30 border-r border-titan-border flex flex-col" style="position: sticky; left: 0;">
				<div class="flex items-center px-1.5 text-[9px] text-titan-text-muted font-medium" style="height: {TRICKPLAY_LANE_H}px">Frames</div>
				<div class="flex items-center px-1.5 text-[9px] text-titan-text-muted font-medium" style="height: {MARKER_LANE_H}px">Visual</div>
				<div class="flex items-center px-1.5 text-[9px] text-titan-text-muted font-medium" style="height: {MARKER_LANE_H}px">Audio</div>
				<div class="flex items-center px-1.5 text-[9px] text-titan-text-muted font-medium" style="height: {CHAPTER_LANE_H}px">Chapters</div>
			</div>

			<!-- Lane 1: Trickplay thumbnails -->
			<div
				class="absolute left-0 top-0 flex cursor-pointer"
				style="height: {TRICKPLAY_LANE_H}px"
				onclick={(e) => {
					const target = e.currentTarget as HTMLDivElement;
					handleLaneClick(e, target);
				}}
				role="button"
				tabindex="-1"
			>
				{#each Array(trickplay.thumbnail_count) as _, i}
					{#if i >= visibleStart && i < visibleEnd}
						{@const style = getThumbnailStyle(i)}
						<div
							class="shrink-0 hover:brightness-125 transition-[filter]"
							style="width: {thumbDisplayW * zoomLevel}px; height: {TRICKPLAY_LANE_H}px;
								background-image: url('{style.url}');
								background-position: {style.bgPosition};
								background-size: {style.bgSize};
								background-repeat: no-repeat;"
						></div>
					{:else}
						<div
							class="shrink-0"
							style="width: {thumbDisplayW * zoomLevel}px; height: {TRICKPLAY_LANE_H}px;"
						></div>
					{/if}
				{/each}
			</div>

			<!-- Lane 2: Visual detections -->
			<div
				class="absolute left-0 bg-titan-bg/50 cursor-pointer"
				style="top: {TRICKPLAY_LANE_H}px; width: {timelineWidth}px; height: {MARKER_LANE_H}px"
				onclick={(e) => {
					const target = e.currentTarget as HTMLDivElement;
					handleLaneClick(e, target);
				}}
				role="button"
				tabindex="-1"
			>
				{#each visualDetections as det}
					<button
						class="absolute top-0.5 bottom-0.5 w-1.5 rounded-sm hover:w-2.5 transition-all z-10"
						style="left: {ticksToX(det.timestamp_ticks)}px;
							background-color: {markerColor(det.type)};
							opacity: {0.5 + det.confidence * 0.5};"
						onclick={(e) => { e.stopPropagation(); onDetectionClick(det); }}
						title="{det.type} ({(det.confidence * 100).toFixed(0)}%)"
					></button>
				{/each}
			</div>

			<!-- Lane 3: Audio detections -->
			<div
				class="absolute left-0 bg-titan-bg/30 cursor-pointer"
				style="top: {TRICKPLAY_LANE_H + MARKER_LANE_H}px; width: {timelineWidth}px; height: {MARKER_LANE_H}px"
				onclick={(e) => {
					const target = e.currentTarget as HTMLDivElement;
					handleLaneClick(e, target);
				}}
				role="button"
				tabindex="-1"
			>
				{#each audioDetections as det}
					<button
						class="absolute top-0.5 bottom-0.5 w-1.5 rounded-sm hover:w-2.5 transition-all z-10"
						style="left: {ticksToX(det.timestamp_ticks)}px;
							background-color: {markerColor(det.type)};
							opacity: {0.5 + det.confidence * 0.5};"
						onclick={(e) => { e.stopPropagation(); onDetectionClick(det); }}
						title="{det.type} ({(det.confidence * 100).toFixed(0)}%)"
					></button>
				{/each}
			</div>

			<!-- Lane 4: Chapters -->
			<div
				class="absolute left-0 cursor-pointer"
				style="top: {TRICKPLAY_LANE_H + MARKER_LANE_H * 2}px; width: {timelineWidth}px; height: {CHAPTER_LANE_H}px"
				onclick={(e) => {
					const target = e.currentTarget as HTMLDivElement;
					handleLaneClick(e, target);
				}}
				role="button"
				tabindex="-1"
			>
				{#each chapters as chapter, i}
					{@const startX = ticksToX(chapter.start_ticks)}
					{@const endX = chapter.end_ticks ? ticksToX(chapter.end_ticks) : (i < chapters.length - 1 ? ticksToX(chapters[i + 1].start_ticks) : timelineWidth)}
					{@const width = Math.max(2, endX - startX)}
					<div
						class="absolute top-0.5 bottom-0.5 rounded-sm overflow-hidden flex items-center px-1"
						style="left: {startX}px; width: {width}px; background-color: {chapterColors[i % chapterColors.length]}40;"
					>
						<span class="text-[9px] text-white truncate pointer-events-none">{chapter.title}</span>
					</div>
				{/each}
			</div>

			<!-- Playback position line (all lanes) -->
			<div
				class="absolute top-0 w-0.5 bg-red-500 z-20 pointer-events-none"
				style="left: {ticksToX(currentTimeTicks)}px; height: {TOTAL_H}px"
			></div>
		</div>
	</div>
</div>
