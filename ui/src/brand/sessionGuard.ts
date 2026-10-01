import type { Client } from "@/client/client";

// Local-auth session guard.
//
// Upstream only checks that the session cookie *exists*: when the backend
// rejects the token (expired JWT, rotated OSS_JWT_SECRET, or a cookie left on
// localhost:3010 by another Dograh instance), every page just fails with 401s
// and the user is never sent back to the login screen. On the first 401 for an
// authenticated request we log out (clears the cookies server-side) instead.

let registered = false;
let loggingOut = false;

export function registerSessionGuard(
  apiClient: Client,
  auth: { provider: string; logout: () => Promise<void> },
) {
  if (registered || auth.provider !== "local") return;
  registered = true;

  apiClient.interceptors.response.use((response, request) => {
    if (
      response.status === 401 &&
      !loggingOut &&
      request.headers.get("Authorization")?.startsWith("Bearer ")
    ) {
      loggingOut = true;
      void auth.logout();
    }
    return response;
  });
}
