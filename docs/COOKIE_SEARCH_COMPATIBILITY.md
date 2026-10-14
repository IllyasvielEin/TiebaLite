# Caller-built cookie and search-content compatibility

This local change is limited to two compatibility bugs:

- `api.getCookie` formats retained entries as `name=value`, joined by `; `.
  It preserves order, evaluates each supplier once, omits only null/empty values,
  and does not trim or encode opaque values. Device-model spaces and CUID
  punctuation such as `=`, `/`, `:`, `|`, `+`, and `%` remain intact.
- `SearchThreadBean.ThreadInfoBean`, `MainPost`, and `PostInfo` keep non-null
  `String` content and now default it to `""`. The existing production
  `coerceInputValues = true` treats explicit null content as the default. Omitted
  content uses the same default. Real strings, whitespace, and highlight markup
  remain unchanged. Object/array content and missing unrelated required fields
  remain decoding errors; the converter does not retry them through Gson.

The small production `CookieHeaderBuilder` rejects invalid HTTP-token names,
semicolon separators, ASCII controls, DEL, and non-ASCII values. The latter were
already unrepresentable by OkHttp's ordinary header API. It throws a generic
`IOException` without the original name/value or cause, so an asynchronous call
receives `onFailure` rather than an unchecked validation exception escaping the
OkHttp dispatcher. It does not promise Unicode-cookie support or silently rewrite
invalid input. This applies only to caller-built pairs, not saved account cookies.

`AccountUtil.getCookie`, cookie credential sets, destination policy, and
interceptor ordering are unchanged. HYBRID still uses its saved web cookie by
normal default; `add_cookie: false` retains the built cookie and removes the
control header. `CommonHeaderInterceptor` retains an explicit Cookie, and HYBRID's
opt-out branch retains that explicit Cookie. Existing default web-cookie
replacement behavior is unchanged.

## Verification

Run the dependency-free production formatter harness and source guards:

```sh
python3 scripts/test_cookie_search_compatibility.py -v
```

This compiles the actual Java helper with target 17 and exercises formatting,
all ASCII boundary characters, failure type, and error redaction. Its source
checks only verify wiring/default declarations, not Kotlin runtime behavior.

With the documented JDK 17 / Android SDK / Gradle environment installed, run:

```sh
./gradlew --no-daemon :app:testDebugUnitTest \
  --tests '*CookieHeaderBuilderTest' \
  --tests '*CookieHeaderCompatibilityTest' \
  --tests '*SearchThreadBeanCompatibilityTest'
```

The Kotlin tests use actual CommonHeader and AddWebCookie interceptors with a
synthetic terminal OkHttp interceptor (no network), including asynchronous
failure callbacks. The saved-cookie fixture temporarily replaces private account
state under a lock and restores the exact original state object in `finally`;
it does not load an account, database, or preferences. Search tests use the real
project `NullOnEmptyConverterFactory`, kotlinx `asConverterFactory`, and Gson
delegate chain on complete synthetic responses and each nested model.

At preparation time, the Java formatter harness passed. The Kotlin/OkHttp/
kotlinx-serialization JUnit tests have not been executed here because this
workspace has no downloaded Gradle distribution, Kotlin/dependency cache,
Android SDK, or JDK 17 toolchain. Java 21 is present and can run the narrow Java
checks. These checks are not an Android build, full unit-test pass, or device test.
