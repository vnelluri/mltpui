import { apiClient } from './client';
import type { S3BrowseResult } from '../types/platform';

export const s3Api = {
  async browse(prefix = ''): Promise<S3BrowseResult> {
    const { data } = await apiClient.get<S3BrowseResult>('/s3/browse', { params: { prefix } });
    return data;
  },
};
