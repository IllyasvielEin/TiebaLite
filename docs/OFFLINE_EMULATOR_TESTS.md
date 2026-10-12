# Offline emulator smoke checks

## Scope and safety boundary

The manual **Offline Android emulator smoke tests** workflow can run only from the trusted
`4.0-dev` default branch. It uses standard `ubuntu-24.04` runners, read-only repository
permission, SHA-pinned actions and a two-entry matrix with `max-parallel: 1`:

- Primary: API 37, `system-images;android-37.0;google_apis;x86_64`
- Regression: API 35, `system-images;android-35;google_apis;x86_64`

No workflow was dispatched as part of writing these files. Local host-only tests do not
establish an Android build or emulator pass. The available development container had
neither an Android SDK/JDK 17 toolchain nor `/dev/kvm`; runtime results remain pending
until a separately approved run actually succeeds. Local Gradle 9.8.1/Java21 configuration
confirmed the smoke assemble/test tasks are registered. A direct invocation of the
project's cached official manifest-merger 32.1.1 merged production main + smoke overlay:
only the smoke Activity and fixture provider remained, Application was inert, and INTERNET
was absent. This source-merge check is not a substitute for the complete dependency-merged
APK proof that the workflow requires before installation.

`-PofflineSmoke=true` creates a `smoke` build type from `debug` and selects its instrumented
tests. It explicitly uses Gradle's normal disposable debug signing configuration. The
fresh runner places the generated key in a temporary Android user home, never accepts
`keystore.properties`, never receives signing secrets, and removes its key and AVD at
cleanup. This workflow does not build, sign or publish a release APK. Normal debug and
release settings do not change when the smoke property is absent.

The target keeps `io.github.illyasvielein.tiebalite`; only Android's ordinary instrumentation
package has the `.test` suffix. **Run on the dedicated disposable emulator, not an existing
personal-device installation with this same application ID.**

The smoke manifest replaces the account-aware `App` with plain `android.app.Application`,
removes production activities/aliases, all services/receivers and all startup providers,
and adds only an isolated host and a non-exported synthetic-fixture FileProvider. Its
provider exposes only `cache/smoke-fixtures/`. The host installs a minimal color resolver
for the production voice view; it does not initialize accounts or real theme preferences.

Both target and instrumentation manifests remove `INTERNET`, including the SDK-specific
permission tag. Before **either** APK is installed, `verify_offline_apks.py` uses the SDK's
official `aapt2` on both actual APKs and fails if INTERNET is present. It also checks the
IDs, target SDK bounds, inert Application and restricted component set. Verified APKs
are copied to a private temporary directory, hashed, rechecked and installed directly;
no Gradle rebuild takes place between permission verification and installation. A device
test independently verifies both installed packages lack that permission.

This blocks direct app network access. It is not a whole-runner or whole-Android-OS
network firewall: SDK/Gradle setup needs network and the Google system image has its own
system services. No production account, Tieba login, upload, post or account mutation is
part of any test.

## What the ten tests actually exercise

### Real Android runtime and production media code

`MediaControllerSmokeTest` runs the production `rememberVideoPlayerController`, Compose
saver, `PlayerSurface` and Media3 player. The small bundled WAVs are generated synthetic
eight-second silence, with no external downloads or personal media.

1. Preparing a real local media source reaches READY with the expected duration; moving
   its PlayerView and disposing the old view keeps the current owner attached.
2. Release cancels a pending delayed preview seek, detaches both views, is repeatable,
   and late playback/seek/surface calls do not recreate a released player.
3. An actual Activity STOP pauses playback, rejects playback and seeks while stopped,
   and allows an explicit new play after resume.
4. The production Compose saver creates a fresh controller and restores progress for
   the same raw resource.
5. A saved state belonging to source A is rejected when the reconstructed composition
   requests source B.

The last two use AndroidX `StateRestorationTester`: they exercise Compose saved-state
restoration, **not full OS process death or all Activity/ViewModel recreation behavior**.
The local media is audio in the video controller; codec-specific video rendering,
fullscreen animation, DRM, network headers and physical-device decoder behavior are
not established by these checks.

`VoiceOwnershipSmokeTest` constructs real `VoicePlayerView`s and the production Manager.
It switches owner rows, removes/releases an unrelated row, proves that stale row cannot
pause the active one, tests repeated release, and verifies context-scoped cleanup. Its
`isPlaying` assertion is the Manager's play-request/ownership contract, not acoustic
output; decoding readiness is covered separately by the controller tests.

### Injected picker contract results (not a system success selection)

`PickerContractSmokeTest` registers independent avatar/theme-style single-image AndroidX
contracts with an injected `ActivityResultRegistry`. It exercises AndroidX result
parsing and the actual production `isPickerContentUri` gate, including:

- Cancel, null successful result and cancel carrying a URI keep the previous selection
- `file:`, HTTPS and missing-authority URIs are rejected
- A generated two-pixel PNG from the fixture provider is accepted and actually readable
- Production `getClipDataUris` deduplicates and filters mixed data/ClipData payloads
- Both installed APKs lack INTERNET and the target Application is inert

The avatar/theme callback harness is intentionally isolated. It does **not** instantiate
`EditProfileActivity` or `TranslucentThemeActivity`, prove Glide/Sketch crop pipelines,
change a stored background, upload a portrait, test revoked URI grants or simulate a
successful system picker selection. Existing `check_image_picker.py` source guards
separately check the production screens remain wired to the tested contract/policy.

### Actual system picker UI

`SystemPickerSmokeTest` invokes the real `ACTION_PICK_IMAGES` image picker, resolves the
system package, waits for its cross-app UI, presses Back, and verifies a cancellation
callback with unchanged selection. It repeats this launch/cancel cycle twice without
injected registry results. It does not mock the system picker and does not select an item.

Each UI wait is bounded. AndroidJUnitRunner has a 45-second per-test limit, instrumentation
has a ten-minute hard limit, emulator boot and workflow steps also have deadlines. The
result verifier requires all ten cases in the four expected classes, with no skips,
failures, empty run or crashed runner accepted as success.

## SDK and runner requirements

Use only the preinstalled official `sdkmanager`/`avdmanager`; the shared
`ensure_android_sdk.py emulator35|emulator37` helper installs a fixed selected set of
official packages under the user's approved Android SDK license grant. It does not
bootstrap an unofficial SDK, use an emulator-runner action, or accept unrelated SDK
licenses with a blanket `--licenses` command.

The official repository feeds were checked on 2026-10-12:

- `platforms;android-37.0`: revision 2
- API37.0 Google APIs x86_64 image: revision 6
- API35 Google APIs x86_64 image: revision 9
- Stable emulator: 37.2.12
- Both image packages reference `android-sdk-license`

The feeds and official release notes differ in what they describe: image package metadata
has an older installation minimum, while emulator 37.1.11 added API37 Vulkan extensions.
This workflow conservatively requires emulator **37.1.11 or newer**, uses `-gpu software`
without disabling Vulkan, and allocates **4096 MB** for API37. It records the actually
installed revisions, verifies `pixel_7` exists in the installed official AVD device inventory,
and confirms the booted device SDK. SDK package revisions are not
immutable; the saved report identifies the versions used by each run.

The workflow requires an already-readable/writable `/dev/kvm` and a successful official
`emulator -accel-check`. Missing access is an actionable blocker, never a skipped pass.
It does not change device permissions, groups, udev rules, host security settings or use
a paid/larger runner. CPU-only emulation is not silently substituted.

## Reports and reproduction

The workflow uploads only allowlisted small text/JSON reports for three days: package
versions, acceleration result, device API, packaged-manifest proof and instrumentation
results. Each file is capped at 2 MiB. It does not upload APKs, signing keys, raw emulator
logs, logcat, screenshots, heap dumps, AVD snapshots or Android userdata.

Host checks (these do not need an SDK):

```sh
python3 scripts/test_offline_smoke.py
python3 app/src/test/compatibility/check_image_picker.py
```

To assemble the isolated test pair in an already configured authorized SDK environment:

```sh
./gradlew -PofflineSmoke=true :app:assembleSmoke :app:assembleSmokeAndroidTest
```

Use the workflow's aapt2 permission verification and hash-preserving direct-adb sequence
before installing. Do not call `connectedSmokeAndroidTest` first; it can install APKs
before these explicit checks. Successful runtime reporting requires
`scripts/verify_smoke_results.py`, not just adb's exit code.

## Official references

- [Google system-image repository feed](https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml)
- [Google SDK repository feed](https://dl.google.com/android/repository/repository2-3.xml)
- [SDK Manager](https://developer.android.com/tools/sdkmanager)
- [Android SDK terms](https://developer.android.com/studio/terms)
- [Emulator release notes](https://developer.android.com/studio/releases/emulator)
- [Emulator acceleration and rendering modes](https://developer.android.com/studio/run/emulator-acceleration)
- [Emulator command-line options](https://developer.android.com/studio/run/emulator-commandline)
- [ActivityResultRegistry testing](https://developer.android.com/training/basics/intents/result#test)
- [Compose StateRestorationTester](https://developer.android.com/reference/kotlin/androidx/compose/ui/test/junit4/StateRestorationTester)
