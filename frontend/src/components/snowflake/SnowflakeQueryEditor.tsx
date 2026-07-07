import { useState } from 'react';
import { snowflakeApi } from '../../api/snowflake';
import { extractErrorMessage } from '../../api/client';
import { Button, Field, Input } from '../shared/ui';
import type { SnowflakeQueryResult } from '../../types/platform';

interface SnowflakeQueryEditorProps {
  database: string;
  schema: string;
  warehouse: string;
  initialSql?: string;
  onSqlChange?: (sql: string) => void;
  onResult?: (result: SnowflakeQueryResult) => void;
}

const DEFAULT_LIMIT = 100;

export function SnowflakeQueryEditor({
  database,
  schema,
  warehouse,
  initialSql = 'SELECT * FROM ',
  onSqlChange,
  onResult,
}: SnowflakeQueryEditorProps) {
  const [sql, setSql] = useState(initialSql);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SnowflakeQueryResult | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await snowflakeApi.query({ sql, database, schema, warehouse, limit });
      setResult(res);
      onResult?.(res);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-bg-elevated bg-bg-dark">
        <textarea
          value={sql}
          onChange={(e) => {
            setSql(e.target.value);
            onSqlChange?.(e.target.value);
          }}
          spellCheck={false}
          rows={5}
          placeholder="SELECT * FROM MY_TABLE WHERE ..."
          className="w-full resize-y bg-transparent px-4 py-3 font-mono text-sm text-text-primary placeholder:text-text-muted focus:outline-none"
        />
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bg-elevated px-4 py-2.5">
          <div className="flex items-center gap-3 text-xs text-text-muted">
            <span className="font-mono">
              {database || '—'}.{schema || '—'} · {warehouse || 'default WH'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Field className="flex items-center gap-2">
              <span className="text-xs text-text-secondary">Limit</span>
              <Input
                type="number"
                min={1}
                max={1000}
                value={limit}
                onChange={(e) => setLimit(Math.min(1000, Math.max(1, Number(e.target.value) || 1)))}
                className="w-20"
              />
            </Field>
            <Button loading={running} onClick={() => void run()} disabled={!sql.trim()}>
              Run query
            </Button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {result && (
        <div className="overflow-hidden rounded-xl border border-bg-elevated bg-bg-card">
          <div className="flex items-center justify-between border-b border-bg-elevated px-4 py-2 text-xs text-text-secondary">
            <span>
              {result.rowCount} row{result.rowCount === 1 ? '' : 's'} · query{' '}
              <span className="font-mono text-text-muted">{result.queryId}</span>
            </span>
          </div>
          <div className="max-h-80 overflow-auto">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-bg-elevated/60">
                <tr>
                  {result.columns.map((c) => (
                    <th key={c} className="whitespace-nowrap px-3 py-2 text-left font-mono text-xs text-text-secondary">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i} className="border-t border-bg-elevated/60">
                    {row.map((cell, j) => (
                      <td key={j} className="whitespace-nowrap px-3 py-1.5 font-mono text-xs text-text-primary">
                        {cell === null ? <span className="text-text-muted">NULL</span> : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
