# Personal learning builds

This fork keeps the upstream source and license. Build artifacts are for learning
and evaluation. A successful build is not a security audit or approval to log in
with a real account.

## Pinned compatible toolchain

- Gradle 8.14.6, official binary distribution with SHA-256 verification
- Android Gradle Plugin 8.13.2, Kotlin 2.3.21, KSP 2.3.8
- Temurin JDK 17.0.20+8 in CI; Java/Kotlin toolchain and bytecode target 17
- Android SDK platform 36, Build Tools 36.0.0; minimum Android API 23

Gradle 8.14.6 is a security patch. AGP 8.13.2 supports Kotlin 2.3 and API 36;
AGP 9's built-in Kotlin and DSL changes are a separate migration, not required
for this build repair. Do not update these components independently without
checking compatibility and building again.

The legacy JCenter-only ImmersionBar 3.0.0 dependency is migrated to the
maintainer's Maven Central coordinate com.geyifeng.immersionbar:immersionbar:3.3.3.
Its Java package remains com.gyf.immersionbar, so existing imports are retained.

Official references:
- https://docs.gradle.org/8.14.6/release-notes.html
- https://gradle.org/release-checksums/
- https://developer.android.com/build/releases/agp-8-13-0-release-notes
- https://kotlinlang.org/docs/gradle-configure-project.html
- https://github.com/gyf-dev/ImmersionBar

## Local verification

Install JDK 17 and Android SDK platform 36 / Build Tools 36.0.0 from their
official sources. Review and accept any required SDK licenses yourself. Set
ANDROID_HOME or create an ignored local.properties with sdk.dir pointing to your
SDK. Then run:

```sh
./gradlew --no-daemon :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
```

Without keystore.properties, the release APK is **unsigned**. It cannot be
installed before signing. The build no longer silently substitutes a disposable
debug key for a release key. A locally configured release signing identity is
still supported; keep keystore.properties and keys out of Git. Creating a stable
personal signing identity and choosing a separate application ID require a
separate decision. This change does neither.

## GitHub Actions

Run **Build learning APK** manually from Actions. The selected ref is built.
There are no push/tag release triggers, no public GitHub Release creation, no
signing secrets, and no write token permissions. Checkout does not retain its
authentication credential. Actions are pinned to full commit SHAs, and
setup-gradle is the only Gradle cache owner (including wrapper validation).

The workflow checks for preinstalled SDK packages/licenses on ubuntu-24.04; it
does not auto-accept SDK licenses. Missing SDK packages fail early with a clear
check failure. The runner image itself receives GitHub updates, so the artifact
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
passed: the current legacy code has outstanding lint findings. Sanitized lint and
unit-test reports are uploaded separately even when the job fails. No lint errors
are suppressed or automatically baselined. These checks do not replace behavior
tests or security review; real-account login is not validated. Download artifacts before retention expires; there is intentionally no
automatic permanent release archive.
