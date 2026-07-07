import { apiClient } from './client';
import type { Paginated, TrainingJob, ComputeType, Framework } from '../types/platform';

export interface SubmitJobPayload {
  name: string;
  computeType: ComputeType;
  framework: Framework;
  entryPointScript: string;
  s3InputPath: string;
  s3OutputPath: string;
  instanceType: string;
  instanceCount: number;
  volumeSizeGb: number;
  hyperparameters: Record<string, string>;
  snowflakeDatabase?: string;
  snowflakeSchema?: string;
  snowflakeTable?: string;
  snowflakeWarehouse?: string;
  snowflakeSql?: string;
  driverMemory?: string;
  executorMemory?: string;
  maxExecutors?: number;
}

export interface ListJobsParams {
  page?: number;
  pageSize?: number;
  status?: string;
  framework?: string;
  computeType?: string;
  tenantId?: string;
}

export const jobsApi = {
  async list(params: ListJobsParams = {}): Promise<Paginated<TrainingJob>> {
    const { data } = await apiClient.get<Paginated<TrainingJob>>('/jobs', { params });
    return data;
  },
  async get(id: string): Promise<TrainingJob> {
    const { data } = await apiClient.get<TrainingJob>(`/jobs/${id}`);
    return data;
  },
  async submit(payload: SubmitJobPayload): Promise<TrainingJob> {
    const { data } = await apiClient.post<TrainingJob>('/jobs', payload);
    return data;
  },
  async cancel(id: string): Promise<TrainingJob> {
    const { data } = await apiClient.post<TrainingJob>(`/jobs/${id}/cancel`);
    return data;
  },
  async logs(id: string): Promise<{ logStreamUrl: string }> {
    const { data } = await apiClient.get<{ logStreamUrl: string }>(`/jobs/${id}/logs`);
    return data;
  },
};
