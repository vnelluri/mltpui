import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import axios from 'axios';
import { fetchAuthSession, signInWithRedirect, signOut } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import { AMPLIFY_CONFIGURED, DEMO_MODE, SAML_PROVIDER } from './amplifyConfig';
import { setTokenProvider, getActiveMembership, setActiveMembership } from '../api/client';
import { authApi } from '../api/auth';
import type { CurrentUser, Role } from '../types/platform';
import { parseTenantRole } from './roles';

type AuthStatus =
  | 'initializing'
  | 'unauthenticated'
  | 'authenticating'
  | 'authenticated'
  | 'no-access'
  | 'error';

interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUser | null;
  /** Azure AD group names from the ID token's custom:groups claim — display/debug only. */
  groups: string[];
  /** Role derived from groups claim — display/debug only, NOT authoritative. */
  tokenRole: Role | null;
  /** The demo role-selector value (localStorage). Purely visual. */
  demoRole: Role;
  demoMode: boolean;
  error: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setDemoRole: (role: Role) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const DEMO_AUTH_KEY = 'mlplatform.demoAuthenticated';
const DEMO_ROLE_KEY = 'mlplatform.demoRole';
const SIGNED_OUT_KEY = 'mlplatform.signedOut';

/**
 * True after an explicit sign-out in this tab. The login page auto-initiates
 * SSO for unauthenticated visitors; without this flag, logging out would
 * bounce straight back through the Hosted UI (silently, if the Azure AD
 * session is still alive) and sign the user right back in.
 */
export function wasExplicitlySignedOut(): boolean {
  return sessionStorage.getItem(SIGNED_OUT_KEY) === 'true';
}

/**
 * Parse the `custom:groups` ID-token claim: a comma-separated string of
 * Azure AD group names (Cognito may wrap multi-valued SAML attributes in
 * square brackets). Mirrors the backend's parse_groups_claim.
 */
function parseGroupsClaim(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((g) => String(g).trim()).filter(Boolean);
  }
  if (typeof value !== 'string') return [];
  let cleaned = value.trim();
  if (cleaned.startsWith('[') && cleaned.endsWith(']')) {
    cleaned = cleaned.slice(1, -1);
  }
  return cleaned
    .split(',')
    .map((g) => g.trim())
    .filter(Boolean);
}

async function groupsFromSession(): Promise<string[] | null> {
  try {
    const session = await fetchAuthSession();
    const payload = session.tokens?.idToken?.payload;
    if (!payload) return null;
    return parseGroupsClaim(payload['custom:groups']);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('initializing');
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [demoRole, setDemoRoleState] = useState<Role>(
    () => (localStorage.getItem(DEMO_ROLE_KEY) as Role) || 'PlatformAdmin',
  );

  const tokenRole = useMemo(() => parseTenantRole(groups), [groups]);

  // Register the Bearer-token provider used by api/client.ts (prod mode only).
  // The backend reads user info from the Cognito ID token, so the ID token —
  // not the access token — is the Bearer credential. Amplify refreshes the
  // session transparently inside fetchAuthSession.
  const registerTokenProvider = useCallback(() => {
    if (DEMO_MODE) {
      setTokenProvider(null);
      return;
    }
    setTokenProvider(async () => {
      try {
        const session = await fetchAuthSession();
        return session.tokens?.idToken?.toString() ?? null;
      } catch {
        return null;
      }
    });
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      const me = await authApi.me();
      setUser(me);
      setError(null);
      setStatus('authenticated');
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 403) {
        // A stale stored role/tenant selection (e.g. a membership revoked in
        // AD) 403s every request — clear it and retry once with the default
        // membership before concluding the user has no access at all.
        if (getActiveMembership()) {
          setActiveMembership(null);
          try {
            const me = await authApi.me();
            setUser(me);
            setError(null);
            setStatus('authenticated');
            return;
          } catch {
            // Fall through to no-access below.
          }
        }
        setStatus('no-access');
        setUser(null);
        return;
      }
      setError('Unable to load your profile from the platform.');
      setStatus('error');
    }
  }, []);

  // Complete a signed-in Cognito session: groups from the ID token, token
  // provider registration, then the authoritative /auth/me.
  const completeSignIn = useCallback(
    async (sessionGroups: string[]) => {
      setGroups(sessionGroups);
      registerTokenProvider();
      await refreshMe();
    },
    [refreshMe, registerTokenProvider],
  );

  // Initial bootstrap.
  useEffect(() => {
    let cancelled = false;

    if (DEMO_MODE) {
      setTokenProvider(null);
      const wasAuthed = localStorage.getItem(DEMO_AUTH_KEY) === 'true';
      if (wasAuthed) {
        void refreshMe();
      } else {
        setStatus('unauthenticated');
      }
      return;
    }

    if (!AMPLIFY_CONFIGURED) {
      setError(
        'Cognito is not configured. Set VITE_COGNITO_USER_POOL_ID, ' +
          'VITE_COGNITO_CLIENT_ID and VITE_COGNITO_DOMAIN.',
      );
      setStatus('error');
      return;
    }

    // Prod mode: Amplify parses the Hosted UI redirect (?code=…) on load and
    // announces the outcome via Hub — listen before probing for a session so
    // the callback can't be missed.
    const unsubscribe = Hub.listen('auth', ({ payload }) => {
      switch (payload.event) {
        case 'signInWithRedirect':
          void (async () => {
            const sessionGroups = await groupsFromSession();
            if (!cancelled) await completeSignIn(sessionGroups ?? []);
          })();
          break;
        case 'signInWithRedirect_failure':
          if (!cancelled) {
            setError('Single sign-on failed. Please try again.');
            setStatus('unauthenticated');
          }
          break;
      }
    });

    void (async () => {
      const sessionGroups = await groupsFromSession();
      if (cancelled) return;
      if (sessionGroups !== null) {
        await completeSignIn(sessionGroups);
        return;
      }
      // No session yet. If this load IS the Hosted UI callback, stay in
      // 'authenticating' and let the Hub listener finish; otherwise the user
      // simply isn't signed in.
      const params = new URLSearchParams(window.location.search);
      if (params.has('code') || params.has('error')) {
        setStatus('authenticating');
      } else {
        setStatus('unauthenticated');
      }
    })();

    return () => {
      cancelled = true;
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async () => {
    setStatus('authenticating');
    setError(null);
    sessionStorage.removeItem(SIGNED_OUT_KEY);
    if (DEMO_MODE) {
      localStorage.setItem(DEMO_AUTH_KEY, 'true');
      await refreshMe();
      return;
    }
    try {
      // Full-page redirect: Hosted UI → Azure AD (SAML) → back here, where
      // the bootstrap effect's Hub listener completes the sign-in.
      await signInWithRedirect({ provider: { custom: SAML_PROVIDER } });
    } catch {
      setError('Single sign-on could not be started.');
      setStatus('unauthenticated');
    }
  }, [refreshMe]);

  const logout = useCallback(async () => {
    localStorage.removeItem(DEMO_AUTH_KEY);
    sessionStorage.setItem(SIGNED_OUT_KEY, 'true'); // suppress the login page's auto-SSO
    setActiveMembership(null); // never carry a role/tenant selection across users
    setUser(null);
    setGroups([]);
    setStatus('unauthenticated');
    if (!DEMO_MODE) {
      try {
        // Redirects through the Cognito /logout endpoint back to /login.
        await signOut();
      } catch {
        // Ignore sign-out errors; local state is already cleared.
      }
    }
  }, []);

  const setDemoRole = useCallback((role: Role) => {
    localStorage.setItem(DEMO_ROLE_KEY, role);
    setDemoRoleState(role);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      groups,
      tokenRole,
      demoRole,
      demoMode: DEMO_MODE,
      error,
      login,
      logout,
      refreshMe,
      setDemoRole,
    }),
    [status, user, groups, tokenRole, demoRole, error, login, logout, refreshMe, setDemoRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
