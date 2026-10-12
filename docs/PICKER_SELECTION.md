# Time picker correctness

Time preferences and callbacks retain the existing ASCII `HH:mm` contract. The
optional 12-hour picker API uses `HH:mm AM`/`HH:mm PM`. Its conversion goes through
hour-of-day values, so midnight is 12 AM and noon is 12 PM. Legacy localized
decimal-digit values remain readable; new serialization is locale-independent.
Malformed or out-of-range input throws `IllegalArgumentException` rather than
silently choosing midnight. Display numbers follow the current Android
configuration locale separately from persistence.

Hour/minute columns remain cyclic. AM/PM remains finite. A lifecycle-owned
observer settles each column and reports each distinct settled item, including
already-aligned changes. Parent echoes do not recenter the current cyclic item;
external value, mode, and item-list changes synchronize silently. A new user drag
can interrupt a snap without ending the observer. Owner cancellation propagates,
preventing callbacks after disposal.

The preference composes each edit session from the persisted value. Preview
changes are not reused after Cancel, Back, or outside dismissal. Confirm saves the
captured settled value once, and the saved callback receives that same value.
Confirm is disabled until every active column is initialized, idle and aligned
with the delivered time. The click handler rereads the actual positions before
accepting; a stale enabled frame cannot submit during a new drag or pending
reset. A per-session gate closes synchronously before Confirm or explicit Cancel
callbacks, rejecting repeated submissions and later preview delivery.

Back/outside dismissal keeps the existing shared dialog animation. Its session
gate closes when that dialog delivers its dismissal notification; this patch
does not add a new animation-start hook to `BaseDialog` or `AnyPopDialog`.
Preview callbacks during that closing animation are therefore not claimed to
stop immediately. A reopened/disposed preference still starts from persistence.

## Verification levels

- `PickerTimeTest`, `TimePickerPreferenceTest`, and `PickerSelectionTest` are JVM
  behavior tests, including conversion, locales, aligned changes, duplicate
  suppression, parent echoes, external requests, empty/data changes, interrupted
  mutations, owner cancellation, cyclic indices, and finite AM/PM boundaries.
- `PickerConfirmationTest` exercises pure readiness and session policies:
  scrolling, pending reset, stale selection/offset, finite alignment, invalid
  indices, stale enabled clicks, repeated/reentrant Confirm, Cancel and fresh
  sessions. These tests do not simulate a Compose frame, fling or dialog animation.
- `python3 scripts/test_time_picker.py` checks source wiring and executes the
  actual legacy Java formatter with small Android API stubs. It is not Compose
  runtime or Android layout validation.
- The new Kotlin/JVM tests have not run in this editing environment because a
  Kotlin compiler/Gradle distribution and Android SDK are unavailable. CI's
  `testReleaseUnitTest` must execute them; source/formatter passes do not stand
  in for that gate.
- Android runtime coverage is still required on API 35 and API 37. Exercise
  edit/cancel/reopen, Back/outside/reopen, confirm once, aligned scrolling,
  interrupted/repeated drags, dismissal during snap, parent echoes, external
  value/mode changes, list replacement, empty-to-nonempty, both AM/PM ends, and a
  configuration-locale change. Check the centered label and callback/saved value
  together. No runtime pass is implied by JVM or source checks.

Implementation follows the lifecycle and latest-value semantics in
[Compose side effects](https://developer.android.com/develop/ui/compose/side-effects).
