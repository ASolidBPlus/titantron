import { describe, it, expect } from 'vitest';
import { ratingColor } from './rating';

describe('ratingColor', () => {
	it('returns dark green for 9+', () => {
		expect(ratingColor(9)).toBe('#1a9a32');
		expect(ratingColor(10)).toBe('#1a9a32');
	});

	it('returns green for 8-8.99', () => {
		expect(ratingColor(8)).toBe('#2eab3f');
		expect(ratingColor(8.5)).toBe('#2eab3f');
	});

	it('returns yellow-green for 7-7.99', () => {
		expect(ratingColor(7)).toBe('#6dbf28');
	});

	it('returns yellow for 6-6.99', () => {
		expect(ratingColor(6)).toBe('#b5c410');
	});

	it('returns orange for 5-5.99', () => {
		expect(ratingColor(5)).toBe('#d4a017');
	});

	it('returns dark orange for 4-4.99', () => {
		expect(ratingColor(4)).toBe('#d97b0e');
	});

	it('returns red-orange for 3-3.99', () => {
		expect(ratingColor(3)).toBe('#cf5210');
	});

	it('returns red for below 3', () => {
		expect(ratingColor(2)).toBe('#c42b16');
		expect(ratingColor(0)).toBe('#c42b16');
	});
});
