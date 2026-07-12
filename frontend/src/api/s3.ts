import { apiClient } from './client';
import type { S3BrowseResult } from '../types/platform';

export const s3Api = {
  async browse(prefix = ''): Promise<S3BrowseResult> {
    const { data } = await apiClient.get<S3BrowseResult>('/s3/browse', { params: { prefix } });
    return data;
  },

  async upload(file: File, prefix?: string): Promise<{ bucket: string; key: string; size: number }> {
    const form = new FormData();
    form.append('file', file);
    if (prefix) form.append('prefix', prefix);
    const { data } = await apiClient.post<{ bucket: string; key: string; size: number }>(
      '/s3/upload',
      form,
    );
    return data;
  },
};
