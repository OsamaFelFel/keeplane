# Browser CSRF cases

**Edition:** Open Source; the browser contract also applies to Enterprise.

Run `.venv/bin/python -m pytest tests/e2e/test_csrf.py -m live` against either protected preview using
`KEEPLANE_BASE_URL`. The full regression includes both addresses. Cookies and
tokens stay in memory and do not appear in evidence.

| Case | Action | Expected result |
| --- | --- | --- |
| CSRF-01 | Fetch authentication options anonymously. | A masked token, HttpOnly Strict cookie and no-store response are returned. |
| CSRF-02 | Sign in with a missing token, wrong token, then foreign Origin. | Each returns 403 and no authenticated session is created. |
| CSRF-03 | Use one browser's token with another browser's cookie. | Sign-in returns 403. |
| CSRF-04 | Sign in correctly, then use the token from before sign-in to change a setting. | The cookie rotates, the old token returns 403 and the setting stays unchanged. |
| CSRF-05 | Call all 17 unsafe browser routes with a session but no token. | POST, PUT and DELETE return 403 before the action. Includes Ask, discovery and sign-out. |
| CSRF-06 | Request GET sign-out after a rejected POST sign-out. | GET returns 405 and the session still works. |
| CSRF-07 | Change and restore an Editions preference with fresh tokens. | Both changes succeed and readback confirms the result. |
| CSRF-08 | Sign out with a valid token and cookie. | POST succeeds, the session cookie is removed and identity returns 401. |
| HTTPS-CSRF-01 | Bootstrap under HTTPS cookie settings. | Secure, HttpOnly and Strict are set. |
| HTTPS-CSRF-02 | Use a trusted HTTPS Origin with and without a token. | Only the valid cookie/token pair succeeds. |
| HTTPS-CSRF-03 | Omit Origin and vary HTTPS Referer. | Missing, insecure or foreign Referer is rejected; trusted HTTPS Referer succeeds. |
| HTTPS-CSRF-04 | Mark a browser view CSRF exempt as DRF does. | The browser middleware still checks the token and origin and returns the redacted JSON refusal. |

Run the four isolated HTTPS checks in the pinned app container:

```sh
docker compose --env-file /private/tmp/keeplane-accounts-trial/.env exec -T app \
  python - < tests/unit/test_browser_csrf.py
```

The managed and existing-gateway TLS suites obtain tokens through the verified
ingress before signing in or making changes. The browser suite also exercises
real React sign-in/sign-out and the static sign-in/Editions/sign-out journey.
