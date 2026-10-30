# WEB-015 — password visibility and journey recheck

Owner request: show/hide eyes on passwords, then revisit the whole CJM after the
merged fixes. This extends existing Flare auth forms, with no new dependency.

Reference lock: existing AuthForm and PasswordRecovery panels, current input
spacing/borders/colors, Heroicons outline1.8 and existing focus styling. Refero
forms/icons craft supplies a44px touch target, explicit input labels and keyboard
focus. React input documentation supplies stable input identity and type=button.

| Decision | Reference | Reason |
| --- | --- | --- |
| Reuse Eye/EyeSlash from the installed Heroicons set | Existing Icon component | Same visual language; no invented icon or library |
| One shared labelled field for login/register/reset/confirmation | Existing auth forms | Consistent behavior and password-manager autocomplete |
| Explicit label beside the wrapper | React input docs | Avoid two labelable controls inside one implicit label |
| Visible action is Show/Hide, EN/ES, with aria-controls | Forms/accessibility craft | Explain the action to screen-reader and keyboard users |
| Keep one input DOM node and a non-submitting eye | React input docs | Keep value, native validation and form payload unchanged |
| Prevent pointer focus transfer; retain keyboard button focus | Existing form focus language | Keep typing comfortable; preserve keyboard access |

Password visibility starts masked and stays local to that mounted field. No value
or visibility is stored or logged. Existing validation, consent, legal fields,
reset tokens, requests and successful navigation are preserved. New-password and
confirmation fields toggle independently. Pending forms disable their controls.

The second pass classifies all42 existing CJM cases by current automated/browser
proof and remaining server/external acceptance. Local checks use isolated synthetic
accounts; production, paid calls, real mail and real provider accounts are separate.
API-005 remains Vova's task, with no changes to generation or budgets.


## Verification replay found during the second pass

The full-source browser exposed Q02: React effect setup/cleanup/setup issued two
requests for the one-use verification link. The first succeeded; the second showed
an invalid-link screen even though /auth/me already reported emailVerified=true.
Reuse the pending attempt in a component-local ref and attach the active effect to
its result. Unmount fences remain in place. Different links get fresh keyed state;
there is no global/persistent token cache and backend token semantics are unchanged.
Regression tests cover successful and invalid replay and late unmounted results.

## Local journey acceptance

A full-source local app uses actual routing, auth/session, API and restricted
PostgreSQL with synthetic accounts, a memory inbox and isolated ZIP storage.
Telemetry is explicitly off; the fixture alone aliases its missing reused SDK so
it can compile. This does not change product source or establish a production
build; the exact locked CI build is required. No mail/provider/AI/payment network
calls occur. Actual browser checks confirm input DOM identity, unchanged password,
selection and pointer focus, a non-submitting eye, visible keyboard focus and
registration/verification/navigation/persistence. Mobile and recovery results are
recorded with the completed map recheck.
