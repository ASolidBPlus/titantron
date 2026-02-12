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
