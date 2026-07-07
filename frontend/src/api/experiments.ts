import { apiClient } from './client';
import type { Paginated, Experiment, ExperimentRun } from '../types/platform';

export interface CreateExperimentPayload {
  name: string;
  description: string;
  tags?: Record<string, string>;
}

export interface CreateRunPayload {
  jobId: string;
  params?: Record<string, string | number>;
  metrics?: Record<string, number>;
  tags?: Record<string, string>;
}

export interface ListParams {
  page?: number;
  pageSize?: number;
}

export const experimentsApi = {
  async list(params: ListParams = {}): Promise<Paginated<Experiment>> {
    const { data } = await apiClient.get<Paginated<Experiment>>('/experiments', { params });
    return data;
  },
  async get(id: string): Promise<Experiment> {
    const { data } = await apiClient.get<Experiment>(`/experiments/${id}`);
    return data;
  },
  async create(payload: CreateExperimentPayload): Promise<Experiment> {
    const { data } = await apiClient.post<Experiment>('/experiments', payload);
    return data;
  },
  async listRuns(id: string, params: ListParams = {}): Promise<Paginated<ExperimentRun>> {
    const { data } = await apiClient.get<Paginated<ExperimentRun>>(`/experiments/${id}/runs`, { params });
    return data;
  },
  async createRun(id: string, payload: CreateRunPayload): Promise<ExperimentRun> {
    const { data } = await apiClient.post<ExperimentRun>(`/experiments/${id}/runs`, payload);
    return data;
  },
  async getRun(id: string, runId: string): Promise<ExperimentRun> {
    const { data } = await apiClient.get<ExperimentRun>(`/experiments/${id}/runs/${runId}`);
    return data;
  },
  async setMetrics(id: string, runId: string, metrics: Record<string, number>): Promise<ExperimentRun> {
    const { data } = await apiClient.put<ExperimentRun>(`/experiments/${id}/runs/${runId}/metrics`, { metrics });
    return data;
  },
  async setParams(id: string, runId: string, params: Record<string, string | number>): Promise<ExperimentRun> {
    const { data } = await apiClient.put<ExperimentRun>(`/experiments/${id}/runs/${runId}/params`, { params });
    return data;
  },
  async setTags(id: string, runId: string, tags: Record<string, string>): Promise<ExperimentRun> {
    const { data } = await apiClient.put<ExperimentRun>(`/experiments/${id}/runs/${runId}/tags`, { tags });
    return data;
  },
};
