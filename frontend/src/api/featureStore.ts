import { apiClient } from './client';
import type { FeatureDefinition, FeatureView, FeatureViewPreview, Paginated } from '../types/platform';

export interface CreateFeatureViewPayload {
  name: string;
  description?: string;
  entityColumn: string;
  features: FeatureDefinition[];
  sourceTable: string;
  experimentId?: string;
}

export interface ListFeatureViewsParams {
  page?: number;
  pageSize?: number;
}

export const featureStoreApi = {
  async list(params: ListFeatureViewsParams = {}): Promise<Paginated<FeatureView>> {
    const { data } = await apiClient.get<Paginated<FeatureView>>('/feature-store/views', { params });
    return data;
  },
  async get(featureViewId: string): Promise<FeatureView> {
    const { data } = await apiClient.get<FeatureView>(`/feature-store/views/${featureViewId}`);
    return data;
  },
  async create(payload: CreateFeatureViewPayload): Promise<FeatureView> {
    const { data } = await apiClient.post<FeatureView>('/feature-store/views', payload);
    return data;
  },
  async preview(featureViewId: string): Promise<FeatureViewPreview> {
    const { data } = await apiClient.get<FeatureViewPreview>(`/feature-store/views/${featureViewId}/preview`);
    return data;
  },
  async materialize(featureViewId: string): Promise<FeatureView> {
    const { data } = await apiClient.post<FeatureView>(`/feature-store/views/${featureViewId}/materialize`);
    return data;
  },
};
