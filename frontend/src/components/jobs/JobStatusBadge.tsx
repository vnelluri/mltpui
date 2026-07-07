import { StatusBadge } from '../shared/StatusBadge';
import type { JobStatus } from '../../types/platform';

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <StatusBadge status={status} />;
}
