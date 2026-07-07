import { apiClient } from './client';
import type {
  SnowflakeStatus,
  SnowflakeQueryResult,
  SnowflakePreview,
  SnowflakeTableColumn,
} from '../types/platform';

export interface RunQueryPayload {
  sql: string;
  database: string;
  schema: string;
  warehouse: string;
  limit: number;
}

export const snowflakeApi = {
  async status(): Promise<SnowflakeStatus> {
    const { data } = await apiClient.get<SnowflakeStatus>('/snowflake/status');
    return data;
  },
  async connect(): Promise<SnowflakeStatus> {
    const { data } = await apiClient.post<SnowflakeStatus>('/snowflake/connect');
    return data;
  },
  async disconnect(): Promise<{ disconnected: boolean }> {
    const { data } = await apiClient.post<{ disconnected: boolean }>('/snowflake/disconnect');
    return data;
  },
  async query(payload: RunQueryPayload): Promise<SnowflakeQueryResult> {
    const { data } = await apiClient.post<SnowflakeQueryResult>('/snowflake/query', payload);
    return data;
  },
  async databases(): Promise<string[]> {
    const { data } = await apiClient.get<string[] | { databases: string[] }>('/snowflake/databases');
    return Array.isArray(data) ? data : data.databases;
  },
  async schemas(db: string): Promise<string[]> {
    const { data } = await apiClient.get<string[] | { schemas: string[] }>(
      `/snowflake/databases/${encodeURIComponent(db)}/schemas`,
    );
    return Array.isArray(data) ? data : data.schemas;
  },
  async tables(db: string, schema: string): Promise<string[]> {
    const { data } = await apiClient.get<string[] | { tables: string[] }>(
      `/snowflake/databases/${encodeURIComponent(db)}/schemas/${encodeURIComponent(schema)}/tables`,
    );
    return Array.isArray(data) ? data : data.tables;
  },
  async preview(
    db: string,
    schema: string,
    table: string,
  ): Promise<SnowflakePreview & { columnTypes?: SnowflakeTableColumn[] }> {
    const { data } = await apiClient.get<SnowflakePreview & { columnTypes?: SnowflakeTableColumn[] }>(
      `/snowflake/databases/${encodeURIComponent(db)}/schemas/${encodeURIComponent(
        schema,
      )}/tables/${encodeURIComponent(table)}/preview`,
    );
    return data;
  },
};
