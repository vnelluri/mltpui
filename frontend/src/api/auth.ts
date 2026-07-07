import { apiClient } from './client';
import type { CurrentUser } from '../types/platform';

export interface TokenInfo {
  claims: Record<string, unknown>;
  groups: string[];
}

export const authApi = {
  async me(): Promise<CurrentUser> {
    const { data } = await apiClient.get<CurrentUser>('/auth/me');
    return data;
  },
  async tokenInfo(): Promise<TokenInfo> {
    const { data } = await apiClient.get<TokenInfo>('/auth/token-info');
    return data;
  },
};
