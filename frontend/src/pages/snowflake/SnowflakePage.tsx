import { useState } from 'react';
import { useSnowflake } from '../../hooks/useSnowflake';
import { PageHeader, Card } from '../../components/shared/ui';
import { SnowflakeConnectBanner } from '../../components/snowflake/SnowflakeConnectBanner';
import { SnowflakeTableBrowser, type SnowflakeSelection } from '../../components/snowflake/SnowflakeTableBrowser';
import { SnowflakeQueryEditor } from '../../components/snowflake/SnowflakeQueryEditor';

/** Read the OAuth-callback outcome params once and clean them off the URL
 * (the backend redirects here with ?connected=1 or ?error=… after Entra). */
function consumeCallbackOutcome(): 'connected' | 'failed' | null {
  const params = new URLSearchParams(window.location.search);
  const outcome = params.get('error') ? 'failed' : params.get('connected') ? 'connected' : null;
  if (outcome) {
    params.delete('error');
    params.delete('connected');
    const rest = params.toString();
    window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''));
  }
  return outcome;
}

export function SnowflakePage() {
  const snowflake = useSnowflake();
  const [selection, setSelection] = useState<SnowflakeSelection | null>(null);
  const [callbackOutcome] = useState(consumeCallbackOutcome);

  return (
    <div>
      <PageHeader title="Snowflake" description="Browse tables and run ad-hoc read-only queries under your own identity." />

      {callbackOutcome === 'failed' && (
        <Card className="mb-4 border-red-300 p-4 text-sm text-red-600">
          Connecting to Snowflake failed — the sign-in at Entra was cancelled or rejected. Try again.
        </Card>
      )}

      <SnowflakeConnectBanner snowflake={snowflake} className="mb-6" />

      {snowflake.state !== 'connected' ? (
        <Card className="p-8 text-center text-sm text-text-secondary">
          Connect to Snowflake above to browse databases and run queries.
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div>
            <h3 className="mb-3 text-sm font-semibold text-text-primary">Databases</h3>
            <SnowflakeTableBrowser
              selected={selection}
              onSelectTable={(sel) => {
                setSelection(sel);
              }}
            />
          </div>
          <div className="lg:col-span-2">
            <h3 className="mb-3 text-sm font-semibold text-text-primary">Query editor</h3>
            <SnowflakeQueryEditor
              key={selection ? `${selection.database}.${selection.schema}.${selection.table}` : 'empty'}
              database={selection?.database ?? ''}
              schema={selection?.schema ?? ''}
              warehouse="COMPUTE_WH"
              initialSql={selection ? `SELECT * FROM ${selection.table}` : 'SELECT * FROM '}
            />
          </div>
        </div>
      )}
    </div>
  );
}
