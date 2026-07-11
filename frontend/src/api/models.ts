import { apiClient } from './client';
import type { Paginated, ModelVersion, ModelCard, ModelStage, Framework } from '../types/platform';

export interface RegisterModelPayload {
  /** The model's inventory KEY (e.g. MDL-0001) — shared by all versions;
   * (modelId, version) is enforced unique. */
  modelId: string;
  name: string;
  /** Explicit version; omitted → the next version for this model name. */
  version?: string;
  /** Business use case the model serves — required at registration; the run
   * and artifact are attached later via update() once training completes. */
  usecaseId: string;
  /** Target tenant — required for PlatformAdmin, own tenant otherwise. */
  tenantId?: string;
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
  modelSchema?: Record<string, unknown>;
  /** Evaluation results (JSON) submitted alongside the artifact. */
  results?: Record<string, unknown>;
  /** S3 URI of the model documentation package (verified to exist). */
  documentationUri?: string;
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
    version: string,
    payload: UpdateModelPayload,
    tenantId?: string,
  ): Promise<ModelVersion> {
    const { data } = await apiClient.put<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}`,
      payload,
      { params: { tenantId } },
    );
    return data;
  },
  async getVersion(name: string, version: string, tenantId?: string): Promise<ModelVersion> {
    const { data } = await apiClient.get<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}`,
      { params: { tenantId } },
    );
    return data;
  },
  async setStage(
    name: string,
    version: string,
    stage: ModelStage,
    tenantId?: string,
    /** ServiceNow change ticket — required by the backend for Production. */
    snowTicketId?: string,
  ): Promise<ModelVersion> {
    const { data } = await apiClient.put<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}/stage`,
      { stage, snowTicketId },
      { params: { tenantId } },
    );
    return data;
  },
  async getCard(name: string, version: string, tenantId?: string): Promise<ModelCard> {
    const { data } = await apiClient.get<ModelCard>(
      `/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}/card`,
      { params: { tenantId } },
    );
    return data;
  },
  async archive(name: string, version: string, tenantId?: string): Promise<ModelVersion> {
    const { data } = await apiClient.post<ModelVersion>(
      `/models/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}/archive`,
      undefined,
      { params: { tenantId } },
    );
    return data;
  },
};
