# Bounded JSON response probing

`FailureResponseInterceptor` and `ProtoFailureResponseInterceptor` use the same
narrow `withBoundedBody` helper for non-consuming size checks and response
ownership. Their format limits remain separate: **JSON 16 MiB**, **protobuf
8 MiB**. Both apply to the decompressed body received by application interceptors.

## Default selection and compatibility risk

The checked-in JSON service contracts were inspected before choosing the JSON
default. Typical defaults request 15 home-feed threads, 30 thread posts with
three floor replies, or 20/50 other paginated entries. The repository has no
captured API JSON response/size fixtures from which to establish a real maximum;
existing offline smoke assets are media/UI fixtures. No live account, private
response, or additional server request was used to choose this cap.

16 MiB is a conservative application defense with extra room for JSON's verbose
representation. It is not a measured server maximum or an optimal memory budget.
Legitimate larger responses can fail with IOException. Investigate pagination
and sanitized size measurements before changing the independent JSON constant;
do not restore an unbounded read. The protobuf default is unchanged. A byte cap
does not guarantee that every parser/model allocation or nesting pattern fits
within device memory.

## Body and error ownership

A declared length above the format cap is rejected before reading. Every other
body, including non-2xx, declared zero, unknown, understated, and decompressed
gzip bodies, is probed for an actual `limit + 1` bytes. Okio may read ahead by one
segment; the physical read upper bound tested is `limit + 8192`, not strictly
`limit + 1`. Oversized streams are not drained to EOF. Exactly the limit is
accepted, and the original bytes, charset, status, and body remain available to
Retrofit without replacing its response body.

Non-2xx bodies are bounded but are not treated as JSON business envelopes. On
successful responses, Gson probes a clone of the already bounded in-memory
buffer using the body's charset (UTF-8 by default). Existing CommonResponse
aliases are retained: `error_code`/`errno`/`no` and `error_msg`/`errmsg`/`error`,
including ErrorMsgAdapter's nested `errmsg` handling. Missing, null, array-shaped,
or empty business-error messages now use the existing generic Chinese message
`未知错误` while preserving the nonzero error code.

Valid JSON that does not fit CommonResponse, and existing syntax/shape probe
failures, remain available to the endpoint converter. Gson's in-memory syntax
MalformedJsonException/EOFException are distinguished from real read failures.
Transport IOException/timeout, cancellation, and fatal errors are not swallowed
as parse fallback. Rejected responses are closed in `finally`, including size,
business-error, read-failure, cancellation, and fatal-error paths. Responses
returned to Retrofit stay open for the caller to own and close. Size-error text
contains the format and safety limit, never a response body or request secret.

## Offline regression fixtures and verification limits

`FailureResponseInterceptorTest` uses a terminal application interceptor and
tracked synthetic sources. It does not open sockets or access account/app state.
Tests call the production interceptor/helper and cover:

- Byte, charset, and caller-ownership preservation with truthful/lying lengths
- Every business-error alias, nested messages, and null/missing/array fallback
- Valid non-envelope JSON and syntax/shape fallback with original bytes intact
- Empty and non-2xx responses, without interpreting HTTP errors as envelopes
- Advertised oversize before reading; real-size caps for unknown/zero/lying lengths
- Exact limit and one byte over; bounded one-segment read-ahead
- GzipSource-modeled decompressed responses, including oversized HTTP errors
- Read failure, timeout, cancellation, synthetic fatal error, and async completion

Proto tests retain their existing error-field, Wire-overflow, gzip, exact-size,
and ownership regressions, plus partial-read failure/cancellation/fatal paths
after sharing the helper. GzipSource fixtures model the application-interceptor
input after OkHttp's bridge; they are not end-to-end network or device gzip tests.
Synthetic OutOfMemoryError fixtures test cleanup/propagation without exhausting
real heap memory.

```sh
python3 app/src/test/security/check_protobuf_response_contracts.py
./gradlew --no-daemon :app:testReleaseUnitTest --tests '*FailureResponseInterceptorTest'
./gradlew --no-daemon :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
```

The source contract check is supplementary, not runtime proof. These new JVM
fixtures were **not executed** in the current local-edit workspace, which has
no Android SDK, Gradle distribution/dependency cache, Kotlin compiler, or test
dependency jars. No toolchain was installed and no CI/build/push was started.
Compilation, JVM unit tests, lint, release assembly, and device validation remain
required in an equipped environment.
