import { apiClient } from './client';
import type { Paginated, ModelVersion, ModelCard, ModelStage, Framework } from '../types/platform';

export interface RegisterModelPayload {
  name: string;
  /** Target tenant — required for PlatformAdmin, own tenant otherwise. */
  tenantId?: string;
  /** Optional at registration — models are registered at inception, before
   * training; the run and artifact are attached later via update(). */
  runId?: string;
  framework: Framework;
  description: string;
  artifactUri?: string;
  hasExplainer?: boolean;
}

/** Post-training update: attach the trained artifact + MRM metadata. */
export interface UpdateModelPayload {
  description?: string;
  runId?: string;
  framework?: Framework;
  artifactUri?: string;
  /** Model I/O contract shown to MRM on the review page (free-form JSON). */
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  hasExplainer?: boolean;
  driftBaselineUri?: string;
}

export interface ListModelsParams {
  page?: number;
  pageSize?: number;
  stage?: string;
  tenantId?: string;
}

// Model names are tenant-scoped on the backend: tenantId is required for
// cross-tenant roles (PlatformAdmin/MRM) on the name-based endpoints below;
// tenant-scoped users may omit it.
export const modelsApi = {
  async list(params: ListModelsParams = {}): Promise<Paginated<ModelVersion>> {
    const { data } = await apiClient.get<Paginated<ModelVersion>>('/models', { params });
    return data;
  },
  async register(payload: RegisterModelPayload): Promise<ModelVersion> {
    const { data } = await apiClient.post<ModelVersion>('/models', payload);
    return data;
  },
  async listVersions(name: string, tenantId?: string): Promise<Paginated<ModelVersion>> {
    const { data } = await apiClient.get<Paginated<ModelVersion>>(
      `/models/${encodeURIComponent(name)}/versions`,
      { params: { tenantId } },
    );
    return data;
  },
  async update(
    name: string,
    version: number,
    payload: UpdateModelPayload,
    tenantId?: string,
  ): Promise<ModelVersion> {
    const { data } = await apiClient.put<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}`,
      payload,
      { params: { tenantId } },
    );
    return data;
  },
  async getVersion(name: string, version: number, tenantId?: string): Promise<ModelVersion> {
    const { data } = await apiClient.get<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}`,
      { params: { tenantId } },
    );
    return data;
  },
  async setStage(
    name: string,
    version: number,
    stage: ModelStage,
    tenantId?: string,
  ): Promise<ModelVersion> {
    const { data } = await apiClient.put<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}/stage`,
      { stage },
      { params: { tenantId } },
    );
    return data;
  },
  async getCard(name: string, version: number, tenantId?: string): Promise<ModelCard> {
    const { data } = await apiClient.get<ModelCard>(
      `/models/${encodeURIComponent(name)}/versions/${version}/card`,
      { params: { tenantId } },
    );
    return data;
  },
  async archive(name: string, version: number, tenantId?: string): Promise<ModelVersion> {
    const { data } = await apiClient.post<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${version}/archive`,
      undefined,
      { params: { tenantId } },
    );
    return data;
  },
};
