import { useRef, useState } from 'react';
import { s3Api } from '../../api/s3';
import { extractErrorMessage } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import { useTenantContext } from '../../hooks/useTenantContext';
import { Button, Card, Input, InlineAlert } from '../shared/ui';

/** Upload a file to the tenant's S3 prefix. Renders only for the roles the
 * backend accepts (Data Scientist, MRM) — the API enforces the same rule. */
export function S3UploadCard() {
  const { user } = useAuth();
  const { tenantId, isDataScientist, isMRM } = useTenantContext();

  const defaultPrefix = tenantId && user ? `${tenantId}/users/${user.userId}/` : '';
  const [prefix, setPrefix] = useState(defaultPrefix);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedKey, setUploadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  if (!isDataScientist && !isMRM) return null;

  const onUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setUploadedKey(null);
    try {
      const res = await s3Api.upload(file, prefix || undefined);
      setUploadedKey(res.key);
      setFile(null);
      if (fileInput.current) fileInput.current.value = '';
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card className="p-5">
      <h3 className="mb-1 text-sm font-semibold text-text-primary">Upload to S3</h3>
      {!tenantId ? (
        <InlineAlert tone="info" className="mt-3">
          Uploads are tenant-scoped — switch to a tenant membership to upload files.
        </InlineAlert>
      ) : (
        <>
          <p className="mb-4 text-xs text-text-muted">
            Files land in your personal tenant directory unless you change the destination.
          </p>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Input
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              aria-label="Destination prefix"
              className="font-mono text-xs sm:flex-1"
            />
            <input
              ref={fileInput}
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              aria-label="File to upload"
              className="text-xs text-text-secondary file:mr-3 file:rounded-lg file:border file:border-bg-elevated file:bg-bg-card file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-text-secondary hover:file:bg-bg-elevated"
            />
            <Button onClick={() => void onUpload()} disabled={!file} loading={uploading}>
              Upload
            </Button>
          </div>
          {uploadedKey && (
            <p className="mt-3 text-xs text-green-700">
              Uploaded to <span className="font-mono">{uploadedKey}</span>
            </p>
          )}
          {error && <p className="mt-3 text-xs text-red-700">{error}</p>}
        </>
      )}
    </Card>
  );
}
