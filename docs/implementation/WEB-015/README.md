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
