/**
 * Returns a CSS color for a rating value (0-10 scale), matching Cagematch's
 * gradient from red (low) through yellow (mid) to green (high).
 */
export function ratingColor(rating: number): string {
	if (rating >= 9) return '#1a9a32';
	if (rating >= 8) return '#2eab3f';
	if (rating >= 7) return '#6dbf28';
	if (rating >= 6) return '#b5c410';
	if (rating >= 5) return '#d4a017';
	if (rating >= 4) return '#d97b0e';
	if (rating >= 3) return '#cf5210';
	return '#c42b16';
}
