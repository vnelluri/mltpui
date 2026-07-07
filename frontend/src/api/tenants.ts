import { apiClient } from './client';
import type { Paginated, Tenant, TenantMetrics, Framework } from '../types/platform';

export interface CreateTenantPayload {
  /** Key field, chosen by the admin: the slug that appears in the AD group
   * names (myapp-{tenantId}-{role}) and S3 prefixes. Lowercase slug. */
  tenantId: string;
  /** Human display name this tenantId maps to. */
  name: string;
  computeQuotaVcpuHours: number;
  allowedFrameworks: Framework[];
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
