/** Conventions shared by the job wizard, clone, and re-run flows. */

/** Today's LOCAL calendar date as YYYY-MM-DD. (toISOString() is UTC and rolls
 * to tomorrow for evening users west of Greenwich — wrong AS_OF_DATE.) */
export function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Default output prefix convention: each (job, as-of date) gets its own
 * prefix so backfills never overwrite another day's artifacts. */
export function deriveOutputPath(
  name: string,
  framework: string,
  tenantId: string | null | undefined,
  asOfDate: string,
): string {
  const slug = (name.trim() || `${framework}-job`)
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `s3://ml-platform-artifacts/${tenantId ?? '<tenant>'}/models/${slug}/${asOfDate || 'latest'}/`;
}

/** When a path follows the dated-prefix convention (ends with /<oldDate>/),
 * swap in a new date; otherwise return the path untouched. */
export function swapDatedPrefix(path: string | null | undefined, oldDate: string | null | undefined, newDate: string): string {
  if (path && oldDate && newDate && path.endsWith(`/${oldDate}/`)) {
    return path.slice(0, -(oldDate.length + 1)) + `${newDate}/`;
  }
  return path ?? '';
}
