/** True when the value looks like a usable S3 object/prefix URI:
 * s3://<bucket>/<key…> — a bucket alone (s3://bucket or s3://bucket/) is not
 * enough; the backend requires a key or prefix after the bucket. Trailing
 * slashes are fine (prefixes). Mirrors backend _validate_artifact_uri. */
export function isValidS3Uri(uri: string): boolean {
  const trimmed = uri.trim();
  if (!trimmed.startsWith('s3://')) return false;
  const rest = trimmed.slice('s3://'.length);
  const slash = rest.indexOf('/');
  if (slash <= 0) return false; // no bucket, or nothing after it
  const key = rest.slice(slash + 1);
  return key.replace(/\//g, '').length > 0;
}

export const S3_URI_FORMAT_HINT =
  's3://<bucket>/<path>, e.g. s3://ml-platform-artifacts/<tenant>/models/model.pkl';
