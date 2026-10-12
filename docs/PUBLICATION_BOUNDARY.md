# Native publication disabled

The learning build's `security/PublicationPolicy.kt` is an immutable source-level
capability gate. It is disabled in every build variant; account state, saved
preferences, remote flags, restored navigation and the old warning-dialog
preference cannot enable it.

## Native coverage

- New-thread floating action button is hidden. Refresh and back-to-top still work.
- Thread and nested-reply input bars, clickable reply cards and reply menu entries
  are hidden/disabled. Reading replies and copying text remain available.
- `ReplyPageContent` is the common destination/dialog boundary. It shows a clear
  disabled notice with a close action, before loading a draft or account data,
  launching a media picker, or installing composer side effects. Restoring a stale
  composer route is safe; the old “continue reply” and official-client composer
  controls are unreachable.
- `ReplyViewModel` rejects send and media-upload intents before processing content
  or resolving image URIs. `AddPostRepository` rejects thread/reply flows before
  obtaining the API client. `ImageUploader` rejects even direct single-image calls
  and empty upload batches before decoding/reading files.
- Legacy `MixedTiebaApiImpl` upload, synchronous/asynchronous reply overloads,
  and thread/reply protobuf builders reject before reading media, obtaining an API
  client, or preparing account-dependent request bodies.
- The shared transport independently rejects the native API publication paths.
  See `CredentialTransportPolicy.isPublicationPath` and its interceptor/tests for
  the authoritative endpoint list. This includes legacy web API posting/upload
  calls made through Retrofit, not arbitrary web browsing.
- No publication service or exported composer activity was found. The remaining
  sign-in/sign/check-in services are distinct from creating posts.

The upstream composer code and draft storage remain in the source to keep this
change reviewable. They are inaccessible for publication while the capability is
false. No draft/account data is deleted or migrated.

## Retained mutations (not a read-only client)

These existing operations are deliberately outside the publication-disable scope:

- Like/unlike posts and threads (`/c/c/agree/opAgree`)
- Follow/unfollow users (`/c/c/user/follow`, `/c/c/user/unfollow`)
- Follow/unfollow forums (`/c/c/forum/like`, `/c/c/forum/unlike`,
  `/c/c/forum/unfavolike`; some legacy forum routes use `/c/f/forum/like`)
- Single and batch forum check-in (`/c/c/forum/sign`, `/c/c/forum/msign`),
  including the existing check-in activity, job and quick-settings tile
- Add/remove saved threads (`/c/c/post/addstore`, `/c/c/post/rmstore`)
- Delete posts/threads (`/c/c/bawu/delpost`, `/c/c/bawu/delthread`)
- User blocking (`/c/c/user/setUserBlack`) and recommendation feedback
  (`/c/c/excellent/submitDislike`)
- Poll voting (`/c/c/post/addPollPost`, both legacy GET and protobuf POST).
  Despite its endpoint name, this is voting, not authoring a thread.

This is an inventory of relevant native mutation families, not an assertion that
all API methods or third-party website actions are read-only. Login/session sync,
local settings and history writes also remain.

## Web and runtime limits

Native Retrofit guards do not control standalone external browsers/apps. Embedded
WebViews are a separate security boundary: known-path request interception alone
cannot establish that arbitrary JavaScript, service workers, redirects or future
server endpoints cannot publish. Do not describe native publication removal as a
complete sandbox for authenticated web browsing. Existing web features remain
available; no blanket embedded-WebView ban is part of this change. The practical
UX goal is to prevent accidental native reply activation on a single content or
floor tap, while preserving ordinary reading and navigation.

## Verification

Run:

```sh
python3 app/src/test/security/check_publication_boundaries.py
./gradlew --no-daemon :app:testReleaseUnitTest --tests '*PublicationPolicyTest'
```

The source tests check early guard ordering, shared composer coverage, immutable
policy and UI capability checks. JVM tests exercise the gate and direct repository
and image-uploader failure paths without real accounts, files, or network access.
Source checks are not a substitute for Kotlin compilation or device UI tests.
Manual/device validation should cover signed-out/signed-in native navigation,
restored composer routes, close/back, and nested replies without submitting real
content. No production login or publication is needed for these checks.

## Reading taps and reply warnings

The accidental-reply path in the upstream native UI was:

- `ThreadPage.PostCard` single tap → `onReplyClick` → `ReplyPageDestination`
- `SubPostsPage.SubPostItem` single tap → `onReplyClick` → `showReplyDialog`
- Both composer variants → `ReplyPageContent` → the warning dialog when
  `postOrReplyWarning` is enabled

Floor cards and subreply-detail cards now explicitly pass `onClick = null`,
independently of account state or saved reply preferences. A reading tap does not
emit a reply event. `LongClickMenu` treats a null callback as long-press-only rather
than installing a no-op `combinedClickable`: it has no tap ripple or accessibility
click action, retains an accessibility long-click action, and positions the menu at
the long-press location. Its existing non-null click branch is retained.

The nested-reply preview inside a thread still opens nested-reply details through
`onOpenSubPosts`; this is navigation, not composing. Content renderers and their
image/link handlers, profile taps, thread-opening navigation, and long-press
copy/report/favorite/delete actions are retained. The common composer guard also
returns before the old warning dialog, covering restored or programmatic routes.

Eight source regression checks currently cover the publication boundaries and
this click wiring. These checks verify source structure only. Nested gesture
propagation, scrolling/cancellation, menu position, accessibility, and child
image/link taps still require Compose/device UI validation; no runtime GUI pass
is claimed. Generic WebView browsing is not disabled by this UX change.
