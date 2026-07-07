import { apiClient } from './client';
import type { Paginated, GovernanceReview, ReviewDecision } from '../types/platform';

export interface CreateReviewPayload {
  modelId: string;
  modelName?: string;
  modelVersion?: number;
  tenantId?: string;
  comments?: string;
}

export interface SubmitDecisionPayload {
  decision: Exclude<ReviewDecision, 'pending'>;
  comments: string;
  conditions: string;
}

export interface ListReviewsParams {
  page?: number;
  pageSize?: number;
  decision?: string;
}

export const governanceApi = {
  async list(params: ListReviewsParams = {}): Promise<Paginated<GovernanceReview>> {
    const { data } = await apiClient.get<Paginated<GovernanceReview>>('/governance/reviews', { params });
    return data;
  },
  async get(id: string): Promise<GovernanceReview> {
    const { data } = await apiClient.get<GovernanceReview>(`/governance/reviews/${id}`);
    return data;
  },
  async create(payload: CreateReviewPayload): Promise<GovernanceReview> {
    const { data } = await apiClient.post<GovernanceReview>('/governance/reviews', payload);
    return data;
  },
  async decide(id: string, payload: SubmitDecisionPayload): Promise<GovernanceReview> {
    const { data } = await apiClient.put<GovernanceReview>(`/governance/reviews/${id}`, payload);
    return data;
  },
  async exportPackage(modelId: string, version: number): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get<Record<string, unknown>>(
      `/governance/export/${encodeURIComponent(modelId)}/${version}`,
    );
    return data;
  },
};
