import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

const homeApiClient = axios.create({
  baseURL: `${BASE_URL}/home`,  
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

homeApiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('Home API Error:', error);
    return Promise.reject(error);
  }
);

const homeAPI = {
  testConnection: () => homeApiClient.get('/test'),
  getSystemInfo: () => homeApiClient.get('/system-info'),
  getFeatures: () => homeApiClient.get('/features'),
  getTestimonials: () => homeApiClient.get('/testimonials'),
  getStats: () => homeApiClient.get('/stats'),
  getProcessSteps: () => homeApiClient.get('/process-steps'),
  getTechnologies: () => homeApiClient.get('/technologies'),
  getFAQs: () => homeApiClient.get('/faqs'),
  getHealth: () => homeApiClient.get('/health'),
  getProjectInfo: () => homeApiClient.get('/project-info'),
  getDatabaseStats: () => homeApiClient.get('/database-stats'),
  submitContact: (data) => homeApiClient.post('/contact', data),
  subscribeNewsletter: (email) => homeApiClient.post('/newsletter', { email }),
  requestDemo: (data) => homeApiClient.post('/demo-request', data),
};

export default homeAPI;