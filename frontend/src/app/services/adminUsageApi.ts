// src/app/services/adminUsageApi.ts

// Use environment variable if set, otherwise fallback to relative path for reverse proxy setups
const BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api/v1';

import { authFetch } from './researchApi';

export interface UsageSummary {
  llm_input_tokens: number;
  llm_output_tokens: number;
  llm_total_tokens: number;
  llm_calls: number;
  serper_requests: number;
  estimated_cost: number;
}

export interface ProviderUsage {
  provider: string;
  logical_calls: number;
  provider_attempts: number;
  successful_attempts: number;
  failed_attempts: number;
  input_tokens: number | null;
  output_tokens: number | null;
  cost: number;
}

export interface StageUsage {
  stage: string;
  logical_llm_calls: number;
  provider_attempts: number;
  successful_attempts: number;
  failed_attempts: number;
  serper_requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
  avg_latency: number;
}

export interface RunUsageItem {
  run_id: string;
  compound_name: string;
  created_at: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_calls: number;
  serper_requests: number;
  cost: number;
}

export interface PaginatedRuns {
  items: RunUsageItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface DetailedRunUsage {
  run_id: string;
  compound_name: string;
  status: string;
  created_at: string;
  architecture_violation: string | null;
  total: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    llm_calls: number;
    serper_requests: number;
    cost: number;
  };
  stages: StageUsage[];
}

export interface ApiCallLog {
  id: string;
  timestamp: string;
  stage: string;
  provider: string;
  model: string;
  operation: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  latency_ms: number;
  status: string;
  cost: number;
  error_message: string | null;
}

export interface PaginatedApiCallLogs {
  items: ApiCallLog[];
  total: number;
  page: number;
  page_size: number;
}

export const adminUsageApi = {
  getSummary: async (timeFilter: string = "28d"): Promise<UsageSummary> => {
    const res = await authFetch(`/admin/usage/summary?time_filter=${timeFilter}`);
    if (!res.ok) throw new Error("Failed to fetch summary");
    return res.json();
  },
  
  getByProvider: async (timeFilter: string = "28d"): Promise<ProviderUsage[]> => {
    const res = await authFetch(`/admin/usage/by-provider?time_filter=${timeFilter}`);
    if (!res.ok) throw new Error("Failed to fetch provider usage");
    return res.json();
  },
  
  getByStage: async (timeFilter: string = "28d"): Promise<StageUsage[]> => {
    const res = await authFetch(`/admin/usage/by-stage?time_filter=${timeFilter}`);
    if (!res.ok) throw new Error("Failed to fetch stage usage");
    return res.json();
  },
  
  getByRun: async (timeFilter: string = "28d", page: number = 1, pageSize: number = 25): Promise<PaginatedRuns> => {
    const res = await authFetch(`/admin/usage/by-run?time_filter=${timeFilter}&page=${page}&page_size=${pageSize}`);
    if (!res.ok) throw new Error("Failed to fetch run usage");
    return res.json();
  },
  
  getRunDetail: async (runId: string): Promise<DetailedRunUsage> => {
    const res = await authFetch(`/admin/usage/run/${runId}`);
    if (!res.ok) throw new Error("Failed to fetch run details");
    return res.json();
  },
  
  getApiCallLogs: async (timeFilter: string = "28d", page: number = 1, pageSize: number = 25, runId?: string): Promise<PaginatedApiCallLogs> => {
    let url = `/admin/usage/calls?time_filter=${timeFilter}&page=${page}&page_size=${pageSize}`;
    if (runId) url += `&run_id=${runId}`;
    const res = await authFetch(url);
    if (!res.ok) throw new Error("Failed to fetch API call logs");
    return res.json();
  },
  
  resetToday: async (): Promise<{message: string}> => {
    const res = await authFetch(`/admin/usage/reset-today`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to reset today's usage");
    return res.json();
  }
};
