import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

const api = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

const votingSessions = new Map();

api.interceptors.request.use(
  (config) => {
    const isLoginEndpoint = /\/auth\/login|\/admin\/auth\/login|\/register|\/auth\/admin\/login/.test(config.url);
    if (!isLoginEndpoint) {
      const adminToken = localStorage.getItem('adminToken');
      const voterToken = localStorage.getItem('authToken');
      if (adminToken) config.headers.Authorization = `Bearer ${adminToken}`;
      else if (voterToken) config.headers.Authorization = `Bearer ${voterToken}`;
    }
    if (config.data instanceof FormData) delete config.headers['Content-Type'];
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('authToken');
      localStorage.removeItem('voterData');
      localStorage.removeItem('isAuthenticated');
      localStorage.removeItem('adminToken');
      localStorage.removeItem('adminData');
      localStorage.removeItem('isAdminAuthenticated');
      const path = window.location.pathname;
      if (path.includes('/admin')) window.location.href = '/admin/login';
      else if (!path.includes('/login')) window.location.href = '/login';
    }
    console.error('API Error:', {
      url: error.config?.url,
      status: error.response?.status,
      message: error.response?.data?.message || error.message,
    });
    return Promise.reject(error);
  }
);

const getAuthHeader = () => {
  const adminToken = localStorage.getItem('adminToken');
  const voterToken = localStorage.getItem('authToken');
  if (adminToken) return { Authorization: `Bearer ${adminToken}` };
  if (voterToken) return { Authorization: `Bearer ${voterToken}` };
  return {};
};

const votingSessionManager = {
  storeSession: (electionId, sessionData) => {
    const enhanced = {
      ...sessionData,
      created_at: Date.now(),
      expires_at: Date.now() + 30 * 60 * 1000,
    };
    localStorage.setItem(`voting_session_${electionId}`, JSON.stringify(enhanced));
    votingSessions.set(electionId, enhanced);
    return enhanced;
  },
  getSession: (electionId) => {
    let session = votingSessions.get(electionId);
    if (!session) {
      const stored = localStorage.getItem(`voting_session_${electionId}`);
      if (stored) session = JSON.parse(stored);
      if (session) votingSessions.set(electionId, session);
    }
    if (!session) return null;
    if (Date.now() > session.expires_at) {
      votingSessionManager.clearSession(electionId);
      return null;
    }
    return session;
  },
  clearSession: (electionId) => {
    votingSessions.delete(electionId);
    localStorage.removeItem(`voting_session_${electionId}`);
    localStorage.removeItem(`voted_${electionId}`);
  },
  refreshSession: (electionId) => {
    const session = votingSessionManager.getSession(electionId);
    if (session) {
      session.expires_at = Date.now() + 30 * 60 * 1000;
      localStorage.setItem(`voting_session_${electionId}`, JSON.stringify(session));
      votingSessions.set(electionId, session);
      return true;
    }
    return false;
  },
};


export const voterAPI = {
  // Auth
  verifyCredentials: (creds) => api.post('/auth/login', creds).then(r => r.data),
  verifyFace: (data) => api.post('/auth/verify-face', data).then(r => r.data),
  checkExistingVoter: (data) => api.post('/register/check-existing-voter', data).then(r => r.data),
  registerFaceHybrid: (voterId, imageData) => api.post(`/register/register-face/${voterId}`, { image_data: imageData }).then(r => r.data),
  verifyFaceHybrid: async (data) => {
    try {
      const response = await api.post('/auth/verify-face-hybrid', data);
      return response.data;
    } catch (error) {
      return { success: false, message: error.response?.data?.message || 'Face verification failed' };
    }
  },
  checkFaceDuplicate: (voterId) => api.post(`/register/check-face-duplicate/${voterId}`).then(r => r.data),
  registerFace: (data) => api.post(`/register/register-face/${data.voter_id}`, { image_data: data.image_data }).then(r => r.data),
  completeRegistration: (voterId) => api.post(`/register/complete-registration/${voterId}`).then(r => r.data),
  directRegisterFace: (voterId, imageData) => api.post(`/register/register-face/${voterId}`, { image_data: imageData }, { headers: getAuthHeader(), timeout: 60000 }).then(r => r.data),
  getFaceSystemStats: () => api.get('/register/face/system-stats').then(r => r.data),
  findSimilarFaces: (imageData) => api.post('/register/face/find-similar', { image_data: imageData }).then(r => r.data),
  logout: () => api.post('/auth/logout').then(r => { localStorage.removeItem('authToken'); localStorage.removeItem('voterData'); localStorage.removeItem('isAuthenticated'); return r.data; }),
  checkAuth: () => api.get('/auth/check-auth').then(r => r.data),
  verifyToken: () => api.get('/auth/verify-token').then(r => r.data),

  // Elections & Voting
  getUpcomingElections: () => api.get('/election/elections/upcoming').then(r => r.data),
  getCompletedElections: () => api.get('/election/elections/completed').then(r => r.data),
  getElectionCandidates: (electionId) => api.get(`/election/elections/${electionId}/candidates`).then(r => r.data),
  castVote: async (electionId, candidateId) => {
    const session = votingSessionManager.getSession(electionId);
    if (!session) throw new Error('No active voting session');
    const response = await api.post(`/election/elections/${electionId}/vote`, { candidate_id: candidateId });
    if (response.data.success) {
      votingSessionManager.clearSession(electionId);
      localStorage.setItem(`voted_${electionId}`, 'true');
    }
    return response.data;
  },
  startVotingSession: async (electionId) => {
    votingSessionManager.clearSession(electionId);
    const response = await api.post(`/election/elections/${electionId}/start-voting`);
    if (response.data.success) {
      votingSessionManager.storeSession(electionId, {
        sessionId: response.data.session_id,
        expires: response.data.session_expires,
        election: response.data.election,
        candidates: response.data.candidates,
      });
    }
    return response.data;
  },
  verifyVotingSession: (electionId) => {
    const session = votingSessionManager.getSession(electionId);
    if (!session) throw new Error('No active voting session');
    return { success: true, session_valid: true, session_data: session, time_remaining: Math.max(0, session.expires_at - Date.now()) };
  },
  getCachedVotingSession: (electionId) => votingSessionManager.getSession(electionId),
  clearVotingSession: (electionId) => votingSessionManager.clearSession(electionId),
  refreshVotingSession: (electionId) => votingSessionManager.refreshSession(electionId),
  hasVoted: (electionId) => localStorage.getItem(`voted_${electionId}`) === 'true',
  isVotingSessionActive: (electionId) => !!votingSessionManager.getSession(electionId),
  getVotingSessionTimeRemaining: (electionId) => {
    const session = votingSessionManager.getSession(electionId);
    return session ? Math.max(0, session.expires_at - Date.now()) : 0;
  },
  endVotingSession: async (electionId) => {
    const response = await api.post(`/election/elections/${electionId}/end-session`);
    votingSessionManager.clearSession(electionId);
    return response.data;
  },
  getVotingSessionStatus: async (electionId) => {
    const session = votingSessionManager.getSession(electionId);
    if (session) {
      return { success: true, session_active: true, session_data: session, time_remaining: Math.max(0, session.expires_at - Date.now()) };
    }
    const response = await api.get(`/election/elections/${electionId}/session-status`);
    return response.data;
  },

  // Results
  getElectionResults: (electionId) => api.get(`/election/elections/${electionId}/results`).then(r => r.data),
  getElectionResultsDashboard: (electionId) => api.get(`/dashboard/elections/${electionId}/results`).then(r => r.data),
  checkResultsAvailability: (electionId) => api.get(`/election/elections/${electionId}/results/check`).then(r => r.data),
  getElectionDetailsForResults: (electionId) => api.get(`/election/elections/${electionId}`).then(r => r.data),
  getElectionResultsSummary: (electionId) => api.get(`/election/elections/${electionId}/results/summary`).then(r => r.data),
  getMyVoteInElection: (electionId) => api.get(`/dashboard/elections/${electionId}/my-vote`).then(r => r.data),

  // Dashboard
  getDashboardData: () => api.get('/dashboard/data').then(r => r.data),
  getEnhancedDashboardData: () => api.get('/dashboard/data/enhanced').then(r => r.data),
  getProfile: () => api.get('/dashboard/profile').then(r => r.data),
  getTrustedDevices: () => api.get('/dashboard/security/devices').then(r => r.data),
  revokeDevice: (deviceId) => api.post('/dashboard/security/devices/revoke', { device_id: deviceId }).then(r => r.data),
  logoutAllSessions: () => api.post('/dashboard/security/sessions/logout-all', {}).then(r => r.data),
  enableTwoFactorAuth: () => api.post('/dashboard/security/two-factor/enable', {}).then(r => r.data),
  disableTwoFactorAuth: () => api.post('/dashboard/security/two-factor/disable', {}).then(r => r.data),
  updateProfile: (profileData) => api.put('/dashboard/profile/update', profileData).then(r => r.data),
  getEnhancedVotingHistory: () => api.get('/dashboard/voting-history/enhanced').then(r => r.data),
  getEnhancedAnalytics: () => api.get('/dashboard/analytics/enhanced').then(r => r.data),
  getEnhancedSecurity: () => api.get('/dashboard/security/enhanced').then(r => r.data),
  generateDigitalID: () => api.get('/dashboard/digital-id/generate').then(r => r.data),
  refreshDashboardData: () => api.post('/dashboard/refresh-data').then(r => r.data),
  exportData: (format) => api.get(`/dashboard/export-data/${format}`).then(r => r.data),
  getNotifications: (limit = 10) => api.get(`/dashboard/notifications?limit=${limit}`).then(r => r.data),
  getAnalytics: () => api.get('/dashboard/analytics').then(r => r.data),
  getLiveElections: () => api.get('/dashboard/elections/live').then(r => r.data),
  getLiveUpdates: () => api.get('/dashboard/live-updates').then(r => r.data),
  getSocketInfo: () => api.get('/dashboard/socket-info').then(r => r.data),
  getDigitalID: () => api.get('/dashboard/digital-id').then(r => r.data),
  downloadVoterSlip: () => api.get('/dashboard/download-voter-slip', { responseType: 'blob' }).then(r => r.data),
  getSecuritySettings: () => api.get('/dashboard/security-settings').then(r => r.data),
  updateSecuritySettings: (settings) => api.post('/dashboard/security-settings', settings).then(r => r.data),
  sendMobileVerificationOTP: () => api.post('/dashboard/mobile-verification', { action: 'send_otp' }).then(r => r.data),
  verifyMobileOTP: (otpCode) => api.post('/dashboard/mobile-verification', { action: 'verify_otp', otp_code: otpCode }).then(r => r.data),
  getVotingHistory: () => api.get('/dashboard/voting-history').then(r => r.data),
  getSystemStats: () => api.get('/system/stats').then(r => r.data),
  debugGetVoters: () => api.get('/auth/debug/voters').then(r => r.data),
  debugCheckAuth: () => api.get('/auth/debug/check-auth').then(r => r.data),
  requestPasswordReset: (emailOrVoterId) => api.post('/auth/password/reset-request', emailOrVoterId).then(r => r.data),
  resetPassword: (resetData) => api.post('/auth/password/reset', resetData).then(r => r.data),

  // Registration
  register: (voterData) => api.post('/register/register', voterData).then(r => r.data),
  sendOTP: (otpData) => api.post('/register/send-otp', otpData).then(r => r.data),
  verifyOTP: (otpData) => api.post('/register/verify-otp', otpData).then(r => r.data),
  sendVerificationOTP: (voterId, data) => api.post(`/register/send-verification-otp/${voterId}`, data).then(r => r.data),
  verifyContact: (voterId, data) => api.post(`/register/verify-contact/${voterId}`, data).then(r => r.data),
  checkVoter: (voterId) => api.get(`/register/check-voter/${voterId}`).then(r => r.data),

  // Utilities
  getSocketConfig: () => ({
    url: window.location.origin, // use same origin; can be overridden if needed
    path: '/socket.io',
    transports: ['websocket', 'polling'],
  }),
  prepareVotingNavigation: (electionId, sessionResponse) => {
    const navData = { electionId, sessionId: sessionResponse.session_id, election: sessionResponse.election, candidates: sessionResponse.candidates, expires: sessionResponse.session_expires, startedAt: new Date().toISOString() };
    localStorage.setItem(`voting_nav_${electionId}`, JSON.stringify(navData));
    sessionStorage.setItem(`voting_nav_${electionId}`, JSON.stringify(navData));
    return navData;
  },
  getVotingNavigationData: (electionId) => {
    const data = sessionStorage.getItem(`voting_nav_${electionId}`) || localStorage.getItem(`voting_nav_${electionId}`);
    return data ? JSON.parse(data) : null;
  },
  clearVotingNavigationData: (electionId) => {
    localStorage.removeItem(`voting_nav_${electionId}`);
    sessionStorage.removeItem(`voting_nav_${electionId}`);
  },
  getVotingPageData: async (electionId) => {
    const cached = votingSessionManager.getSession(electionId);
    if (cached) return { success: true, session_data: cached, election: cached.election, candidates: cached.candidates, from_cache: true };
    return voterAPI.startVotingSession(electionId);
  },
  debugVotingFlow: async (electionId) => {
    const auth = await voterAPI.checkAuth();
    const active = await voterAPI.getUpcomingElections();
    const target = active.elections?.find(e => e.election_id === electionId);
    const session = await voterAPI.startVotingSession(electionId);
    return { success: true, auth, election: target, session };
  },
  isElectionResultsAvailable: async (electionId) => {
    try {
      const res = await voterAPI.checkResultsAvailability(electionId);
      return res;
    } catch {
      return { success: false, available: false, message: 'Unable to check results availability' };
    }
  },
};

// Admin API
export const adminAPI = {
  login: async (credentials) => {
    const loginApi = axios.create({ baseURL: BASE_URL, headers: { 'Content-Type': 'application/json' }, timeout: 30000 });
    const response = await loginApi.post('/auth/admin/login', credentials);
    return response.data;
  },
  verifyToken: () => api.get('/admin/verify-token', { headers: getAuthHeader() }).then(r => r.data),
  logout: () => api.post('/admin/auth/logout').then(r => { localStorage.removeItem('adminToken'); localStorage.removeItem('adminData'); localStorage.removeItem('isAdminAuthenticated'); return r.data; }),
  getElectionResults: (electionId) => api.get(`/admin/elections/${electionId}/results`, { headers: getAuthHeader() }).then(r => r.data),
  publishElectionResults: (electionId) => api.post(`/admin/elections/${electionId}/publish-results`, {}, { headers: getAuthHeader() }).then(r => r.data),
  unpublishElectionResults: (electionId) => api.post(`/admin/elections/${electionId}/unpublish-results`, {}, { headers: getAuthHeader() }).then(r => r.data),
  getElectionResultsAnalytics: (electionId) => api.get(`/admin/elections/${electionId}/results/analytics`, { headers: getAuthHeader() }).then(r => r.data),
  getElectionResultsDashboard: (electionId) => api.get(`/admin/elections/${electionId}/results/dashboard`, { headers: getAuthHeader() }).then(r => r.data),
  getDashboardStats: () => api.get('/admin/dashboard/stats', { headers: getAuthHeader() }).then(r => r.data),
  getSystemStats: () => api.get('/admin/dashboard/stats', { headers: getAuthHeader() }).then(r => r.data),
  getElections: async (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return api.get(`/admin/elections?${query}`, { headers: getAuthHeader() }).then(r => r.data);
  },
  createElection: (formData) => api.post('/admin/elections', formData, { headers: getAuthHeader(), timeout: 60000 }).then(r => r.data),
  updateElection: (electionId, updateData) => api.put(`/admin/elections/${electionId}`, updateData, { headers: getAuthHeader() }).then(r => r.data),
  deleteElection: (electionId) => api.delete(`/admin/elections/${electionId}`, { headers: getAuthHeader() }).then(r => r.data),
  getElectionDetails: (electionId) => api.get(`/admin/elections/${electionId}`, { headers: getAuthHeader() }).then(r => r.data),
  updateElectionStatus: (electionId, statusData) => api.put(`/admin/elections/${electionId}/status`, statusData, { headers: getAuthHeader() }).then(r => r.data),
  getElectionForEdit: (electionId) => api.get(`/admin/elections/${electionId}/edit`, { headers: getAuthHeader() }).then(r => r.data),
  getVoters: async (params = {}) => {
    const query = new URLSearchParams(params).toString();
    try {
      const response = await api.get(`/admin/voters?${query}`, { headers: getAuthHeader() });
      return { success: true, voters: response.data.voters || response.data.data || response.data, pagination: response.data.pagination || { page: params.page || 1, per_page: params.per_page || 10, total: 0, total_pages: 1 } };
    } catch (error) {
      return { success: false, message: error.response?.data?.message || 'Failed to load voters', voters: [], pagination: { page: params.page || 1, per_page: params.per_page || 10, total: 0, total_pages: 1 } };
    }
  },
  getVoterDetails: (voterId) => api.get(`/admin/voters/${voterId}`, { headers: getAuthHeader() }).then(r => r.data).catch(e => ({ success: false, message: e.response?.data?.message || 'Failed to load voter details' })),
  verifyVoter: (voterId, verificationData) => api.post(`/admin/voters/${voterId}/verify`, verificationData, { headers: getAuthHeader() }).then(r => r.data),
  updateVoterStatus: (voterId, statusData) => api.put(`/admin/voters/${voterId}/status`, statusData, { headers: getAuthHeader() }).then(r => r.data),
  deleteVoter: (voterId) => api.delete(`/admin/voters/${voterId}`, { headers: getAuthHeader() }).then(r => r.data),
  getCandidates: async (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return api.get(`/admin/candidates?${query}`, { headers: getAuthHeader() }).then(r => r.data);
  },
  createCandidate: (formData) => api.post('/admin/candidates', formData, { headers: getAuthHeader(), timeout: 60000 }).then(r => r.data),
  updateCandidate: (candidateId, updateData) => api.put(`/admin/candidates/${candidateId}`, updateData, { headers: getAuthHeader() }).then(r => r.data),
  deleteCandidate: (candidateId) => api.delete(`/admin/candidates/${candidateId}`, { headers: getAuthHeader() }).then(r => r.data),
  approveCandidate: (candidateId) => api.put(`/admin/candidates/${candidateId}/approve`, {}, { headers: getAuthHeader() }).then(r => r.data),
  getCandidateDetails: (candidateId) => api.get(`/admin/candidates/${candidateId}`, { headers: getAuthHeader() }).then(r => r.data),
  getCandidateForEdit: (candidateId) => api.get(`/admin/candidates/${candidateId}/edit`, { headers: getAuthHeader() }).then(r => r.data),
  getDashboardReports: () => api.get('/admin/reports/dashboard', { headers: getAuthHeader() }).then(r => r.data),
  getVoterAnalytics: () => api.get('/admin/reports/voter-analytics', { headers: getAuthHeader() }).then(r => r.data),
  getSystemHealth: () => api.get('/admin/reports/system-health', { headers: getAuthHeader() }).then(r => r.data),
  getElectionReport: (electionId) => api.get(`/admin/reports/election/${electionId}`, { headers: getAuthHeader() }).then(r => r.data),
  exportReport: (data) => api.post('/admin/reports/export', data, { headers: getAuthHeader() }).then(r => r.data),
  getAuditLogs: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return api.get(`/admin/audit-logs?${query}`, { headers: getAuthHeader() }).then(r => r.data);
  },
  getSystemSettings: () => api.get('/admin/settings', { headers: getAuthHeader() }).then(r => r.data),
  updateSystemSettings: (settings) => api.put('/admin/settings', settings, { headers: getAuthHeader() }).then(r => r.data),
  broadcastMessage: (messageData) => api.post('/admin/broadcast', messageData, { headers: getAuthHeader() }).then(r => r.data),
  sendBroadcast: (messageData) => api.post('/admin/broadcast', messageData, { headers: getAuthHeader() }).then(r => r.data),
  getConnectedUsers: () => api.get('/admin/connected-users', { headers: getAuthHeader() }).then(r => r.data),
  healthCheck: () => api.get('/admin/health', { headers: getAuthHeader() }).then(r => r.data),
  updateElectionRealTime: (action, electionData) => api.post('/dashboard/admin/update-election', { action, election_data: electionData }, { headers: getAuthHeader() }).then(r => r.data),
  updateVoterRealTime: (action, voterData) => api.post('/dashboard/admin/update-voter', { action, voter_data: voterData }, { headers: getAuthHeader() }).then(r => r.data),
  adminBroadcast: (messageData) => api.post('/dashboard/admin/broadcast', messageData, { headers: getAuthHeader() }).then(r => r.data),
  getConnectedUsersInfo: () => api.get('/dashboard/admin/connected-users', { headers: getAuthHeader() }).then(r => r.data),
};

// Authentication Utilities
export const authUtils = {
  isVoterAuthenticated: () => !!localStorage.getItem('authToken') && !!localStorage.getItem('voterData') && localStorage.getItem('isAuthenticated') === 'true',
  isAdminAuthenticated: () => !!localStorage.getItem('adminToken') && !!localStorage.getItem('adminData') && localStorage.getItem('isAdminAuthenticated') === 'true',
  getCurrentVoter: () => {
    try { return JSON.parse(localStorage.getItem('voterData')); } catch { return null; }
  },
  getCurrentAdmin: () => {
    try { return JSON.parse(localStorage.getItem('adminData')); } catch { return null; }
  },
  getVoterToken: () => localStorage.getItem('authToken'),
  getAdminToken: () => localStorage.getItem('adminToken'),
  setVoterAuthData: (token, voterData) => {
    localStorage.setItem('authToken', token);
    localStorage.setItem('voterData', JSON.stringify(voterData));
    localStorage.setItem('isAuthenticated', 'true');
  },
  setAdminAuthData: (token, adminData) => {
    localStorage.setItem('adminToken', token);
    localStorage.setItem('adminData', JSON.stringify(adminData));
    localStorage.setItem('isAdminAuthenticated', 'true');
  },
  clearVoterAuthData: () => {
    localStorage.removeItem('authToken');
    localStorage.removeItem('voterData');
    localStorage.removeItem('isAuthenticated');
  },
  clearAdminAuthData: () => {
    localStorage.removeItem('adminToken');
    localStorage.removeItem('adminData');
    localStorage.removeItem('isAdminAuthenticated');
  },
  clearAllAuthData: () => {
    authUtils.clearVoterAuthData();
    authUtils.clearAdminAuthData();
  },
  isTokenExpired: (token) => {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp * 1000 < Date.now();
    } catch { return true; }
  },
  voterLogin: (token, voterData) => { authUtils.setVoterAuthData(token, voterData); window.dispatchEvent(new Event('authStateChange')); },
  adminLogin: (token, adminData) => { authUtils.setAdminAuthData(token, adminData); window.dispatchEvent(new Event('authStateChange')); },
  voterLogout: () => { authUtils.clearVoterAuthData(); window.dispatchEvent(new Event('authStateChange')); },
  adminLogout: () => { authUtils.clearAdminAuthData(); window.dispatchEvent(new Event('authStateChange')); },
};

// Error Handler
export const apiErrorHandler = {
  handleError: (error, customMessage = null) => {
    let message = customMessage || 'An unexpected error occurred';
    if (error.response) {
      const serverMsg = error.response.data?.message;
      switch (error.response.status) {
        case 400: message = serverMsg || 'Bad request'; break;
        case 401: message = serverMsg || 'Authentication failed'; authUtils.clearAllAuthData(); break;
        case 403: message = serverMsg || 'Access denied'; break;
        case 404: message = serverMsg || 'Resource not found'; break;
        case 409: message = serverMsg || 'Conflict'; break;
        case 422: message = serverMsg || 'Validation error'; break;
        case 429: message = serverMsg || 'Too many requests'; break;
        case 500: message = serverMsg || 'Server error'; break;
        case 503: message = serverMsg || 'Service unavailable'; break;
        default: message = serverMsg || `Error ${error.response.status}`;
      }
    } else if (error.request) {
      message = 'Network error. Please check your connection.';
    } else {
      message = error.message || message;
    }
    console.error('API Error Details:', { message, originalError: error });
    return message;
  },
  handleVotingError: (error) => {
    const base = apiErrorHandler.handleError(error);
    if (error.response?.status === 400) {
      const msg = error.response.data?.message;
      if (msg?.includes('already voted')) return 'You have already cast your vote.';
      if (msg?.includes('not eligible')) return 'You are not eligible to vote in this election.';
      if (msg?.includes('not active')) return 'This election is not active.';
      if (msg?.includes('voting period')) return 'Voting period has ended.';
      if (msg?.includes('session')) return 'Voting session issue. Please restart.';
    }
    return base;
  },
  handleResultsError: (error) => {
    const base = apiErrorHandler.handleError(error);
    if (error.response?.status === 403 && error.response.data?.message?.includes('not available')) {
      return 'Election results are not available yet.';
    }
    if (error.response?.status === 404) return 'Election results not found.';
    return base;
  },
  handleVoterResultsError: (error) => {
    const message = apiErrorHandler.handleResultsError(error);
    return { message, reason: error.response?.data?.reason || '', resultsNotAvailable: message.includes('not available'), election_id: error.response?.data?.election_id };
  },
  handleAdminResultsError: (error) => {
    const message = apiErrorHandler.handleResultsError(error);
    return { message, action: message.includes('not available') ? 'You may need to publish the results first.' : undefined };
  },
};

// Results Utilities
export const resultsUtils = {
  canVoterViewResults: async (electionId) => {
    try { const res = await voterAPI.getElectionResults(electionId); return res.success; } catch { return false; }
  },
  canAdminViewResults: async (electionId) => {
    try { const res = await adminAPI.getElectionResults(electionId); return res.success; } catch { return false; }
  },
  getResultsAccessInfo: async (electionId, isAdmin = false) => {
    try {
      if (isAdmin) {
        const res = await adminAPI.getElectionResults(electionId);
        return { canView: res.success, accessLevel: 'admin', data: res.results };
      } else {
        const res = await voterAPI.getElectionResults(electionId);
        return { canView: res.success, accessLevel: 'voter', data: res.results, reason: res.access_info?.reason };
      }
    } catch (error) {
      return { canView: false, accessLevel: isAdmin ? 'admin' : 'voter', error: error.message };
    }
  },
  formatResultsForDisplay: (resultsData) => {
    if (!resultsData?.candidates) return null;
    return {
      ...resultsData,
      candidates: resultsData.candidates.map(c => ({
        ...c,
        formattedPercentage: `${c.percentage}%`,
        isWinner: c.rank === 1,
        colorClass: c.rank === 1 ? 'text-success' : c.rank === 2 ? 'text-warning' : c.rank === 3 ? 'text-info' : 'text-muted',
      })),
    };
  },
  generateResultsSummary: (resultsData) => {
    if (!resultsData?.candidates?.length) return 'No results available';
    const winner = resultsData.candidates[0];
    const totalVotes = resultsData.total_votes;
    const turnout = resultsData.voter_turnout || 0;
    return `${winner.full_name} (${winner.party}) wins with ${winner.vote_count} votes (${winner.percentage}%) out of ${totalVotes} total votes. Voter turnout: ${turnout}%.`;
  },
};

// Development logging
if (process.env.NODE_ENV === 'development') {
  api.interceptors.request.use(req => { console.log('API Request:', { url: req.url, method: req.method }); return req; });
  api.interceptors.response.use(res => { console.log('API Response:', { url: res.config.url, status: res.status }); return res; }, err => { console.log('API Error:', { url: err.config?.url, status: err.response?.status, message: err.message }); return Promise.reject(err); });
}

export default api;