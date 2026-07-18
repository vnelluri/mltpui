import { Amplify } from 'aws-amplify';

export const DEMO_MODE = String(import.meta.env.VITE_DEMO_MODE ?? 'true').toLowerCase() === 'true';

// Cognito user pool + Hosted UI settings. Sign-in goes through the Hosted UI,
// which federates to Azure AD via the SAML identity provider named below —
// the app itself never talks to Azure AD.
const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID || '';
const userPoolClientId = import.meta.env.VITE_COGNITO_CLIENT_ID || '';
// Hosted UI domain WITHOUT scheme, e.g. "myapp.auth.us-east-1.amazoncognito.com".
const domain = import.meta.env.VITE_COGNITO_DOMAIN || '';

// Name of the SAML identity provider configured in the user pool.
export const SAML_PROVIDER = import.meta.env.VITE_COGNITO_SAML_PROVIDER || 'AzureAD';

export const AMPLIFY_CONFIGURED = !DEMO_MODE && !!(userPoolId && userPoolClientId && domain);

if (AMPLIFY_CONFIGURED) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        loginWith: {
          oauth: {
            domain,
            scopes: ['openid', 'email', 'profile'],
            redirectSignIn: [window.location.origin],
            redirectSignOut: [window.location.origin + '/login'],
            responseType: 'code',
          },
        },
      },
    },
  });
}
