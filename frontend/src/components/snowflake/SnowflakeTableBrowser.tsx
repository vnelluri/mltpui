import { useEffect, useState } from 'react';
import { snowflakeApi } from '../../api/snowflake';
import { extractErrorMessage } from '../../api/client';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import type { SnowflakePreview } from '../../types/platform';

export interface SnowflakeSelection {
  database: string;
  schema: string;
  table: string;
}

interface SnowflakeTableBrowserProps {
  onSelectTable: (selection: SnowflakeSelection, preview: SnowflakePreview) => void;
  selected?: SnowflakeSelection | null;
}

interface NodeState {
  expanded: boolean;
  loading: boolean;
  error: string | null;
  children: string[] | null;
}

const chevron = (expanded: boolean) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    className={`transition-transform ${expanded ? 'rotate-90' : ''}`}
  >
    <path d="M9 6l6 6-6 6" />
  </svg>
);

export function SnowflakeTableBrowser({ onSelectTable, selected }: SnowflakeTableBrowserProps) {
  const [databases, setDatabases] = useState<string[]>([]);
  const [loadingDbs, setLoadingDbs] = useState(true);
  const [dbError, setDbError] = useState<string | null>(null);
  const [dbNodes, setDbNodes] = useState<Record<string, NodeState>>({});
  const [schemaNodes, setSchemaNodes] = useState<Record<string, NodeState>>({});
  const [previewLoading, setPreviewLoading] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const dbs = await snowflakeApi.databases();
        if (!cancelled) setDatabases(dbs);
      } catch (err) {
        if (!cancelled) setDbError(extractErrorMessage(err));
      } finally {
        if (!cancelled) setLoadingDbs(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleDb = async (db: string) => {
    const current = dbNodes[db];
    if (current?.expanded) {
      setDbNodes((prev) => ({ ...prev, [db]: { ...current, expanded: false } }));
      return;
    }
    if (current?.children) {
      setDbNodes((prev) => ({ ...prev, [db]: { ...current, expanded: true } }));
      return;
    }
    setDbNodes((prev) => ({ ...prev, [db]: { expanded: true, loading: true, error: null, children: null } }));
    try {
      const schemas = await snowflakeApi.schemas(db);
      setDbNodes((prev) => ({ ...prev, [db]: { expanded: true, loading: false, error: null, children: schemas } }));
    } catch (err) {
      setDbNodes((prev) => ({
        ...prev,
        [db]: { expanded: true, loading: false, error: extractErrorMessage(err), children: null },
      }));
    }
  };

  const toggleSchema = async (db: string, schema: string) => {
    const key = `${db}.${schema}`;
    const current = schemaNodes[key];
    if (current?.expanded) {
      setSchemaNodes((prev) => ({ ...prev, [key]: { ...current, expanded: false } }));
      return;
    }
    if (current?.children) {
      setSchemaNodes((prev) => ({ ...prev, [key]: { ...current, expanded: true } }));
      return;
    }
    setSchemaNodes((prev) => ({ ...prev, [key]: { expanded: true, loading: true, error: null, children: null } }));
    try {
      const tables = await snowflakeApi.tables(db, schema);
      setSchemaNodes((prev) => ({
        ...prev,
        [key]: { expanded: true, loading: false, error: null, children: tables },
      }));
    } catch (err) {
      setSchemaNodes((prev) => ({
        ...prev,
        [key]: { expanded: true, loading: false, error: extractErrorMessage(err), children: null },
      }));
    }
  };

  const selectTable = async (db: string, schema: string, table: string) => {
    const key = `${db}.${schema}.${table}`;
    setPreviewLoading(key);
    try {
      const preview = await snowflakeApi.preview(db, schema, table);
      onSelectTable({ database: db, schema, table }, preview);
    } catch (err) {
      setDbError(extractErrorMessage(err));
    } finally {
      setPreviewLoading(null);
    }
  };

  if (loadingDbs) {
    return (
      <div className="rounded-xl border border-bg-elevated bg-bg-card p-8">
        <LoadingSpinner label="Loading databases…" size="sm" />
      </div>
    );
  }

  if (dbError) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-bg-card p-4 text-sm text-red-300">{dbError}</div>
    );
  }

  return (
    <div className="max-h-96 overflow-y-auto rounded-xl border border-bg-elevated bg-bg-card p-2 font-mono text-sm">
      {databases.map((db) => {
        const dbNode = dbNodes[db];
        return (
          <div key={db}>
            <button
              onClick={() => void toggleDb(db)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-text-primary transition hover:bg-bg-elevated"
            >
              {chevron(!!dbNode?.expanded)}
              <span className="text-brand-purple">🗄</span>
              {db}
            </button>
            {dbNode?.expanded && (
              <div className="ml-5 border-l border-bg-elevated pl-2">
                {dbNode.loading && <div className="px-2 py-1 text-xs text-text-muted">Loading schemas…</div>}
                {dbNode.error && <div className="px-2 py-1 text-xs text-red-300">{dbNode.error}</div>}
                {dbNode.children?.map((schema) => {
                  const key = `${db}.${schema}`;
                  const schemaNode = schemaNodes[key];
                  return (
                    <div key={schema}>
                      <button
                        onClick={() => void toggleSchema(db, schema)}
                        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-text-secondary transition hover:bg-bg-elevated"
                      >
                        {chevron(!!schemaNode?.expanded)}
                        <span className="text-sky-400">📁</span>
                        {schema}
                      </button>
                      {schemaNode?.expanded && (
                        <div className="ml-5 border-l border-bg-elevated pl-2">
                          {schemaNode.loading && (
                            <div className="px-2 py-1 text-xs text-text-muted">Loading tables…</div>
                          )}
                          {schemaNode.error && (
                            <div className="px-2 py-1 text-xs text-red-300">{schemaNode.error}</div>
                          )}
                          {schemaNode.children?.map((table) => {
                            const tableKey = `${db}.${schema}.${table}`;
                            const isSelected =
                              selected?.database === db &&
                              selected?.schema === schema &&
                              selected?.table === table;
                            return (
                              <button
                                key={table}
                                onClick={() => void selectTable(db, schema, table)}
                                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-bg-elevated ${
                                  isSelected ? 'bg-brand-purple/15 text-brand-purple' : 'text-text-secondary'
                                }`}
                              >
                                <span className="w-3.5" />
                                <span className="text-emerald-400">▦</span>
                                {table}
                                {previewLoading === tableKey && (
                                  <span className="ml-auto text-xs text-text-muted">loading…</span>
                                )}
                                {isSelected && <span className="ml-auto text-xs">selected</span>}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
