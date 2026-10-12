# Live browser security journeys

**Edition:** Open Source; the same browser contract applies to Enterprise.

| Case | Action | Expected result |
| --- | --- | --- |
| BSEC-01 | Sign in through React, open Users and sign out. | The live CSRF checks accept sign-in and a POST sign-out; the browser returns to sign-in and identity returns 401. No GET sign-out is sent. |
| BSEC-02 | Use static sign-in, change and restore an Editions preference, then sign out. | Both settings writes pass live CSRF checks, readback matches each value, the original preference is restored and POST sign-out removes access. |

Run `npm test -- security.spec.ts` from this directory. Set `KEEPLANE_BASE_URL`
for the kind preview. These journeys use real APIs; the other browser suites
also retain their mock refusal, timeout, keyboard and layout cases.
