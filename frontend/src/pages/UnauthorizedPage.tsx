import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { landingPathForRole } from '../auth/roles';
import { Button } from '../components/shared/ui';

export function UnauthorizedPage() {
  const { user } = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-dark px-6">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-full bg-amber-500/15 text-amber-400">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 15v2m0-10v6m9 3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h1 className="text-xl font-semibold text-text-primary">Access denied</h1>
        <p className="mt-2 text-sm text-text-secondary">
          Your role does not have permission to view this page.
        </p>
        <Link to={user ? landingPathForRole(user.role) : '/login'}>
          <Button className="mt-6">Back to dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
