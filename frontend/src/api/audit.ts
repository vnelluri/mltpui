import { apiClient } from './client';
import type { Paginated, AuditEvent } from '../types/platform';

export interface ListAuditParams {
  page?: number;
  pageSize?: number;
  userId?: string;
  resourceType?: string;
  action?: string;
  startDate?: string;
  endDate?: string;
}

export const auditApi = {
  async list(params: ListAuditParams = {}): Promise<Paginated<AuditEvent>> {
    const { data } = await apiClient.get<Paginated<AuditEvent>>('/audit/events', { params });
    return data;
  },
};
