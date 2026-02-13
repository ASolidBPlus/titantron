const API_BASE = '/api/v1';

class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
	const response = await fetch(`${API_BASE}${path}`, {
		...options,
		credentials: 'include',
		headers: {
			'Content-Type': 'application/json',
			...options.headers
		}
	});

	if (!response.ok) {
		throw new ApiError(response.status, await response.text());
	}

	return response.json();
}

// Auth
export interface AuthStatus {
	connected: boolean;
	jellyfin_url?: string;
	username?: string;
	libraries?: {
		id: number;
		name: string;
		promotion_name: string;
		video_count: number;
		last_synced: string | null;
	}[];
}

export interface ConnectRequest {
	url: string;
	username: string;
	password: string;
}

export interface ConnectResponse {
	success: boolean;
	username: string;
	user_id: string;
}

export function getAuthStatus(): Promise<AuthStatus> {
	return request('/auth/status');
}

export function connect(data: ConnectRequest): Promise<ConnectResponse> {
	return request('/auth/connect', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function disconnect(): Promise<void> {
	return request('/auth/disconnect', { method: 'POST' });
}

// Libraries
export interface JellyfinLibrary {
	id: string;
	name: string;
	collection_type: string;
}

export interface ConfiguredLibrary {
	id: number;
	jellyfin_library_id: string;
	name: string;
	promotion_id: number;
	promotion_name: string;
	promotion_abbreviation: string;
	video_count: number;
	last_synced: string | null;
}

export interface ConfigureLibraryRequest {
	jellyfin_library_id: string;
	jellyfin_library_name: string;
	cagematch_promotion_id: number;
	promotion_name: string;
	promotion_abbreviation: string;
}

export function getJellyfinLibraries(): Promise<JellyfinLibrary[]> {
	return request('/libraries/jellyfin');
}

export function getConfiguredLibraries(): Promise<ConfiguredLibrary[]> {
	return request('/libraries');
}

export function configureLibrary(data: ConfigureLibraryRequest): Promise<ConfiguredLibrary> {
	return request('/libraries', {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function deleteLibrary(id: number): Promise<void> {
	return request(`/libraries/${id}`, { method: 'DELETE' });
}

// Sync
export interface SyncStatus {
	is_running: boolean;
	library_id?: number;
	progress?: number;
	total?: number;
	message?: string;
}

export function syncLibrary(libraryId: number): Promise<{ message: string }> {
	return request(`/libraries/${libraryId}/sync`, { method: 'POST' });
}

export function getSyncStatus(): Promise<SyncStatus> {
	return request('/sync/status');
}

// Browse
import type { Promotion, Event, EventDetail, EventComment, VideoItem, MatchCandidate, MatchStatus, PlayerInfo, Chapter, WrestlerProfile, WrestlerMatchHistory, SearchResults } from '$lib/types';

export function getPromotions(): Promise<Promotion[]> {
	return request('/browse/promotions');
}

export function getPromotionEvents(promotionId: number, year?: number): Promise<{ promotion: { id: number; cagematch_id: number; name: string; abbreviation: string }; events: Event[] }> {
	const params = year ? `?year=${year}` : '';
	return request(`/browse/promotions/${promotionId}/events${params}`);
}

export function getEventDetail(eventId: number): Promise<EventDetail> {
	return request(`/browse/events/${eventId}`);
}

export function scrapeEventMatches(eventId: number): Promise<{ message: string; count: number }> {
	return request(`/browse/events/${eventId}/scrape-matches`, { method: 'POST' });
}

export function getEventComments(eventId: number): Promise<EventComment[]> {
	return request(`/browse/events/${eventId}/comments`);
}

// Matching
export function triggerMatching(libraryId: number): Promise<{ message: string }> {
	return request(`/matching/libraries/${libraryId}/match`, { method: 'POST' });
}

export function getMatchingStatus(): Promise<MatchStatus> {
	return request('/matching/status');
}

export function getLibraryVideos(libraryId: number, status?: string): Promise<VideoItem[]> {
	const params = status ? `?status=${status}` : '';
	return request(`/matching/libraries/${libraryId}/videos${params}`);
}

export function getVideoCandidates(videoId: number): Promise<{ video_id: number; video_title: string; extracted_date: string; candidates: MatchCandidate[] }> {
	return request(`/matching/videos/${videoId}/candidates`);
}

export function confirmMatch(videoId: number): Promise<{ success: boolean }> {
	return request(`/matching/videos/${videoId}/confirm`, { method: 'POST' });
}

export function rejectMatch(videoId: number): Promise<{ success: boolean }> {
	return request(`/matching/videos/${videoId}/reject`, { method: 'POST' });
}

export function assignMatch(videoId: number, cagematchEventId: number): Promise<{ success: boolean; event_name: string }> {
	return request(`/matching/videos/${videoId}/assign/${cagematchEventId}`, { method: 'POST' });
}

export function rematchVideo(videoId: number): Promise<{ success: boolean; status: string; event_name: string | null; score: number | null }> {
	return request(`/matching/videos/${videoId}/rematch`, { method: 'POST' });
}

export function bulkConfirm(videoIds: number[]): Promise<{ confirmed: number; total: number }> {
	return request('/matching/videos/bulk-confirm', {
		method: 'POST',
		body: JSON.stringify({ video_ids: videoIds }),
	});
}

export function bulkReject(videoIds: number[]): Promise<{ rejected: number; total: number }> {
	return request('/matching/videos/bulk-reject', {
		method: 'POST',
		body: JSON.stringify({ video_ids: videoIds }),
	});
}

export interface EventSearchResult {
	id: number;
	cagematch_event_id: number;
	name: string;
	date: string | null;
	location: string | null;
	rating: number | null;
}

export function searchEvents(query: string): Promise<EventSearchResult[]> {
	return request(`/matching/events/search?q=${encodeURIComponent(query)}`);
}

// Player
export function getPlayerInfo(videoId: number): Promise<PlayerInfo> {
	return request(`/player/${videoId}/info`);
}

// Chapters
export function getChapters(videoId: number): Promise<Chapter[]> {
	return request(`/player/${videoId}/chapters`);
}

export function createChapter(videoId: number, data: { title: string; start_ticks: number; match_id?: number | null }): Promise<Chapter> {
	return request(`/player/${videoId}/chapters`, {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function updateChapter(videoId: number, chapterId: number, data: { title?: string; start_ticks?: number; match_id?: number | null }): Promise<Chapter> {
	return request(`/player/${videoId}/chapters/${chapterId}`, {
		method: 'PUT',
		body: JSON.stringify(data)
	});
}

export function deleteChapter(videoId: number, chapterId: number): Promise<void> {
	return request(`/player/${videoId}/chapters/${chapterId}`, {
		method: 'DELETE'
	});
}

// Playback reporting
export function reportPlaybackStart(videoId: number, data: { position_ticks: number; play_session_id: string }): Promise<void> {
	return request(`/player/${videoId}/playback/start`, {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function reportPlaybackProgress(videoId: number, data: { position_ticks: number; is_paused: boolean; play_session_id: string }): Promise<void> {
	return request(`/player/${videoId}/playback/progress`, {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

export function reportPlaybackStopped(videoId: number, data: { position_ticks: number; play_session_id: string }): Promise<void> {
	return request(`/player/${videoId}/playback/stopped`, {
		method: 'POST',
		body: JSON.stringify(data)
	});
}

// Wrestlers
export function getWrestler(wrestlerId: number): Promise<WrestlerProfile> {
	return request(`/wrestlers/${wrestlerId}`);
}

export function getWrestlerMatches(wrestlerId: number, limit = 50, offset = 0): Promise<WrestlerMatchHistory> {
	return request(`/wrestlers/${wrestlerId}/matches?limit=${limit}&offset=${offset}`);
}

// Search
export function globalSearch(query: string): Promise<SearchResults> {
	return request(`/search?q=${encodeURIComponent(query)}`);
}

// Admin auth
export interface AdminStatus {
	required: boolean;
	authenticated: boolean;
}

export function getAdminStatus(): Promise<AdminStatus> {
	return request('/admin/status');
}

export function adminLogin(password: string): Promise<{ success: boolean }> {
	return request('/admin/login', {
		method: 'POST',
		body: JSON.stringify({ password })
	});
}

export function adminLogout(): Promise<{ success: boolean }> {
	return request('/admin/logout', { method: 'POST' });
}
