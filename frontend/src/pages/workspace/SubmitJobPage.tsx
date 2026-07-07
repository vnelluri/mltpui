import { PageHeader } from '../../components/shared/ui';
import { JobSubmitForm } from '../../components/jobs/JobSubmitForm';

export function SubmitJobPage() {
  return (
    <div>
      <PageHeader title="Submit Training Job" description="Configure and launch a new training job in seven steps." />
      <JobSubmitForm />
    </div>
  );
}
