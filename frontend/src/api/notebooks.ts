import { apiClient } from './client';
import type { NotebookSession, SessionType, Paginated } from '../types/platform';

export interface LaunchNotebookPayload {
  sessionType: SessionType;
  tenantId: string;
  /** Launch in collaborative mode for a business use case — everyone
   * launching against the same use case shares one workspace. */
  usecaseId?: string;
}

export const notebooksApi = {
  async launch(payload: LaunchNotebookPayload): Promise<NotebookSession> {
    const { data } = await apiClient.post<NotebookSession>('/notebooks/launch', payload);
    return data;
  },
  async sessions(): Promise<Paginated<NotebookSession>> {
    const { data } = await apiClient.get<Paginated<NotebookSession>>('/notebooks/sessions');
    return data;
  },
};
