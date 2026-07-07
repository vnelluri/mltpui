import { apiClient } from './client';
import type { Paginated, Tenant, TenantMetrics, Framework } from '../types/platform';

export interface CreateTenantPayload {
  name: string;
  computeQuotaVcpuHours: number;
  allowedFrameworks: Framework[];
  s3BucketName?: string;
  emrApplicationId?: string;
  sagemakerDomainId?: string;
}

export interface UpdateTenantPayload {
  name?: string;
  computeQuotaVcpuHours?: number;
  allowedFrameworks?: Framework[];
  emrApplicationId?: string;
  sagemakerDomainId?: string;
  executionRoleArn?: string;
}

export interface ListTenantsParams {
  page?: number;
  pageSize?: number;
  status?: string;
}

export const tenantsApi = {
  async list(params: ListTenantsParams = {}): Promise<Paginated<Tenant>> {
    const { data } = await apiClient.get<Paginated<Tenant>>('/tenants', { params });
    return data;
  },
  async get(id: string): Promise<Tenant> {
    const { data } = await apiClient.get<Tenant>(`/tenants/${id}`);
    return data;
  },
  async create(payload: CreateTenantPayload): Promise<Tenant> {
    const { data } = await apiClient.post<Tenant>('/tenants', payload);
    return data;
  },
  async update(id: string, payload: UpdateTenantPayload): Promise<Tenant> {
    const { data } = await apiClient.put<Tenant>(`/tenants/${id}`, payload);
    return data;
  },
  async suspend(id: string): Promise<Tenant> {
    const { data } = await apiClient.post<Tenant>(`/tenants/${id}/suspend`);
    return data;
  },
  async reactivate(id: string): Promise<Tenant> {
    const { data } = await apiClient.post<Tenant>(`/tenants/${id}/reactivate`);
    return data;
  },
  async metrics(id: string): Promise<TenantMetrics> {
    const { data } = await apiClient.get<TenantMetrics>(`/tenants/${id}/metrics`);
    return data;
  },
};
