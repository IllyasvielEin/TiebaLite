# Personal learning builds

This fork keeps the upstream source and license. Build artifacts are for learning
and evaluation. A successful build is not a security audit or approval to log in
with a real account.

## Pinned Android 17 migration candidate

- Gradle 9.8.1, official binary distribution and wrapper with SHA-256 verification
- Android Gradle Plugin 9.1.1 with built-in Kotlin; Kotlin compiler and
  Compose/Serialization/Parcelize plugins aligned at 2.3.21; KSP 2.3.8
- Hilt plugin/runtime/compiler 2.59.2, including AGP 9 and Jetifier fixes
- Wire plugin/runtime catalog pin 6.4.5; selected runtime is verified separately in CI
- Temurin JDK 17.0.20+8 in CI; Java/Kotlin toolchain and bytecode target 17
- Android SDK platform/compileSdk/targetSdk 37, Build Tools 36.0.0;
  minimum Android API 35, with no maximum SDK restriction

The SDK package ID is `platforms;android-37.0`, installed under
`platforms/android-37.0`. Keep integer `compileSdk = 37`: AGP 9.1.1 maps this to
the `android-37.0` platform hash automatically. `platforms;android-37` is not the
correct package name.

AGP 9.1.1 is the minimum stable AGP supporting API 37. Its minimum Gradle is
9.3.1, but that version is affected by the October 2026 Gradle security
advisories. Gradle 9.8.1 is selected as the patched open-source 9.x release,
rather than reintroducing vulnerabilities fixed by the previous 8.14.6 pin.

The Gradle 9.8.1 compatibility matrix covers this AGP/Kotlin range; Kotlin's own
2.3.21 matrix lists an older fully tested range. This is a migration candidate
until dependency resolution, both KSP/Wire generation paths, unit tests, lint,
and the release build pass together. See [ANDROID17_BUILD_MIGRATION.md](ANDROID17_BUILD_MIGRATION.md)
for exact compatibility sources, checksums, API changes, and verification limits.
Do not update these components independently without checking and building again.

The legacy JCenter-only ImmersionBar 3.0.0 dependency is migrated to the
maintainer's Maven Central coordinate com.geyifeng.immersionbar:immersionbar:3.3.3.
Its Java package remains com.gyf.immersionbar, so existing imports are retained.

Official references:
- https://docs.gradle.org/9.8.1/release-notes.html
- https://gradle.org/release-checksums/
- https://developer.android.com/build/releases/agp-9-1-0-release-notes
- https://kotlinlang.org/docs/gradle-configure-project.html
- https://github.com/gyf-dev/ImmersionBar
- https://github.com/square/wire/security/advisories/GHSA-9rm7-3qhh-h2mc

The Wire update is a narrow 6.x security patch, not a general dependency refresh.
CI records `releaseRuntimeClasspath` and Wire `dependencyInsight` reports, then
checks selected runtime component headers against the patched catalog pin. A
version declaration alone is not resolved-dependency evidence. The fixed report
names are included in the filtered validation artifact even if a later build
step fails. See [PROTOBUF_BOUNDARY.md](PROTOBUF_BOUNDARY.md) for the response cap
and compatibility tests, and [IMAGE_PICKER.md](IMAGE_PICKER.md) for the scoped
system-picker migration.

This candidate raises compileSdk/targetSdk to 37. The device test matrix is
Android 17/API 37 primary coverage and Android 15/API 35 minimum-version
regression coverage, with API 36 optional. No API 23/24/34 execution lane applies
to this minSdk 35 package. Target-specific runtime behavior still needs device
tests; a source migration or successful APK build is not full Android 17 adaptation.

Publication and transport restrictions are documented in
[SECURITY-BOUNDARIES.md](SECURITY-BOUNDARIES.md) and
[PUBLICATION_BOUNDARY.md](PUBLICATION_BOUNDARY.md).

## Local verification

Install JDK 17 and Android SDK platform 37 / Build Tools 36.0.0 from their
official sources. Review and accept any required SDK licenses yourself. Set
ANDROID_HOME or create an ignored local.properties with sdk.dir pointing to your
SDK. Then run:

```sh
sha256sum -c gradle/wrapper/gradle-wrapper.jar.sha256
./gradlew --no-daemon :app:generateDebugProtos :app:generateReleaseProtos :app:kspDebugKotlin :app:kspReleaseKotlin
./gradlew --no-daemon :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
```

Without keystore.properties, the release APK is **unsigned**. It cannot be
installed before signing. The build no longer silently substitutes a disposable
debug key for a release key. A locally configured release signing identity is
still supported; keep keystore.properties and keys out of Git. Creating a stable
personal signing identity remains a separate decision. The approved fork now
uses application ID `io.github.illyasvielein.tiebalite`; its source/resource
namespace remains `com.huanchengfly.tieba.post`. It is a separate installation
from the upstream package, not an update or automatic data transfer.

APK names follow AGP defaults (normally `app-release-unsigned.apk` for the
unsigned release). Read `output-metadata.json` to locate the actual file and
version fields; do not reconstruct a filename from the version name.

`application.properties` is the single source for `versionName` and `versionCode`.
Both local and CI builds use these values unchanged: `4.0.0` and `390103` for
this revision. No prerelease label or commit SHA is appended to the version name.
Commit provenance remains in the build metadata, and CI still controls the
existing self-build flag independently. Future version changes need only those
two properties; existing APK files are not renamed.

## GitHub Actions

Run **Build learning APK** manually from Actions. The selected ref is built.
Leave **sign_apk** unchecked for the default unsigned proof. There are no
push/tag release triggers, public GitHub Release creation, or write token
permissions. Optional signing requires an explicitly configured owner-controlled
key and only runs on the trusted default branch after the build and full lint
pass; see [SIGNING.md](SIGNING.md) for the separate-runner trust boundary. Checkout does not retain its
authentication credential. Actions are pinned to full commit SHAs, and
setup-gradle is the only Gradle cache owner (including wrapper validation).

The owner approved the [Android SDK terms](https://developer.android.com/studio/terms)
and fixed official SDK package installation for Actions. The workflow uses the
runner's existing official SDK manager and `scripts/ensure_android_sdk.py` to
install `platforms;android-37.0`, Build Tools 36.0.0 and platform tools. It accepts
prompts only for the selected package set, not blanket `sdkmanager --licenses`.
Missing command-line tools or required installed files fail closed. Emulator
packages are a separate fixed mode; no paid device service is enabled.
The runner image itself receives GitHub updates, so the artifact
metadata records the actual JDK as well as source/toolchain versions.

The seven-day artifact includes:
- Unsigned release APK
- SHA256SUMS (verify with `sha256sum -c SHA256SUMS`)
- Android output-metadata.json and allowlisted build/source metadata
- R8 mapping.txt when generated

Artifacts on a public repository are not a private distribution channel. Do not
put credentials, personal data, keystores, or confidential information in the
source/artifact. There is no device installation, app launch, login, or production
posting in this workflow. Keep the original key for any future signed package;
changing keys normally prevents updating an existing installation.

Unit tests include the upstream example and targeted privacy/security regressions.
The workflow builds/tests and archives the experimental unsigned proof first, then
runs full lint as a blocking quality gate. A downloadable APK does not mean lint
passed: the first full verification found legacy lint errors, and the current
reports are authoritative for any remaining findings. Allowlisted lint and
unit-test reports are uploaded separately even when the job fails, with partial
token-pattern scrubbing rather than a guarantee of comprehensive secret removal. No lint errors
are suppressed or automatically baselined. These checks do not replace behavior
tests or security review; real-account login is not validated. Download artifacts before retention expires; there is intentionally no
automatic permanent release archive.
