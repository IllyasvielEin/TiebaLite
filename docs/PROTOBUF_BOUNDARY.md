# Bounded protobuf responses and Wire patch

This change is limited to the native protobuf API response boundary. It does not
enable publication, change web features or credentials, or migrate the build
stack. No live-account requests are needed for its tests.

## Dependency selection

The shared Wire plugin/runtime version is pinned to **6.4.5**. The maintainer's
GHSA-9rm7-3qhh-h2mc / CVE-2026-63126 advisory (published 2026-07-14) lists runtimes
through 6.4.4 as affected and 6.4.5 as patched. The 6.4.5 changelog entry is dated
2026-06-29. It checks oversized lengths and logical reader boundaries. This is a
6.x patch, not a Wire 7 / AGP 9 migration. Keeping the generator and runtime on
one catalog version avoids an accidental mixed-version configuration.

- https://github.com/square/wire/security/advisories/GHSA-9rm7-3qhh-h2mc
- https://github.com/square/wire/blob/master/CHANGELOG.md#version-645

A declared catalog version is not proof of the resolved APK dependency. The
release validation must preserve these commands' output and check the selected
runtime (including wire-runtime-jvm, if selected):

```sh
./gradlew --no-daemon :app:dependencies --configuration releaseRuntimeClasspath
./gradlew --no-daemon :app:dependencyInsight --dependency com.squareup.wire --configuration releaseRuntimeClasspath
```

The main public exploit example concerns byte-array/ByteString decoding; this
app uses streamed response decoding. The patch also hardens streaming reader
boundaries. This upgrade is preventive remediation of an affected declaration,
not a claim that an exploitable app crash was reproduced.

## Response-size contract

`ProtoFailureResponseInterceptor` limits **decompressed** response bodies to
**8 MiB**. This deliberate defensive limit allows substantial paginated data
while preventing unbounded buffering. It is not based on a measured universal
Tieba maximum, and a legitimate larger response will now fail with IOException.
If such a response is encountered, investigate pagination and a sanitized size
measurement before changing the limit; do not restore unbounded reads.

The size/response-ownership implementation is shared with the JSON interceptor
through the narrow `withBoundedBody` helper. The independent JSON default is
16 MiB; this refactor does not change the protobuf cap or envelope mappings.
See [JSON_RESPONSE_BOUNDARY.md](JSON_RESPONSE_BOUNDARY.md) for the JSON default,
parser-fallback contract, and current verification limits.

The check runs before both successful-body decoding and return of HTTP error
bodies, since Retrofit may also buffer the latter. A declared size above the
limit is rejected without reading; a limit-plus-one probe enforces the bound
when Content-Length is unknown, understated, or stripped after gzip decoding.
Okio can read ahead by a single segment. The probe does not drain the full
oversized stream. Exactly 8 MiB is accepted. The original bounded bytes remain
available to the real converter through a non-consuming peek.

Every rejected response is closed, including read errors, malformed envelopes,
size errors, and API business errors. Malformed envelope decode exceptions are
normalized to IOException so OkHttp's asynchronous failure callback can handle
them. Under-limit non-2xx status/body content is left intact and is not interpreted
as a protobuf envelope; empty successful bodies still pass through. Existing
business error code/message reporting is retained.

## Envelope compatibility

Most `OfficialProtobufTiebaApi` contracts put `Error` in field 1. Four put data in
field 1 and `Error` in field 2:

- /c/f/forum/getBawuInfo: GetBawuInfoResponse
- /c/f/forum/getLevelInfo: GetLevelInfoResponse
- /c/f/forum/getMemberInfo: GetMemberInfoResponse
- /c/c/post/addPollPost: AddPollPostReponse

Those exact paths use their existing generated response adapters. Blindly
rejecting a generic field-1 envelope probe failure would reject valid responses
from these contracts. The last route handles poll voting, not post/reply
publication. Its existing voting behavior remains unchanged.

The default probe validates the common error envelope and top-level field
encoding, not all nested endpoint-specific data. The actual Retrofit Wire
converter remains responsible for the complete response schema. Add or update
the mapping and fixtures whenever a service contract changes its error field.
The source-level contract test checks every declared @POST/Flow response against
the checked-in proto schema to catch a newly introduced mismatch.

## Offline verification

No MockWebServer or new test dependency is needed. A terminal application
interceptor supplies synthetic responses without opening a socket. Tests cover:

- Valid/unknown-field bodies preserved for conversion; known/unknown empty bodies
- Non-2xx body/status preservation; API business error code/message and closure
- All four data-first response schemas, including their real error field
- Truncated and malicious-length protobuf failures and response closure
- Direct Wire byte-array and stream overflow regression (not just an exception wrapper)
- Advertised oversize before read, unknown/understated lengths, exact limit and +1
- Decompressed gzip-shaped bodies (via GzipSource) and bounded read-ahead
- Read failures and asynchronous failure callback completion

The gzip fixture models the decompressed body the interceptor receives. It is
not an end-to-end network or Android-device gzip test.

```sh
python3 app/src/test/security/check_protobuf_response_contracts.py
./gradlew --no-daemon :app:testReleaseUnitTest --tests '*ProtoFailureResponseInterceptorTest'
./gradlew --no-daemon :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
```

The source check is supplementary, not proof that JVM tests, Gradle resolution,
release shrinking, or device behavior passed. Build evidence and later emulator/
physical-device verification must be reported separately.
