import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Import after mocking
const { getAdminStatus, getPromotions } = await import('./client');

describe('API client', () => {
	beforeEach(() => {
		mockFetch.mockReset();
	});

	it('makes GET requests to the correct path', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve({ required: false, authenticated: false })
		});

		await getAdminStatus();

		expect(mockFetch).toHaveBeenCalledWith(
			'/api/v1/admin/status',
			expect.objectContaining({
				credentials: 'include',
				headers: expect.objectContaining({
					'Content-Type': 'application/json'
				})
			})
		);
	});

	it('throws ApiError on non-ok response', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 404,
			text: () => Promise.resolve('Not Found')
		});

		await expect(getAdminStatus()).rejects.toThrow('Not Found');
	});

	it('parses JSON response correctly', async () => {
		const promotions = [{ id: 1, name: 'WWE', abbreviation: 'WWE' }];
		mockFetch.mockResolvedValueOnce({
			ok: true,
			json: () => Promise.resolve(promotions)
		});

		const result = await getPromotions();
		expect(result).toEqual(promotions);
	});
});
