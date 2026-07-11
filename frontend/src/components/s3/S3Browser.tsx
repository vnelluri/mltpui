import { useEffect, useState } from 'react';
import { s3Api } from '../../api/s3';
import { extractErrorMessage } from '../../api/client';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { Button } from '../shared/ui';
import { formatBytes } from '../../lib/format';
import type { S3File } from '../../types/platform';

interface S3BrowserProps {
  /** Called with a full `s3://bucket/key` URI when the user picks a file or folder. */
  onSelectPath: (s3Uri: string) => void;
  selectedPath?: string | null;
}

export function S3Browser({ onSelectPath, selectedPath }: S3BrowserProps) {
  const [bucket, setBucket] = useState('');
  const [prefix, setPrefix] = useState('');
  const [folders, setFolders] = useState<string[]>([]);
  const [files, setFiles] = useState<S3File[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async (targetPrefix: string) => {
    setLoading(true);
    try {
      const res = await s3Api.browse(targetPrefix);
      setBucket(res.bucket);
      setPrefix(res.prefix);
      setFolders(res.folders);
      setFiles(res.files);
      setError(null);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const segments = prefix.split('/').filter(Boolean);
  const breadcrumbPrefixFor = (index: number) => `${segments.slice(0, index + 1).join('/')}/`;

  return (
    <div className="rounded-xl border border-bg-elevated bg-bg-card">
      <div className="flex flex-wrap items-center gap-1 border-b border-bg-elevated px-3 py-2 font-mono text-xs text-text-secondary">
        <button onClick={() => void load('')} className="hover:text-brand-purple">
          {bucket || 'bucket'}
        </button>
        {segments.map((seg, i) => (
          <span key={i} className="flex items-center gap-1">
            <span className="text-text-muted">/</span>
            <button onClick={() => void load(breadcrumbPrefixFor(i))} className="hover:text-brand-purple">
              {seg}
            </button>
          </span>
        ))}
      </div>

      {loading ? (
        <div className="p-6">
          <LoadingSpinner label="Loading…" size="sm" />
        </div>
      ) : error ? (
        <div className="p-4 text-sm text-red-600">{error}</div>
      ) : (
        <div className="max-h-72 overflow-y-auto p-2 font-mono text-sm">
          {folders.length === 0 && files.length === 0 && (
            <p className="px-2 py-4 text-xs text-text-muted">This folder is empty.</p>
          )}
          {folders.map((folder) => {
            const name = folder.replace(prefix, '').replace(/\/$/, '');
            return (
              <button
                key={folder}
                onClick={() => void load(folder)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-text-primary transition hover:bg-bg-elevated"
              >
                <span className="text-sky-400">📁</span>
                {name}
              </button>
            );
          })}
          {files.map((file) => {
            const name = file.key.replace(prefix, '');
            const uri = `s3://${bucket}/${file.key}`;
            const isSelected = selectedPath === uri;
            return (
              <button
                key={file.key}
                onClick={() => onSelectPath(uri)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition hover:bg-bg-elevated ${
                  isSelected ? 'bg-brand-purple/15 text-brand-purple' : 'text-text-secondary'
                }`}
              >
                <span className="text-emerald-400">▦</span>
                <span className="flex-1 truncate">{name}</span>
                <span className="text-[11px] text-text-muted">{formatBytes(file.size)}</span>
                {isSelected && <span className="text-[11px]">selected</span>}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between border-t border-bg-elevated px-3 py-2">
        <span className="truncate font-mono text-[11px] text-text-muted">
          s3://{bucket}/{prefix}
        </span>
        <Button
          variant="secondary"
          className="!px-3 !py-1.5 !text-xs"
          onClick={() => onSelectPath(`s3://${bucket}/${prefix}`)}
        >
          Use this folder
        </Button>
      </div>
    </div>
  );
}
