# Avatar diagnostic build

This build adds **Settings → 头像加载诊断**. Recording is disabled on every process
start and is not saved as a preference. Enable it, return to a post and refresh,
then return to the diagnostic page and copy the report. Normal avatar/profile
taps and existing long-press actions are unchanged. Enabling or clearing the
observer does not replace an image request or trigger a diagnostic download.

The report contains at most 40 events. It is memory-only; disabling, clearing, or
restarting clears the session. Clearing and disabling invalidate outstanding
event leases, so their late results cannot refill the cleared session. The copy
button reads a fresh snapshot rather than a previously rendered report.

## Scope and interpretation

- `AVATAR`: observed display-state transitions from the shared String Avatar.
- `AVATAR_SNAPSHOT`: current display state; it may have loaded before recording
  was enabled. Fast memory-cache results may also appear as snapshots.
- `NETWORK`: stages of existing image-client requests for the known
  `tb.himg.baidu.com` and `himg.bdimg.com` normal `/sys/portrait/item/` and
  large `/sys/portraith/item/` routes.
- Network `host` is the original request host, before legacy route migration. It
  does not prove the actual contacted host. A redirect's scheme and host
  bucket can be shown, but a later failure is not proof of failure at that
  original host. The network listener does not cover arbitrary avatar hosts.
- Entries are independent. They are not joined by timing or identity. Missing
  network entries do not establish a cache hit; the success stage reflects the
  actual Sketch data source when available.
- `OBSERVATION_ENDED` means the display observer left composition. It does not
  claim that a network request was cancelled.
- Main-floor avatars classify the original portrait field as empty, ID, URL,
  local or other. Other shared Avatar callers classify their supplied image URI.

Only fixed enum buckets, the allowlisted host, HTTP status, and bounded counts
are stored/exported. Unknown hosts become `other`. No portrait value, account
ID, full URL, path/query, header, raw exception message, runtime class name,
stack trace or request/response object enters the report or store. No analytics,
files, external sharing, system logging, or additional network request is added.
Copying to the local clipboard happens only when the user presses the button.

The anonymous image client's HTTPS upgrade/blocking, certificate/hostname
verification, empty cookie jar, credential stripping, and cross-scheme redirect
restriction remain unchanged. Existing policy rejections are represented by a
typed IOException with fixed reasons for safe classification.

## Verification

Run `python3 scripts/test_avatar_diagnostics.py` for pure JVM privacy/session
tests and source-wiring checks. It compiles the Java model at Java 17 source and
bytecode levels and runs without Android, an emulator, accounts, or network.
`AvatarDiagnosticStoreTest` runs the same scenarios in the existing Gradle unit
test lane. The source checks cover the supported Sketch 3.3.2 Compose state API:
DisplayRequest listeners are deliberately not installed because that version
rejects them in Compose.

These checks do not constitute on-device UI verification or diagnose the cause
of a real avatar failure. The ordinary signed APK build, lint, and unit-test
lane must pass before delivery; no emulator lane is required for this build.
