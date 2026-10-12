# Bounded offline APK installation

Run `38275237917` passed measured storage capacity and the packaged APK isolation/hash
gates, then the first default/streamed target install reported
`cmd: Failure calling service package: Broken pipe (32)`. No package-service stack was
captured. A crash, OOM or streaming-specific cause is **not established**.

In the [official cmd source](https://android.googlesource.com/platform/frameworks/native/+/refs/heads/main/cmds/cmd/cmd.cpp),
this diagnostic follows a negative `IBinder::shellCommand` result after obtaining a service
handle. That identifies a failed call, not its underlying cause. The
[official adb install source](https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/client/adb_install.cpp)
chooses the default transport from device features. The helper keeps `adb install -t`
unchanged; it adds no transport override or replay.

## Caller contract

After both packaged manifests, debug signatures, hashes and storage capacity have passed:

```sh
python3 scripts/install_offline_apks.py \
  --apks "$RUNNER_TEMP/offline-apks" \
  --adb "$ANDROID_HOME/platform-tools/adb" \
  --serial emulator-5554 \
  --report out/smoke-reports/install-diagnostics.json
```

The directory must contain exactly nonempty, regular, singly linked `target.apk` and
`test.apk`, plus an optional equally guarded `SHA256SUMS`. Other entries, file/directory
symlinks and symlink parent paths are rejected. The helper does not verify manifest or
signature isolation itself, read/write APK contents, or replace the caller's hash gate.
The report must have the fixed filename `install-diagnostics.json` outside this directory.
Only the fixed disposable serial is accepted.

## Readiness and one attempt per role

A monotonic **60-second** readiness deadline contains three fixed read-only probes, each
limited to **5 seconds** and the remaining deadline:

- `getprop sys.boot_completed`: exactly `1`
- `pidof system_server`: exactly one positive PID
- `cmd package path android`: nonempty, well-formed absolute APK package paths

Two fully successful samples must retain the same PID and be separated by at least
**2 seconds**. A failed/unknown sample or PID change resets stability. Nonzero exits,
timeouts, malformed/oversized output and invalid UTF-8 cannot pass. This is a readiness
observation, not a guarantee that a later service call cannot fail.

The helper installs the target once, then the test APK once only if the target succeeded.
Each install has a **90-second** timeout and requires exit zero plus exactly one whole
`Success` stdout line. Failure or timeout blocks further installation and returns nonzero.
There is no retry, reboot, transport change, SDK installation or guest/host permission change.

After both successes or an adb-stage failure, one **15-second** read-only snapshot repeats
the same three probes. Snapshot uncertainty is recorded and never replaces the original
install failure or exit/timeout evidence. After both installs succeed, the snapshot must
also be fully ready: timeout, malformed/unknown output or a not-ready observation fails
the distinct `post_install_health` stage and blocks instrumentation. This snapshot is
still not a substitute for the separate instrumentation runtime gate. A global
**270-second** command deadline leaves at least **30 seconds** of the workflow's five-minute
install step for the bounded report; the ordinary maximum command budgets total 255
seconds. Guest storage preflight runs in a separate step before this helper.
Existing workflow emulator/key cleanup and exact KVM ACL restoration remain responsible
for cleanup even when this helper fails.

## Small retained evidence

The JSON report is capped at **4 KiB**. It records role/stage, elapsed milliseconds,
command exit/timeout/error status, configured command timeout, readiness sample/PID-change
counts, per-probe status/parse counts and latest observations, both install results and the
final snapshot. Repeated readiness samples use fixed-size aggregate counts rather than an
unbounded history. UTF-8 replacement decoding and printable ASCII previews prevent control
bytes from reaching terminal diagnostics. Each stdout/stderr preview is at most 128
characters with original byte/character counts and exact omitted-character counts.
Only previews are shortened to fit, starting with readiness/snapshot previews; numeric and
status evidence is preserved. No logcat, raw emulator log, environment, secrets, APK bytes
or app data are collected. Workflow report retention/allowlisting remains separate.

`python3 scripts/test_offline_install.py` exercises these guards with mocked subprocesses
and a synthetic monotonic clock, including invalid byte streams. It does not prove actual
API37/API35 installation or instrumentation success; that requires an authorized emulator run.
