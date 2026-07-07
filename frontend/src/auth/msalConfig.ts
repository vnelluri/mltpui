import type { Configuration, PopupRequest } from '@azure/msal-browser';

const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID || 'common';
const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID || '00000000-0000-0000-0000-000000000000';

export const DEMO_MODE = String(import.meta.env.VITE_DEMO_MODE ?? 'true').toLowerCase() === 'true';

export const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: window.location.origin,
    postLogoutRedirectUri: window.location.origin + '/login',
  },
  cache: {
    cacheLocation: 'localStorage',
    storeAuthStateInCookie: false,
  },
  system: {
    allowNativeBroker: false,
  },
};

// Scopes requested at login. `openid`/`profile` yield the ID token; the API
// scope yields an access token used as the Bearer credential for the backend.
export const loginRequest: PopupRequest = {
  scopes: ['openid', 'profile', 'email', 'User.Read'],
};

export const apiTokenRequest: PopupRequest = {
  scopes: ['api://ml-training-platform/ml-platform.read', 'api://ml-training-platform/ml-platform.write'],
};
