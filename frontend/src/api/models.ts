import { apiClient } from './client';
import type { Paginated, ModelVersion, ModelCard, ModelStage, Framework } from '../types/platform';

export interface RegisterModelPayload {
  name: string;
  runId: string;
  framework: Framework;
  description: string;
  artifactUri?: string;
  hasExplainer?: boolean;
}

export interface ListModelsParams {
  page?: number;
  pageSize?: number;
  stage?: string;
  tenantId?: string;
}

export const modelsApi = {
  async list(params: ListModelsParams = {}): Promise<Paginated<ModelVersion>> {
    const { data } = await apiClient.get<Paginated<ModelVersion>>('/models', { params });
    return data;
  },
  async register(payload: RegisterModelPayload): Promise<ModelVersion> {
    const { data } = await apiClient.post<ModelVersion>('/models', payload);
    return data;
  },
  async listVersions(name: string): Promise<Paginated<ModelVersion>> {
    const { data } = await apiClient.get<Paginated<ModelVersion>>(`/models/${encodeURIComponent(name)}/versions`);
    return data;
  },
  async getVersion(name: string, version: number): Promise<ModelVersion> {
    const { data } = await apiClient.get<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}`,
    );
    return data;
  },
  async setStage(name: string, version: number, stage: ModelStage): Promise<ModelVersion> {
    const { data } = await apiClient.put<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}/stage`,
      { stage },
    );
    return data;
  },
  async getCard(name: string, version: number): Promise<ModelCard> {
    const { data } = await apiClient.get<ModelCard>(
      `/models/${encodeURIComponent(name)}/versions/${version}/card`,
    );
    return data;
  },
  async archive(name: string, version: number): Promise<ModelVersion> {
    const { data } = await apiClient.post<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}/archive`,
    );
    return data;
  },
};
