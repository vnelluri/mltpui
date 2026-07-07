import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/shared/ui';

export function NoAccessPage() {
  const { logout } = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-dark px-6">
      <div className="max-w-lg text-center">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/15 text-red-400">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M18.364 5.636L5.636 18.364M12 21a9 9 0 100-18 9 9 0 000 18z" />
          </svg>
        </div>
        <h1 className="text-xl font-semibold text-text-primary">No group mapping found</h1>
        <p className="mt-3 text-sm text-text-secondary">
          Your Microsoft Entra ID account was authenticated successfully, but it is not a
          member of any Entra security group that has been mapped to a role and tenant
          on this platform.
        </p>
        <p className="mt-3 text-sm text-text-secondary">
          Contact your platform administrator and ask them to add your account's Entra
          group to the appropriate mapping under{' '}
          <span className="font-mono text-text-primary">Group Mappings</span>, or add you
          directly to an existing mapped group (e.g. <em>ML-RiskAnalytics-DataScientists</em>).
        </p>
        <Button variant="secondary" className="mt-6" onClick={() => void logout()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
