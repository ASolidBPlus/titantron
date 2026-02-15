import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch }) => {
	try {
		const res = await fetch('/api/v1/auth/status');
		const status = await res.json();
		if (status.connected) throw redirect(302, '/browse');
	} catch (e) {
		// Re-throw redirects
		if (e && typeof e === 'object' && 'status' in e && (e as any).status === 302) throw e;
		// If backend unreachable, show welcome page
	}
	return { connected: false };
};
