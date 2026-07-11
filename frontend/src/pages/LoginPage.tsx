import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { ROLES, ROLE_LABELS, ROLE_DESCRIPTIONS, landingPathForRole } from '../auth/roles';
import type { Role } from '../types/platform';
import { Button } from '../components/shared/ui';

export function LoginPage() {
  const { status, user, error, login, demoMode, demoRole, setDemoRole } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (status === 'authenticated' && user) {
      navigate(landingPathForRole(user.role), { replace: true });
    }
    if (status === 'no-access') {
      navigate('/no-access', { replace: true });
    }
  }, [status, user, navigate]);

  return (
    <div className="flex min-h-screen bg-bg-dark">
      {/* Left panel */}
      <div className="login-grid-pattern relative hidden w-1/2 flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-valhalla via-brand-valhalla to-[#1a0f2e] p-12 lg:flex">
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />
        <div className="relative z-10 flex items-center gap-3">
          <img src="/truist-logo.svg" alt="Truist" className="h-10 w-10" />
          <span className="text-lg font-semibold text-white">Truist</span>
        </div>
        <div className="relative z-10 max-w-md">
          <h1 className="text-4xl font-semibold leading-tight text-white">
            Enterprise ML Training Platform
          </h1>
          {/* On-dark periwinkle: this panel stays valhalla-dark in the light theme */}
          <p className="mt-4 text-[#A6A3E0]/90">
            Submit training jobs, track experiments, and govern models across every
            business unit — with tenancy and access derived directly from Entra ID.
          </p>
        </div>
        <p className="relative z-10 text-xs text-white/40">
          © {new Date().getFullYear()} Truist Financial Corporation. Internal use only.
        </p>
      </div>

      {/* Right panel */}
      <div className="flex w-full flex-col items-center justify-center px-6 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-8 text-center lg:hidden">
            <img src="/truist-logo.svg" alt="Truist" className="mx-auto mb-3 h-10 w-10" />
            <h1 className="text-xl font-semibold text-text-primary">ML Training Platform</h1>
          </div>

          <h2 className="text-2xl font-semibold text-text-primary">Sign in</h2>
          <p className="mt-1 text-sm text-text-secondary">
            {demoMode
              ? 'Local demo mode — pick a role to explore the platform.'
              : 'Sign in with your Truist Microsoft account.'}
          </p>

          {error && (
            <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {demoMode ? (
            <div className="mt-6 space-y-2">
              {ROLES.map((role: Role) => (
                <button
                  key={role}
                  onClick={() => setDemoRole(role)}
                  className={`w-full rounded-xl border px-4 py-3 text-left transition ${
                    demoRole === role
                      ? 'border-brand-purple bg-brand-purple/10'
                      : 'border-bg-elevated bg-bg-card hover:border-brand-purple/40'
                  }`}
                >
                  <p className="text-sm font-semibold text-text-primary">{ROLE_LABELS[role]}</p>
                  <p className="mt-0.5 text-xs text-text-secondary">{ROLE_DESCRIPTIONS[role]}</p>
                </button>
              ))}
              <Button
                className="mt-4 w-full"
                loading={status === 'authenticating'}
                onClick={() => void login()}
              >
                Continue as {ROLE_LABELS[demoRole]}
              </Button>
              <p className="mt-3 text-center text-[11px] text-text-muted">
                The demo role selector only styles the UI locally — your actual role
                and tenant always come from the backend's <code>DEV_USER_ROLE</code> setting
                (<code>AUTH_MODE=dev</code>).
              </p>
            </div>
          ) : (
            <Button
              className="mt-6 w-full gap-3"
              loading={status === 'authenticating'}
              onClick={() => void login()}
            >
              <svg width="18" height="18" viewBox="0 0 21 21" fill="none">
                <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
              </svg>
              Sign in with Microsoft
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
