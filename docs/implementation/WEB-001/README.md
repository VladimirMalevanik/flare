# WEB-001: Funny mode

Funny mode is an optional browser preference under Settings → Appearance & Theme.
It adds a colorful light/dark theme, a Magic 8-ball capture control, short synthesized
button sounds and English fortune lines. It is off by default. Funny sounds can
be muted independently; both preferences survive refresh in this browser.

## Behavior

1. Enable Funny mode and open Flares.
2. Click Analyze today. The ball says “Nah, dude. Shake the ball.” No analysis
   request is sent at this point.
3. Drag the ball back and forth with a mouse or finger. Four substantial direction
   reversals start the existing analysis flow. Alternatively focus the ball and
   press Space or Enter four times; holding a key does not count as repeated shakes.
4. While analysis is pending, additional shakes change the fortune without
   creating additional analysis requests. Real results, empty results and errors
   produce distinct feedback. The ball cannot guarantee that evidence yields a Flare.
5. Cancel an unstarted ritual using Cancel or Escape. Opening capture or disabling
   Funny mode also cancels an unstarted ritual. Already queued analysis continues.

Reading an existing daily run does not require shaking and does not enqueue a
new run. The server's once-per-day limit and workspace access rules remain authoritative.
Idle clicks still open capture; idle dragging still repositions it. Voice capture
pauses funny audio before requesting microphone access. Reduced-motion preferences
disable decorative motion; keyboard controls remain available.

## Validation on October 2, 2026

- All 95 frontend tests passed, including 11 Funny mode tests. These execute the
  actual AnalyzeAction, Capture and workspace hooks with deterministic harnesses,
  as well as the existing AnalyzeController. They cover mouse/touch reversals,
  keyboard repeat, single enqueue, viewer/quota guards, capture/mode cancellation,
  resumed runs, day changes, preference persistence and audio cleanup/voice pause.
- Whole-frontend ESLint, TypeScript and production build passed.
- Browser checks passed for default off, saved mode/mute preferences, light/dark
  appearance, normal-mode restoration and a 390 × 844 mobile viewport. The fortune
  area reserves space above the feed heading.
- A local production build was exercised against a loopback-only synthetic API.
  After three keyboard shakes it recorded zero POSTs; the fourth produced one
  POST. Additional shakes while processing kept that count at one. The actual
  HTTP/polling path displayed completion with five selected sections and zero
  Flares honestly. A separate HTTP 409 fixture displayed the daily-limit error.
- The demo provider's success path displayed real demo Flare cards after shaking.
- A separate agent reviewed the final diff and found no remaining actionable issue.

Browser QA used synthetic accounts/data. It did not call the production AI service
or access user recordings. Physical device accelerometer shaking is not implemented;
touch dragging and keyboard input are the supported gestures. Microphone recording
was covered by regression tests, without capturing live audio during browser QA.
Speech/audio availability depends on browser support and autoplay policy; on-screen
instructions always work. No dependencies, backend, schema or cloud settings changed.

## Handoff

Branch: `task/web-001-funny-mode-20261002`.
Task state: review after publication. Product acceptance, merge and deployment
remain separate steps; this feature is not live on flare4u.tech yet.

For a local preview use the existing frontend demo mode:

```sh
cd frontend
NEXT_PUBLIC_DATA_PROVIDER=mock npm run dev -- --webpack --hostname 127.0.0.1 --port 3102
```

Implementation uses standard [Pointer Events](https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events),
[Web Audio](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API) and
[React effect cleanup](https://react.dev/reference/react/useEffect).
