# Offline emulator smoke checks

## Scope and safety boundary

The manual **Offline Android emulator smoke tests** workflow can run only from the trusted
`4.0-dev` default branch. It uses standard `ubuntu-24.04` runners, read-only repository
permission, SHA-pinned actions and a fixed matrix with `max-parallel: 1`.
`api_scope` defaults to `35-and-37`; selecting `37` runs only the primary diagnostic.
No arbitrary API, image or shell input is accepted. Every selected job
requires the default-false `allow_kvm_access` dispatch input to be explicitly enabled
under the owner's approval for that dispatch, and `github.run_attempt == 1`:

- Primary: API 37, `system-images;android-37.0;google_apis;x86_64`
- Regression: API 35, `system-images;android-35;google_apis;x86_64`

Local host-only tests do not establish an Android build, real KVM permission change,
ACL restoration on a hosted runner, or emulator pass. Earlier hosted diagnostics found
`/dev/kvm` (character device 10:232), owner 0, group 993, mode 0660. The runner was UID
1001 with groups 1001, 4, 100, 118 and 999, without read/write access. Those diagnostics
do not establish a successful runtime test. The available development container had
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

## What the eleven tests actually exercise

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
6. A separate direct foreground=false check isolates the controller command guards; it
   supplements, rather than replaces, the actual Activity lifecycle test.

Cases 4 and 5 use AndroidX `StateRestorationTester`: they exercise Compose saved-state
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
result verifier requires all eleven cases in the four expected classes, with no skips,
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

### Disposable data-partition capacity and install preflight

Run `38234454811` reached a booted API37 emulator and passed the actual target/test APK
isolation checks, then PackageInstaller rejected the first install with “Requested internal
only, but not enough space.” The retained reports contain no APK file sizes, guest `/data`
free-block counts or AVD partition configuration for that failed runner. Its exact free
space and active partition size are therefore unknown; the SDK source's generic defaults
are not evidence of that runner's effective configuration.

The workflow now requests a fresh **6144 MiB** partition with the official
`-partition-size 6144` option and existing `-wipe-data`. Android's command-line documentation
describes this option; the official emulator source explicitly applies it to the data
partition, overriding the AVD setting. It is a capacity configuration for a new disposable
AVD, not a guest remount or change to Android's storage/install safeguards. Runtime
confirmation of the larger filesystem remains pending until the next authorized run.

Two read-only capacity checks provide measured diagnostics:

1. Before requesting KVM access, the host check reads both verified APK file sizes and
   their ZIP entry metadata without extraction. It requires temporary host disk space for
   the complete 6144 MiB data image plus the install allowance below. It does not delete
   unrelated runner files to make room.
2. After boot and the APK hash recheck, before **either** `adb install`, the guest check
   reads `stat -f -c %S,%b,%f,%a /data` and `df -Pk /data` through the explicit emulator
   serial. Each query has a 15-second timeout. It records block size, total/free/available
   block counts, df byte counts and each APK's compressed/uncompressed size. It uses the
   lower available-space measurement and fails closed on missing, malformed or
   insufficient data.

Toybox `df` selects a mount with the requested path's device identity and can report a
bind-mount alias rather than the literal `/data` path. The parser still requires exactly
one df data row, explicit KiB units and valid numeric accounting. For an alias it performs
one additional read-only `stat -L -c %d /data <reported_mount>` probe and requires exactly
two equal positive device IDs. The alias must first pass a 192-character absolute-path
allowlist with no whitespace, shell metacharacters, empty components or `.`/`..` segments;
an unsafe path never becomes an adb shell argument. Literal `/data` needs no identity
probe. Identity failure or uncertainty blocks installation; statfs alone cannot pass.
See [Android Toybox df source](https://android.googlesource.com/platform/external/toybox/+/7aa651a/toys/posix/df.c)
and [Toybox stat formats](https://raw.githubusercontent.com/landley/toybox/master/toys/other/stat.c).

Run `38270265662` stopped before installation with “Unexpected guest /data df output.”
Its retained report omitted df stdout/stderr and the earlier successful statfs parse,
so the exact unexpected format or mount name cannot be reconstructed. A mount alias is
a source-supported possibility, not an observed diagnosis. Regression fixtures for the
parser are synthetic/source-derived, not captured API37 output; runtime validation of
this parser change remains pending.

The install allowance is `2 × combined APK bytes + combined uncompressed ZIP entry bytes
+ 1 GiB reserve`. The two copies allow for staging and installed APKs; full ZIP entry sizes
conservatively include extracted content; the reserve leaves room for dex/runtime growth
and the OS low-space margin. This is a documented planning heuristic, not a claim to
reproduce PackageInstaller's exact allocation policy or guarantee installation. Android
remains the final authority. No low-storage checks, permissions, install-location policy
or threshold settings are disabled or changed.

`storage-host.json` and `storage-guest.json` contain the numeric measurements, formula
inputs and short status/error. Guest reports also retain each fixed probe's exit or
timeout status, parse stage and stdout/stderr previews capped at 128 characters each,
with original character counts and truncation flags. Non-ASCII/control characters are
replaced for printable diagnostics; previews can be shortened further to preserve the
total report limit without trimming numerical evidence. A later failure preserves earlier parsed evidence
without granting permission to install. Reports are each capped at **4 KiB** and retained
for three days with the other allowlisted reports; they include no filesystem dump,
application data or APK contents. A failed preflight writes the bounded diagnostic report
and fails the job; ordinary emulator/KVM/key cleanup still runs.

### Explicit one-run KVM access

The owner-approved dispatch covers only these two disposable API37/API35 runners. Keep
`allow_kvm_access` false unless the owner has approved that particular dispatch. The input
is a record of dispatch approval, not blanket permission for later runs. GitHub's **Re-run
jobs** path is deliberately blocked, even when it inherits a true input: a retry requires
a fresh owner-approved dispatch. A false input skips both matrix jobs; it is not a passing
runtime result.

`scripts/kvm_access.py check` first records small numeric device/runner diagnostics without
changing access. The helper grants access only **after** both isolated APKs have been built,
verified to lack INTERNET, checked for disposable debug signatures, copied and hashed.
It independently requires a manual first-attempt run on the trusted default branch, an
explicit true input, matrix API 35 or 37, and actual/effective UID **1001**. Missing KVM,
`getfacl`, `setfacl` or noninteractive `sudo` support is a failure; no extra utility or
package installation is attempted.

If access already exists, no ACL change or snapshot is made. Otherwise, the helper accepts
only the observed simple root-owned 0660 ACL on character device **10:232**, with no
extended or default ACL entries. Rejecting an unexpected extended ACL avoids accidentally
widening another user's masked permissions. It saves the original numeric ACL and device
identity in a private 0700 directory with 0600 files under `RUNNER_TEMP`, before running
only `sudo -n setfacl -m u:1001:rw /dev/kvm`. The helper verifies the resulting ACL contains
only that added UID and the required mask, and confirms read/write access. It never makes
the device world-writable, changes groups, writes udev rules, or changes another host
file. Only this brief interval grants every process running as UID 1001 access
to KVM, so trusted source and a disposable runner remain important.

The official `emulator -accel-check` must then succeed. CPU-only emulation is never
silently substituted. No paid/larger runner is used.

Separate `always()` cleanup steps stop the emulator, restore the original ACL, and remove
the disposable debug key/APKs/AVD and logs. Restoration parses and validates the saved
single-device numeric ACL, validates its run/API binding and unchanged device identity,
and rejects symlink or hardlinked state files and symlink parent paths. The validated ACL
is supplied through stdin to fixed-target `sudo -n setfacl --set-file=- /dev/kvm`; privileged
multi-target `--restore` is not used. Exact original numeric `getfacl` output, mode, owner,
group and device identity must all match after restoration. The private ACL snapshot is
then removed, including after an ordinary restoration failure. Unsafe/tampered state is
rejected rather than followed; the disposable runner is subsequently discarded.

A restoration or state-cleanup failure fails the job and is retained in the small
`kvm-restoration.json` report. It cannot prevent the later always-run debug-key cleanup
or artifact reporting, and is never converted to a skipped/successful check. As with any
CI cleanup, abrupt runner loss or a forced platform termination can prevent cleanup code
from executing; the runner itself is disposable. Mocked host tests exercise these guards
and failure paths but do not prove real hosted ACL restoration or emulator execution.

## Reports and reproduction

The workflow uploads only allowlisted small text/JSON reports for three days: package
versions, acceleration result, device API, packaged-manifest proof and instrumentation
results, plus numeric KVM diagnostics/restoration status, storage preflight measurements,
and bounded installation diagnostics. A failure-only termination summary contains fixed
parsed fields; raw guest log data is discarded in memory and never archived.
KVM, storage and install reports are capped at 4 KiB and other files at 2 MiB. The private original ACL/state is never uploaded. It does
not upload APKs, signing keys, raw emulator logs, logcat, screenshots, heap dumps, AVD
snapshots or Android userdata.

Host checks (these do not need an SDK):

```sh
python3 scripts/test_offline_smoke.py
python3 scripts/test_emulator_storage.py
python3 scripts/test_kvm_access.py
python3 scripts/test_install_termination.py
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
- [Emulator command-line options, including partition sizing](https://developer.android.com/studio/run/emulator-commandline)
- [Official emulator data-partition option handling](https://android.googlesource.com/platform/external/qemu/+/emu-master-dev/android/android-emu/android/main-common.c)
- [ActivityResultRegistry testing](https://developer.android.com/training/basics/intents/result#test)
- [Compose StateRestorationTester](https://developer.android.com/reference/kotlin/androidx/compose/ui/test/junit4/StateRestorationTester)

## Verified run at 9055b6c5

[Run 38329127641](https://github.com/IllyasvielEin/TiebaLite/actions/runs/38329127641)
passed all 11 API35 smoke cases, including actual Activity/Compose-owner background
checks and the separate direct foreground-gate test. This does not establish why the
older run failed. API37 passed APK, storage and package-readiness checks but its first
installation failed; the subsequent sample found no system_server PID or package
service. No API37 tests ran and the process-loss cause remains unknown. Both temporary
KVM ACLs were restored and independently checked against the uploaded reports.
A further dispatch requires approval for its selected temporary runner(s).
