import { getToken } from './researchApi';

// Use environment variable if set, otherwise fallback to relative path for reverse proxy setups
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api/v1';

export interface ProviderInfo {
  id: string;
  name: string;
  description: string;
  capabilities: string[];
  status: string;
  apiKeyInput?: string;
}

export interface LLMSettings {
  active_provider: string;
  providers: ProviderInfo[];
}

export const settingsApi = {
  getLLMSettings: async (): Promise<LLMSettings> => {
    const token = await getToken();
    const response = await fetch(`${API_BASE_URL}/settings/llm`, {
      method: 'GET',
      cache: 'no-store',
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok) {
      throw new Error('Failed to fetch LLM settings');
    }
    return response.json();
  },

  updateLLMProvider: async (providerId: string, apiKey?: string): Promise<{ status: string; active_provider: string }> => {
    const token = await getToken();
    const response = await fetch(`${API_BASE_URL}/settings/llm`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ provider_id: providerId, api_key: apiKey }),
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.detail || 'Failed to update LLM provider');
    }
    return response.json();
  },
};
