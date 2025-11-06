// Centralized API base handling used across the app
const API_BASE ="https://railway-production-f8eb.up.railway.app";
export const apiUrl = (path) => `${API_BASE}${path}`;
export const eventSourceUrl = (path) => `${API_BASE}${path}`;
export const reportDownloadUrl = (dateStr) => {
	const d = dateStr || new Date().toISOString().slice(0,10);
	return `${API_BASE}/api/report/download?date=${encodeURIComponent(d)}`;
};
