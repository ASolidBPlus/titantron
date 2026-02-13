export interface Promotion {
	id: number;
	cagematch_id: number;
	name: string;
	abbreviation: string;
	image_url: string | null;
	event_count: number;
	video_count: number;
}

export interface Event {
	id: number;
	cagematch_event_id: number;
	name: string;
	date: string;
	promotion_id: number;
	event_type: string | null;
	location: string | null;
	arena: string | null;
	rating: number | null;
	votes: number | null;
	video_count?: number;
}

export interface VideoItem {
	id: number;
	jellyfin_item_id: string;
	title: string;
	filename: string | null;
	extracted_date: string | null;
	match_status: string;
	match_confidence: number | null;
	matched_event_id: number | null;
	matched_event_name: string | null;
	poster_url: string | null;
}

export interface MatchParticipant {
	id: number;
	name: string;
	cagematch_wrestler_id: number | null;
	is_linked: boolean;
	side: number | null;
	team_name: string | null;
	is_winner: boolean;
	role: string;
}

export interface WrestlingMatch {
	id: number;
	match_number: number;
	match_type: string | null;
	title_name: string | null;
	result: string | null;
	rating: number | null;
	votes: number | null;
	duration: string | null;
	participants: MatchParticipant[];
}

export interface EventDetail extends Event {
	promotion: { id: number; cagematch_id: number; name: string; abbreviation: string } | null;
	matches: WrestlingMatch[];
	videos: {
		id: number;
		jellyfin_item_id: string;
		title: string;
		match_status: string;
		match_confidence: number | null;
		poster_url: string | null;
	}[];
}

export interface MatchCandidate {
	cagematch_event_id: number;
	name: string;
	date: string;
	location: string | null;
	rating: number | null;
	votes: number | null;
	score: number;
}

export interface LogEntry {
	time: string;
	message: string;
}

export interface MatchStatus {
	is_running: boolean;
	library_id: number | null;
	progress: number | null;
	total: number | null;
	message: string | null;
	results: {
		total: number;
		auto_matched: number;
		suggested: number;
		unmatched: number;
	} | null;
	log: LogEntry[];
}

export interface EventComment {
	username: string;
	date: string | null;
	rating: number | null;
	text: string;
}

export interface WrestlerProfile {
	id: number;
	cagematch_wrestler_id: number | null;
	name: string;
	image_url: string | null;
	is_linked: boolean;
	birth_date: string | null;
	birth_place: string | null;
	height: string | null;
	weight: string | null;
	style: string | null;
	debut: string | null;
	roles: string | null;
	nicknames: string | null;
	signature_moves: string | null;
	trainers: string | null;
	alter_egos: string | null;
	rating: number | null;
	votes: number | null;
	match_count: number;
}

export interface WrestlerMatchEntry {
	match_id: number;
	match_number: number;
	match_type: string | null;
	title_name: string | null;
	result: string | null;
	rating: number | null;
	votes: number | null;
	duration: string | null;
	is_winner: boolean;
	role: string;
	event: {
		id: number;
		cagematch_event_id: number;
		name: string;
		date: string;
		promotion_id: number;
	};
	participants: MatchParticipant[];
}

export interface WrestlerMatchHistory {
	total: number;
	matches: WrestlerMatchEntry[];
}

export interface SearchResults {
	events: {
		id: number;
		cagematch_event_id: number;
		name: string;
		date: string | null;
		location: string | null;
		rating: number | null;
		promotion_id: number;
	}[];
	wrestlers: {
		id: number;
		cagematch_wrestler_id: number | null;
		name: string;
		image_url: string | null;
		is_linked: boolean;
		match_count: number;
	}[];
}

export interface TrickplayInfo {
	resolution: number;
	width: number;
	height: number;
	tile_width: number;
	tile_height: number;
	thumbnail_count: number;
	interval: number;
	base_url: string;
}

export interface Chapter {
	id: number;
	video_item_id: number;
	match_id: number | null;
	title: string;
	start_ticks: number;
	end_ticks: number | null;
}

export interface PlayerInfo {
	video: {
		id: number;
		jellyfin_item_id: string;
		title: string;
		duration_ticks: number;
		media_source_id: string;
	};
	stream: {
		url: string;
		is_hls: boolean;
		play_session_id: string;
		api_key: string;
		server_url: string;
	};
	trickplay: TrickplayInfo | null;
	chapters: Chapter[];
	event: {
		id: number;
		cagematch_event_id: number;
		name: string;
		date: string;
		matches: WrestlingMatch[];
	} | null;
}
