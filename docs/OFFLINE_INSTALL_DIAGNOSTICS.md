# Bounded offline APK installation

> Archived on 2026-10-13 at the owner’s request. The workflow is preserved in
> `docs/archive/emulator.yml.disabled`, outside GitHub Actions discovery. The following
> describes the historical test setup; cloud emulator execution is no longer exposed.
> Build, unit-test, lint and optional signing checks remain in `build.yml`.

Run `38275237917` passed measured storage capacity and the packaged APK isolation/hash
gates, then the first default/streamed target install reported
`cmd: Failure calling service package: Broken pipe (32)`. No package-service stack was
captured. A crash, OOM or streaming-specific cause is **not established**.

In the [official cmd source](https://android.googlesource.com/platform/frameworks/native/+/refs/heads/main/cmds/cmd/cmd.cpp),
this diagnostic follows a negative `IBinder::shellCommand` result after obtaining a service
handle. That identifies a failed call, not its underlying cause. The
[official adb install source](https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/client/adb_install.cpp)
chooses the default transport from device features. The helper's default keeps
`adb install -t` unchanged; a separately selected `no-streaming` mode is described below.

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

### Explicit install transport comparison

`--transport` accepts only `default` (the default) or `no-streaming`. The former preserves
the exact baseline `adb -s emulator-5554 install -t VERIFIED_APK` arguments. It requests
ADB's default mode; it does not attest that ADB selected streaming. The latter emits
exactly `adb -s emulator-5554 install --no-streaming -t VERIFIED_APK` for each attempted
role. The [official ADB mode parser and selection](https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/client/adb_install.cpp#356)
map this explicit option to push installation without a fallback mode; the legacy
installer pushes the APK before invoking package installation.

The primary report records the fixed `requested_transport=default/no-streaming` enum,
including input/readiness failures. The helper never chooses a different transport from
probe or install results, falls back between these choices, or replays an install. Target
still runs once, followed by test once only on success. All readiness/health gates,
90-second role timeouts, 270-second shared command deadline, failure-only termination
collection and report limits are unchanged. This opt-in code supports a future separately
authorized comparison; mocked host tests do not establish either mode's API37 runtime
outcome or the cause of the observed service/process loss. Workflow input/wiring and
runtime authorization remain the caller's responsibility.

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
There is no retry, reboot, automatic transport change, SDK installation or guest/host permission change.

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

The JSON report is capped at **4 KiB**. It records the requested transport, role/stage, elapsed milliseconds,
command exit/timeout/error status, configured command timeout, readiness sample/PID-change
counts, per-probe status/parse counts and latest observations, both install results and the
final snapshot. Repeated readiness samples use fixed-size aggregate counts rather than an
unbounded history. UTF-8 replacement decoding and printable ASCII previews prevent control
bytes from reaching terminal diagnostics. Each stdout/stderr preview is at most 128
characters with original byte/character counts and exact omitted-character counts.
Only previews are shortened to fit, starting with readiness/snapshot previews; numeric and
status evidence is preserved. This report retains no logcat, raw emulator log,
environment, secrets, APK bytes or app data. Workflow report retention/allowlisting remains separate.

## Failure-only termination signatures

Run `38329127641` again reached two healthy API37 readiness samples (PID 1742), then the
target install returned Broken pipe. Its bounded post-failure snapshot found no
`system_server` PID and no package-service handle. This supports observed service/process
loss after the failed install; it does not identify a Java exception, native signal or OOM.
The API35 job passed all eleven cases. No raw API37 crash log was retained.

`install_termination.py` adds a separate best-effort `install-termination.json`, capped at
**4 KiB**, only after an actual target/test install attempt fails and the existing health
snapshot finishes. Input/readiness failure, successful installs, failed post-success health
or an install skipped for deadline exhaustion never trigger log collection. Diagnostic
failure cannot replace the original install result, stage, report or nonzero return.

After readiness and before the install sequence, two read-only **2-second** commands read
`pidof zygote64 zygote` and `date +%s.%N`. The system-server PID comes from stable readiness;
the zygote set must contain one or two distinct positive int32 PIDs. After failure another
2-second guest date read closes the sequence-wide window. Strict numeric seconds/nanoseconds
are required; missing, malformed, reversed or longer-than-210-second windows skip logcat.
The report labels `window_scope=install_sequence`, so the failed role supplies context,
not a claim that every observed event was caused by that single install command.

The single fixed logcat query uses `-d`, only `main/system/crash`, explicit
`threadtime,epoch,usec,printable`, silent defaults with `AndroidRuntime:E Zygote:I libc:F`,
and `-t` with the validated decimal start epoch. Decimal time is important: a bare integer
selects a line count. A dedicated nonblocking pipe reader stores at most **64 KiB stdout**
in memory and immediately discards stderr content, counting at most **1 KiB**. Its
**5-second** budget includes reserved kill/reap time. It has no temporary raw file,
console echo, generic command previews or unbounded `communicate()`. These added commands
share the 270-second deadline; ordinary command budgets total 266 seconds, preserving the
five-minute step's report-writing margin. Collection does not alter the selected transport,
SDK, permissions or retry policy.

Only anchored, bounded formatted headers within the guest window are considered. Zygote
templates must come from a captured zygote PID and reference the captured system-server
child. Java/libc records require that actual header's system-server PID. The Java summary
keeps only the system-process fatal marker and the first correlated throwable class within
two seconds and sixteen lines, mapped to four `java.lang` exception enums or `other`.
Nested causes, frames, messages, thread names, arbitrary class names, addresses and paths
are not exported. Native evidence retains only a numeric signal; an explicit trailing
crashed-process PID must match, distinct from a signal-sender PID in earlier details.
Duplicate scalar facts deduplicate; conflicting scalar values become null and ambiguous.
libc-observed and Zygote-termination signals remain separate facts without cause inference.

The fixed JSON schema contains only role/window scope, validated PIDs, window duration,
collection status/reason/exit/counts/timing and bounded booleans, numeric exit/signal values,
an exception enum and ambiguity. Its writer rejects extra/free-form fields and unsafe
symlink, hardlink or nonregular report destinations. Nonzero exit, any stderr warning,
invalid UTF-8/format, partial records, caps or timeout leave evidence **null**, never a
healthy/no-crash conclusion. A complete empty/unmatched result means only that no matching
signature was found. Unsupported device formatting fails closed, without a broader query.

Source-derived fixtures and format boundaries use the official
[logcat options/time parser](https://android.googlesource.com/platform/system/logging/+/refs/heads/main/logcat/logcat.cpp),
[logprint header and per-message-line prefixes](https://android.googlesource.com/platform/system/logging/+/refs/heads/main/liblog/logprint.cpp),
[Zygote termination templates](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/jni/com_android_internal_os_Zygote.cpp),
[RuntimeInit fatal marker](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/master/core/java/com/android/internal/os/RuntimeInit.java),
[debuggerd native signal summary](https://android.googlesource.com/platform/system/core/+/refs/heads/main/debuggerd/handler/debuggerd_handler.cpp)
and [Toybox numeric date formats](https://raw.githubusercontent.com/landley/toybox/master/toys/posix/date.c).
The invoked logcat comes from the system image, not host platform-tools. Host fixtures
alone cannot establish image-specific format support; the observed API37 capture below
provides one bounded runtime check, not a guarantee for other captures or images.

### Official body-format compatibility and structural reporting

Run `38334145181` reached log collection: exit zero, 2677 stdout bytes, no stderr. Its
schema-1 summary reported `invalid_header` with zero parsed/ignored records. Raw bytes
were intentionally discarded, so the rejected content and exact cause are unknown. The
earlier tests covered an intended synthetic format, not actual image output.

Official `convertPrintable` leaves literal TAB unchanged and copies valid UTF-8 sequences
without Python's Unicode printability check. The earlier whole-capture `isprintable()`
gate incorrectly rejected both, even inside a correctly prefixed message. The source-derived
fixture now uses width-19 epoch seconds, six fractional digits, width-5 PID/TID, padded tags,
real per-segment headers, empty message segments and literal-tab Java stack lines. It
reproduces that code defect, not the discarded runner bytes. Later run `38337086608` reported
complete collection for 747 stdout bytes, six parsed records and two validated banners,
without a format rejection or matching termination signature. This confirms acceptance of
that bounded API37 capture; it neither establishes a healthy/no-crash result nor explains
the observed installation failure or service/process loss.

The parser now validates each unchanged strict header before its body. Only within that
body it permits TAB, printable ASCII and valid non-ASCII UTF-8, matching the official
formatter. Raw ASCII C0/DEL, stray CR, malformed UTF-8, header tabs/Unicode whitespace,
unprefixed continuations and unknown/blank separators still fail closed. LF remains the
only record split, with optional terminal CR for CRLF; Unicode line separators inside a
message never create records. PID, timestamp, tag, child-process and throwable correlation
boundaries are unchanged. No additional log query, broader filters, raw output or replay
is added.

Schema **2** adds only a fixed `format_diagnostics` object: total LF-delimited line count,
maximum raw line bytes excluding LF, CRLF count, verified banner/message-TAB line counts,
and nullable first-rejected line number/byte count. Verified counts stop at a rejection;
total counts cover the capped capture. Coarse rejection-phase enums are
`decode/terminator/control/line_length/header/pid`; shape enums are
`known_banner/epoch_header/epoch_prefix/calendar_prefix/other`. Shapes classify syntax and
never grant evidence acceptance. They include no raw prefix, token, codepoint, hash, name
or log text. Unattempted parsing has zero/null diagnostics. Any later rejected record
clears even earlier positive evidence. The complete maximum fixed report remains within
4 KiB, and collector/file-safety/deadline/original-failure guarantees remain unchanged.

`python3 scripts/test_offline_install.py` and `python3 scripts/test_install_termination.py`
exercise these guards with mocked adb calls, a synthetic clock and real local Python
pipe cap/timeout/reap tests, including invalid byte streams. They do not prove actual
API37/API35 installation or instrumentation success; that requires an authorized emulator run.
