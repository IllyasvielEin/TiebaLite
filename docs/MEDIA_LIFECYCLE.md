# Media ownership and validation

## Scope

This change retains inline/fullscreen video, preview seeking, playback gestures,
and one-at-a-time voice playback. It does not enable native publication, add a
background playback service, change application identity/signing, or install an APK.

## Ownership rules

- `rememberVideoPlayerController` owns initialization and final release, outside
  the inline/fullscreen presentation branches. Moving the surface does not release
  the engine. A changed media source gets a new controller lifetime. Saved progress
  and fullscreen state are restored only when a SHA-256 source discriminator matches.
  Different URLs, header variants, or raw resources start fresh; legacy untagged
  state also starts fresh. Raw source URLs/headers and cached thumbnail URLs are not
  persisted in the saved-state envelope.
- Fullscreen presentation temporarily changes system bars/orientation and restores
  their previous values when dismissed or removed. Platform large-screen
  orientation policy may override landscape requests; do not rely on that request
  to recreate the Activity.
- Video release cancels progress, controls, delayed hide and preview-seek jobs,
  detaches both surfaces, removes the listener, and releases only existing engines.
  `PlaybackResource` forbids implicit creation after release. Initialization is an
  explicit operation.
- On the supported API35+ range, `ON_STOP` pauses video and blocks delayed play/seek
  actions. `ON_START`/`ON_RESUME` permit user playback, and initial foreground state
  uses the `STARTED` threshold. Returning to the foreground does not auto-resume. The engine remains owned by the composition until final
  disposal; this is foreground-only playback, not a background playback service.
- Voice `Manager` owns one application-context engine. A row only binds by object
  identity. Disposing a different or previous row cannot release the current row.
  View detach/final release and the owning Activity's stop release the active
  binding. The unreachable API23 pause-only release branch has been removed.
- Voice playback has one main-thread progress job, running only while playing.
  There are no per-row timers or wrappers retaining released shared engines.

## Offline checks

Run:

```sh
python3 scripts/test_media_lifecycle.py -v
python3 app/src/test/compatibility/check_compose_compatibility.py -v
```

The media script includes seven source-wiring checks and one executable Java harness
covering ten ownership/resource/source-identity scenarios. It needs a JDK, but no Android SDK,
device, account, or network. The same ten scenarios have JUnit wrappers for the
normal Gradle test suite.

These checks prove the pure helpers' behavior and guard selected source wiring.
They do not compile the Kotlin Android code or simulate Compose disposal, Media3
callbacks, coroutine scheduling, codecs, focus, or a device memory leak. Full
Gradle compilation, lint, unit tests and device validation remain required.

## Device/emulator regression matrix

Use an authorized emulator/test device and non-account test media. Android17/API37
is the primary current-platform target; also cover Android15/API35 at the approved
minimum, with Android16/API36 optional. Older retained branches are not supported
installation test lanes. Do not treat emulator success as hardware
decoder, audio-route, or memory validation on every real device.

1. Play video inline; toggle fullscreen/back 20 times; repeat while paused and
   buffering. Verify playback position, surface binding, buttons and gestures.
2. Leave navigation while fullscreen. Verify original system bars and orientation
   are restored. Test a >=600dp window, split-screen and resizing while paused.
3. Replace source A with B at the same UI position; verify B's source/thumbnail and
   that old progress callbacks cannot update B. Recreate saved state and verify the
   selected source and position remain appropriate.
4. Home/Back/return and any supported window/PiP flow: assert actual playback and
   audio focus state, not only absence of exceptions. Foreground return must not
   auto-play. Android17 can reject background audio interactions without throwing.
5. Display voice rows A/B: play A and remove B, then play B and remove A. The active
   row must continue. Removing the active row stops it. Return/replay, repeated
   play/pause, buffering, completion and network-error retry must work.
6. Navigate between Activities while voice is playing. A late stop from the old
   Activity must not release playback owned by a different Activity.
7. Observe player create/release counts, coroutine/timer/thread activity and heap
   references after final exit. Source inspection alone is not a leak measurement.

## References

- [Compose effects and lifecycle keys](https://developer.android.com/develop/ui/compose/side-effects)
- [Views in Compose and final release](https://developer.android.com/develop/ui/compose/migrate/interoperability-apis/views-in-compose)
- [Media3 player lifecycle](https://developer.android.com/media/implement/playback-app)
- [Android17 background audio changes](https://developer.android.com/about/versions/17/changes/bg-audio)
