export interface Promotion {
	id: number;
	cagematch_id: number;
	name: string;
	abbreviation: string;
	image_url: string | null;
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
}
