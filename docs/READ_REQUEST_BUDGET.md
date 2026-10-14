# Selective read-request execution budget

The existing 60-second connect/read/write timeouts are individual I/O timeouts.
A server can keep a response alive with occasional bytes, so these timeouts alone
do not cap an entire request's network execution.

`BudgetedReadRequest` marks individually audited Retrofit methods. Before creating
an OkHttp call, `ReadOnlyRequestCallFactory` reads Retrofit's `Invocation.method()`
and chooses a prebuilt derived client with `callTimeout(60, SECONDS)`. Unmarked
methods and requests without a Retrofit Invocation use the original client.
This does not infer read-only behavior from POST/GET, URL matching or multipart
encoding. Protobuf reads themselves use `MyMultipartBody`.

The derived client uses `originalClient.newBuilder()` and changes only callTimeout.
It retains credential/publication guards, interceptor order, signature/cookie
handling, normal platform TLS verification, disabled HTTP/HTTPS redirects, the
original dispatcher, and the shared connection pool. It adds no application retry,
refresh, automatic login navigation or changes to session state. Existing OkHttp
connection recovery is unchanged. A transport timeout remains an IOException on
the existing error path; it is not evidence of invalid credentials or a request
to force login. Write/upload and image/media clients retain their previous policy.

## Audited first batch

- `OfficialProtobufTiebaApi.frsPageFlow`, `/c/f/frs/page`: requests a forum's page,
  sort/filter and thread summaries. MixedTiebaApi currently routes through V12.
- `OfficialProtobufTiebaApi.threadListFlow`, `/c/f/frs/threadlist`: fetches forum
  threads by page/sort and supplied thread IDs. MixedTiebaApi routes through V12.
- `OfficialProtobufTiebaApi.pbPageFlow`, `/c/f/pb/page`: reads thread posts,
  page/post positions, filters and floor summaries. MixedTiebaApi uses V12.
- `OfficialProtobufTiebaApi.pbFloorFlow`, `/c/f/pb/floor`: reads a post's floor
  replies by page/sub-post ID. MixedTiebaApi uses V22.
- `OfficialProtobufTiebaApi.generalTabListFlow`, `/c/f/frs/generalTabList`: reads
  a forum tab's thread page and sorting. MixedTiebaApi uses the POST-profile
  client; that client's name does not imply all of its methods write data.
- `OfficialTiebaApi.threadContent` and `threadContentAsync`: all four JSON
  `/c/f/pb/page` overloads read the same thread content, selecting by page number
  or post ID. Both Call and Deferred adapters receive the budget.
- `OfficialTiebaApi.floor`: the JSON `/c/f/pb/floor` floor-list read used by
  MixedTiebaApi receives the same budget.
- `MiniTiebaApi.forumPage` and `forumPageAsync`: the two legacy JSON
  `/c/f/frs/page` reads select forum page/sort/classification.
- `MiniTiebaApi.floor`: the legacy JSON `/c/f/pb/floor` read is explicitly marked
  as well. MixedTiebaApi currently uses OfficialTiebaApi.floor instead, but this
  API method has the same read-only purpose if directly invoked.

There are 13 marked methods in three interfaces. The protobuf interface is shared
by V11, V12, V22 and POST-profile client instances. Only those five marked protobuf
methods select the budget on any of those instances. Unmarked methods, including
addPostFlow, addThreadFlow, addPollPostProtobuf, uploads, login and account changes,
continue to use their original client settings. Other reads remain unmarked until
separately audited. Sofire's factory remains unchanged.

## Scope of the timer

With pinned OkHttp 5.3.2, the call timer starts at synchronous execution or when
an asynchronous call begins running, and covers network execution including
response-body I/O. Its 60 seconds do not include waiting in OkHttp's asynchronous
dispatcher queue. It is not a page-level deadline: preparing request data, separate
calls, rendering and arbitrary CPU-bound/interceptor work are not guaranteed to
return by 60 seconds. Cancellation closes in-flight network I/O through the
existing call/coroutine path. There is no new scheduler or application retry.

Setting the timeout on the derived client before `newCall` also ensures raw
OkHttp `Call.clone()` retains it. Retrofit clones recreate a request with the
same Invocation method and choose the derived client again. Runtime annotation
attributes and the annotation type are retained by the release rules; a release
build still needs verification in an SDK-equipped environment.

## Verification

The JVM test source `ReadOnlyRequestCallFactoryTest` invokes the production factory
and real Retrofit service methods. It uses local ServerSocket HTTP I/O and short,
injected test budgets; it does not simulate a timeout with Thread.sleep and a
synthetic response. Cases cover default budget and both kinds of clone, normal
success, stalled headers, a progressing slow response body, cancellation, unmarked
GET/write/upload/no-Invocation exclusions, a multipart read, shared dispatcher
queue behavior, shared pooled connections, interceptor/EventListener preservation,
disabled redirects and credential guards before later interceptors. Request counts
check that failure tests do not introduce extra application requests. The real
production Flow and Deferred adapters also have marked success/timeout, unmarked
over-budget success, and underlying-call cancellation cases. Fixture
sockets, workers and clients are closed after tests. A synthetic terminal response
is used only for the separate credential-guard test, where it must never be reached.

Run the source-only wiring guards:

```sh
python3 -m unittest discover -s scripts -p 'test_read_request_budget.py' -v
```

Run actual JVM regressions with an Android SDK/Gradle dependency environment:

```sh
./gradlew --no-daemon :app:testDebugUnitTest --tests '*ReadOnlyRequestCallFactoryTest'
./gradlew --no-daemon :app:testReleaseUnitTest --tests '*ReadOnlyRequestCallFactoryTest'
./gradlew --no-daemon :app:lintRelease :app:assembleRelease
```

Python source guards do not compile Kotlin, run the JVM network tests or verify
R8/release behavior. No Gradle cache, Android SDK or Kotlin compiler is available
in the recovery workspace, so the actual JVM/build/release checks have not been
run there. This remains an explicit verification gap, not a passing runtime test.

Primary pinned implementation references:

- [OkHttp 5.3.2 RealCall timer/clone/async execution](https://github.com/square/okhttp/blob/parent-5.3.2/okhttp/src/commonJvmAndroid/kotlin/okhttp3/internal/connection/RealCall.kt)
- [OkHttp 5.3.2 newBuilder copies client settings](https://github.com/square/okhttp/blob/parent-5.3.2/okhttp/src/commonJvmAndroid/kotlin/okhttp3/OkHttpClient.kt)
- [Retrofit 3.0 Invocation method tag](https://github.com/square/retrofit/blob/3.0.0/retrofit/src/main/java/retrofit2/Invocation.java)
- [Retrofit 3.0 Call clone and request creation](https://github.com/square/retrofit/blob/3.0.0/retrofit/src/main/java/retrofit2/OkHttpCall.java)
