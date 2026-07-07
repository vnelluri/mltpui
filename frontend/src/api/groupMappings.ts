import { apiClient } from './client';
import type { Paginated, GroupMapping, Role } from '../types/platform';

export interface CreateGroupMappingPayload {
  groupId: string;
  role: Role;
  tenantId: string;
  description: string;
}

export interface UpdateGroupMappingPayload {
  role?: Role;
  tenantId?: string;
  description?: string;
}

export const groupMappingsApi = {
  async list(params: { page?: number; pageSize?: number } = {}): Promise<Paginated<GroupMapping>> {
    const { data } = await apiClient.get<Paginated<GroupMapping>>('/group-mappings', { params });
    return data;
  },
  async get(groupId: string): Promise<GroupMapping> {
    const { data } = await apiClient.get<GroupMapping>(`/group-mappings/${groupId}`);
    return data;
  },
  async create(payload: CreateGroupMappingPayload): Promise<GroupMapping> {
    const { data } = await apiClient.post<GroupMapping>('/group-mappings', payload);
    return data;
  },
  async update(groupId: string, payload: UpdateGroupMappingPayload): Promise<GroupMapping> {
    const { data } = await apiClient.put<GroupMapping>(`/group-mappings/${groupId}`, payload);
    return data;
  },
  async remove(groupId: string): Promise<void> {
    await apiClient.delete(`/group-mappings/${groupId}`);
  },
};
