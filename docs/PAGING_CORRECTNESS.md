# Forum pagination correctness

## Scope

This local change covers the latest/good forum thread lists and GeneralTab lists.
It does not change BaseViewModel, LoadMoreLayout, recommendation feeds, startup
initialization, or transport policy. Repository response caches are removed;
forum-header and default latest-list first loads may make separate requests.
The existing `forceNew` parameters remain source-compatible but no longer select
cached responses.

## Ownership and invalidation

Each list ViewModel owns its own producer and pagination coordinator. The owner
accepts query replacement and network completion through one mailbox. Acceptance
of a refresh invalidates the previous generation before cancelling its request.
Cancellation saves work; generation checks establish correctness even if a
request ignores cancellation. Load-more intents carry only an action, and
concurrent load-more actions are dropped rather than queued with UI snapshots.

Queued changes are checked again by the real reducer and by event projection.
List failures use a list-specific event with a final guard immediately before
the page displays its Toast. This covers BaseViewModel's event-before-reducer
ordering and delayed UI event delivery without changing the common framework.
Refresh start also clears the previous load-more loading flag.

AccountUtil's existing initialization, switch and logout assignments advance a
non-credential, observable session generation under the same lock as the account
assignment and version getter. Requests and final guards include that version,
so A -> B -> A also invalidates A's earlier work. A changed account clears the
previous list, cursor and metadata and reloads the first page. A pending account
clear survives superseding refreshes until the current clear is actually reduced.
A failed account reload cannot restore another account's data. Ordinary refresh
failure retains the last query/cursor snapshot actually applied to the UI.

## Cursor and continuation rules

Repository page results preserve raw transport IDs/tails before video/live
filtering. Hidden blocked items are excluded from displayable additions.
GeneralTab advances from the raw last thread ID, not the displayed tail. Good
forum requests retain their selected classification, including default 0 when
no selection exists. ID-batch requests retain the existing good-list sort value
0; FRS good-list requests retain sort -1.

FRS server `has_more`, remaining thread-ID batches and visible threads are
independent. An ID batch consumes up to 30 IDs only after success, and preserves
the FRS server continuation flag because ThreadListResponse has no `has_more`.
Successful empty append pages remain consumed when a later page fails; the failed
page remains retryable. Replacement refreshes are transactional across their
bounded continuation requests.

One trigger can request at most three pages in total, including its first
request. A new displayable ID, server end, error, invalid generation or repeated
raw cursor stops continuation. Three filtered/duplicate pages with progressing
raw cursors preserve continuation and show “暂未找到符合条件的帖子 / 继续加载”.
Only the explicit continue button grants a new budget. The owner rejects delayed
automatic callbacks while paused; page preloading and swipe loading are disabled
in that state. Appending does not scroll to the top. A raw cursor with no progress
stops safely instead of spinning.

## Tests and verification boundary

32 new JUnit 4 tests use Channels and CompletableDeferred, with no sleeps:

- OwnedPaginationTest: 16 tests for stale success/failure/loading, ignored
  cancellation, final side-effect guards, two-owner isolation, single-flight,
  filtered/duplicate pages, total request budget, automatic gate, refresh rollback,
  partial append failure, account-switch/logout and queued account-clear races.
- ForumPagingCursorTest: 7 tests for classification/sort, raw cursor progression,
  ID batches and server continuation independent of visible items.
- ForumPageMappingTest: 4 tests execute the actual repository mapping functions
  and verify raw tails/IDs, filtering, authors and preserved server metadata.
- ForumPagingProducerTest: 5 tests execute actual producers, reducers and failure
  event projection, including classification, raw-tail ownership, retryable ID
  batches, delayed errors and account-clear/reload failures.

The new Kotlin/JUnit tests have not been compiled or run in this workspace.
The Gradle wrapper checksum passed and `git diff --check` passed. A focused
`:app:testReleaseUnitTest` attempt with a writable temporary GRADLE_USER_HOME
was blocked while downloading the pinned official Gradle distribution with
`java.net.SocketException: Network is unreachable`. No Android SDK, cached
Gradle distribution or Kotlin compiler was found; Android build, lint and device
validation remain unverified. Existing Python/Java host checks are separate
coverage and do not substitute for these coroutine/JVM or Android tests.

Run in a configured environment:

```sh
./gradlew --no-daemon :app:testReleaseUnitTest \
  --tests '*OwnedPaginationTest' \
  --tests '*ForumPagingCursorTest' \
  --tests '*ForumPageMappingTest' \
  --tests '*ForumPagingProducerTest'
```

Then run the repository's complete unit-test, lint and release-build workflow.
Device testing should cover repeated refresh/load-more, changing good categories,
fully filtered pages, the continue button, account switching and logout during
requests. These local changes are not a published build or a runtime safety
claim.
