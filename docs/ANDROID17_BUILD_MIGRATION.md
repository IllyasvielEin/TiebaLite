# Android 17 build migration candidate

## Scope and verification boundary

The approved platform policy is minSdk 35, compileSdk 37, targetSdk 37, with no
maxSdk restriction. Android 17/API 37 is the primary device lane; Android 15/API
35 is the minimum-version regression lane. API 36 is optional. Source checks,
dependency resolution, compilation, lint, and device behavior are distinct
results. This document does not certify Android 17 runtime adaptation or
real-account login safety.

No Android SDK, system image, or JDK was installed in the local migration probe.
The owner subsequently approved official SDK/system-image installation and the
Android SDK terms (https://developer.android.com/studio/terms) for Actions. The
workflow uses the runner's preinstalled official SDK manager to install a fixed
package set; it does not accept unrelated installed-package licenses or change
KVM permissions. Package IDs and resulting files are checked explicitly.

API level 37 is packaged as `platforms;android-37.0`, with its JAR at
`platforms/android-37.0/android.jar`. The integer `compileSdk = 37` is correct:
the exact AGP 9.1.1 sources show its setter delegates to `release(37)`, and
`CompileSdkVersionImpl.toHash()` supplies `.0` for API 37+ when no minor version
is set. No explicit minor-version DSL or metadata-regex migration is needed.

## Toolchain decisions

- **AGP 9.1.1:** the minimum stable AGP release supporting API 37. Its documented
  minimum is Gradle 9.3.1, Build Tools 36.0.0, and JDK 17. Keep this bounded AGP
  version rather than adopting later releases just to rename APK files.
- **Gradle 9.8.1:** the October 7, 2026 security advisories affect open-source
  Gradle 9.0.0 through 9.8.0. The patched open-source versions are 8.14.6 and
  9.8.1. Moving to 9.3.1 would undo the previous security repair; 9.8.1 is the
  security-driven choice. Commercial backports are not assumed available.
- **Kotlin 2.3.21:** AGP supplies Kotlin support, with an explicit root buildscript
  KGP dependency taking its version from the catalog. Compose, Serialization,
  and Parcelize remain separately applied, all sharing the same Kotlin pin.
  `org.jetbrains.kotlin.android` is no longer declared or applied.
- **KSP 2.3.8:** retain the existing KSP2 line. KSP added AGP 9 built-in-Kotlin
  support in 2.3.1. No KAPT compatibility plugin or KSP1 opt-out is introduced.
- **Hilt 2.59.2:** 2.58 explicitly withheld AGP 9 support. 2.59 added it, and
  2.59.1/2.59.2 fixed associated Jetifier/transform and incremental-build issues.
  Plugin, runtime, and compiler use the same bounded version.
- **Wire 6.4.5:** keep the reviewed security pin. Its tagged plugin detects
  AGP's built-in Kotlin and registers Android generated sources through
  `AndroidComponents` and `variant.sources.kotlin.addGeneratedSourceDirectory`.
  The 6.4.6 change to Kotlin's `generatedKotlin` source-set API is not required
  for this Android registration path. Generated-code/KSP compilation still
  needs to pass on this actual project.
- **refreshVersions 0.60.6:** retain it; this patch replaced an internal API
  removed in Gradle 9. Do not run a broad dependency refresh as part of migration.
- **JDK 17:** remains the CI and Java/Kotlin compilation toolchain. A check run
  under the existing Java 21 runtime only establishes that check, not JDK 17 compilation.

Gradle 9.8.1's published test range includes Kotlin 2.0.0–2.4.20-RC2 and AGP
9.0–9.5.0-alpha02. Kotlin's own 2.3.20–2.3.21 table only lists Gradle through
9.3.0 and AGP through 9.0.0 as fully supported; it allows newer releases with
possible warnings or unavailable features. These are different maintainers'
validation ranges, not proof this entire plugin combination builds. Do not
promote this candidate to verified until all project gates pass.

## Public API and behavior migration

- Removed the legacy `applicationVariants`/`BaseVariantOutputImpl` filename cast.
  AGP 9.1's public `VariantOutput` does not expose `outputFileName`; that property
  was added in 9.4.1. Keep standard AGP APK names and consume the actual filename,
  version name, and version code in `output-metadata.json`.
- Explicitly enable the default host unit-test suite for both variants through
  public `androidComponents.beforeVariants` and `HostTestBuilder.UNIT_TEST_TYPE`.
  This preserves the existing `:app:testReleaseUnitTest` CI gate despite AGP 9's
  new tested-build-type-only default.
- Java resource-ID switch cases are migrated to comparisons, preserving the
  new compile-time R-class default without a compatibility opt-out.
- Eight existing memberless component/Glide keep rules now explicitly retain
  their no-argument constructor. AGP 9's strict keep-rule semantics no longer
  retain that constructor implicitly. This preserves those rules' previous
  effect without disabling the new optimizer behavior globally.
- Compose compiler settings live in their top-level extension. No legacy DSL,
  built-in-Kotlin, SDK-warning, or optimizer bypass is added.

## Official checksum provenance

Verified against https://gradle.org/release-checksums/ and the corresponding
`services.gradle.org/distributions/` checksum endpoints on October 12, 2026:

- `gradle-9.8.1-bin.zip` SHA-256:
  `dce76f55f8e251a3a1f130eb120f30b3d271de2b76c9b0729d316b5a1b6dc01f`
- Gradle 9.8.1 `gradle-wrapper.jar` SHA-256:
  `3b8a25775a69158b5ad2b1d17a80a88dc7b40a352a73eb27d06c612a7ce68e98`

The binary ZIP was verified before executing Gradle. Its wrapper task generated
this repository's wrapper JAR and POSIX/Windows scripts in an isolated empty
project; the generated JAR was then checked against the official wrapper hash.
Windows script line endings are normalized to the repository's existing LF
convention. Do not copy the Gradle repository's own bootstrap JAR from the
v9.8.1 tag: that tag's wrapper is still 9.8.0, with a different checksum.
The temporary generator skipped only its URL availability probe after Java's
probe failed; the ZIP checksum was independently verified, and this repository
retains `validateDistributionUrl=true` and `distributionSha256Sum`.

From the repository root, verify the wrapper before executing it:

```sh
sha256sum -c gradle/wrapper/gradle-wrapper.jar.sha256
```

## Required gates

1. Run `python scripts/test_android_toolchain.py` and all existing source,
   privacy, signing, metadata, and report checks.
2. Resolve `releaseRuntimeClasspath`; capture and check the Wire dependency
   insight reports. Catalog pins alone do not establish the selected graph.
3. Generate debug/release Wire sources and run `kspDebugKotlin` and
   `kspReleaseKotlin`, exercising Room, Hilt, Glide, and Compose Destinations.
4. Run release unit tests, full release lint, and unsigned release assembly;
   inspect merged SDK/identity metadata and generated output metadata.
5. After a separately authorized device setup/signing step, run API 37 primary
   and API 35 minimum-version regression coverage. An unsigned APK is not
   installable and is not runtime-test evidence.

## Local verification on October 12, 2026

- Passed: official distribution and generated-wrapper SHA-256 checks,
  `./gradlew --version`, POSIX wrapper shell syntax, source toolchain regressions,
  identity regressions, and `git diff --check`.
- Passed: `:app:help` on the existing Java 21 runtime. Both Kotlin DSL build
  scripts compiled and all pinned plugins applied. A temporary read-only Gradle
  task-registration assertion verified `testDebugUnitTest`,
  `testReleaseUnitTest`, `generateDebugProtos`, `generateReleaseProtos`,
  `kspDebugKotlin`, and `kspReleaseKotlin` exist. Registration does not mean those
  tasks executed or that their outputs compile.
- Blocked: `:app:tasks --all` reached task realization, then failed creating
  `compileDebugJavaWithJavac` because no JDK 17 installation was available.
  Toolchain auto-provisioning and SDK downloading were disabled. API 37 is also
  not installed in this environment. No unit test, lint, APK, or runtime result
  is claimed from this configuration check.
- Existing Jetifier/non-final-resource-ID settings and the singular Compose
  stability-file option emit deprecation warnings. They are not configuration
  failures, and Gradle 10 compatibility is outside this migration.

## Primary references

- [AGP 9.1.1 compatibility](https://developer.android.com/build/releases/agp-9-1-0-release-notes)
- [Exact AGP 9.1.1 sources: SdkDelegates.kt and CompileSdkSpecImpl.kt](https://dl.google.com/dl/android/maven2/com/android/tools/build/gradle/9.1.1/gradle-9.1.1-sources.jar)
- [AGP 9 migration and changed defaults](https://developer.android.com/build/releases/agp-9-0-0-release-notes)
- [Built-in Kotlin migration](https://developer.android.com/build/migrate-to-built-in-kotlin)
- [Kotlin Gradle compatibility](https://kotlinlang.org/docs/gradle-configure-project.html)
- [Gradle 9.8.1 compatibility](https://docs.gradle.org/current/userguide/compatibility.html)
- [Gradle 9.8.1 release notes](https://docs.gradle.org/9.8.1/release-notes.html)
- [Gradle client/daemon security advisory](https://github.com/gradle/gradle/security/advisories/GHSA-xwqc-3h47-hg64)
- [Gradle worker/daemon security advisory](https://github.com/gradle/gradle/security/advisories/GHSA-mvvg-497x-hmj8)
- [Gradle TLS repository-failure advisory](https://github.com/gradle/gradle/security/advisories/GHSA-j5m7-59rp-24f5)
- [KSP AGP 9 support](https://github.com/google/ksp/issues/2615)
- [Hilt release notes](https://github.com/google/dagger/releases)
- [Wire 6.4.5 generated Android source registration](https://github.com/square/wire/blob/6.4.5/wire-gradle-plugin/src/main/kotlin/com/squareup/wire/gradle/kotlin/SourceRoots.kt)
- [Wire change log](https://github.com/square/wire/blob/master/CHANGELOG.md)
- [refreshVersions 0.60.6](https://github.com/Splitties/refreshVersions/releases/tag/v0.60.6)
- [AGP 9.1 host-test builder API](https://developer.android.com/reference/tools/gradle-api/9.1/com/android/build/api/variant/HostTestBuilder)
- [AGP 9.1 variant output API](https://developer.android.com/reference/tools/gradle-api/9.1/com/android/build/api/variant/VariantOutput)
