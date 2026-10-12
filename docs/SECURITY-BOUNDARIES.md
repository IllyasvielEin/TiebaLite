# Learning edition security boundaries

This document describes the next local hardening changes. They are not a claim
that the application is safe for a real account, and are not yet verified by an
Android build. The last verified build before these changes was commit
`914635fe`, Actions run `38204894955`.

## Publication and other account changes

Thread creation, replies (including nested replies), and publication image
uploads are disabled as a source-level capability. Composer entry points are
hidden; restored or direct composer routes display a disabled notice. ViewModel,
repository, uploader and native API boundaries independently reject publication.
This is not a preference that a user or remote configuration can turn on.

The application is **not fully read-only**. Existing votes, likes/dislikes,
check-ins, follows, bookmarks, profile/avatar edits, deletion and blacklisting
are separate account mutations. Their retention is not evidence that they are
safe or tested. The separate native avatar endpoint (`/c/c/img/portrait`) is retained;
publication media upload endpoints are denied.

Authenticated embedded web pages are a separate boundary from native Retrofit
calls. Their JavaScript or service workers can submit requests outside native
publication guards. Existing embedded web features are retained. Native publication closure does
not prove web publication is impossible; remote pages remain outside this
practical accidental-reply prevention guarantee. No blanket WebView ban is added.
The login provider can set its own cookies in the shared WebView CookieManager;
hardening the app-generated BDUSS cookie does not establish identical attributes
for every server-set cookie or complete isolation between embedded pages.

## Transport

Legacy JSON clients migrate from HTTP `c.tieba.baidu.com` to HTTPS
`tiebac.baidu.com`, following the existing Protobuf endpoint migration. This is
an endpoint compatibility precedent, not proof that every authenticated request
works on every device. Platform TLS certificate and hostname verification must
remain enabled. There is no credential-bearing HTTP fallback.

Authenticated API clients enforce their exact configured HTTPS origin before
adding account credentials. Automatic redirects are disabled, including
same-origin redirects, to avoid replaying signed bodies or credentials. Some
server flows may therefore fail closed and need endpoint-specific investigation.

Cleartext traffic is disabled. Legacy HTTP-only images/emoticons may not load;
image availability is not a reason to bypass certificate errors. General image
and update/download traffic must remain separate from authenticated cookies and
headers. Normal TLS errors must never trigger a permissive trust manager.

## Dependency permissions and remaining identifiers

The pinned `com.github.gzu-liyujiang:Android_CN_OAID:4.2.17` library
[declares](https://github.com/gzu-liyujiang/Android_CN_OAID/blob/4.2.17/library/src/main/AndroidManifest.xml)
`READ_PHONE_STATE`, `WRITE_SETTINGS` and Google `AD_ID`. Its exact published AAR
was inspected; SHA-256:
`505a052f4aa7cafa669e6655a3cf2f540981fccaed22628f74b05cdc49978e26`.
The app now uses unconditional `tools:node="remove"` markers for
`READ_PHONE_STATE` and `WRITE_SETTINGS`, preventing library manifests from
restoring those unused permissions. Omitting a permission from the app source
alone is insufficient; see the Android
[manifest-merger rules](https://developer.android.com/build/manage-manifests#node_markers).
The final APK permission check must verify the merged result on every build.

The app's `App.Config.init` and `OAIDGetter.onActivityResumed` call only
`DeviceID.supportedOAID` and `DeviceID.getOAID(Context, IGetter)`. The library's
[DeviceID](https://github.com/gzu-liyujiang/Android_CN_OAID/blob/4.2.17/library/src/main/java/com/github/gzuliyujiang/oaid/DeviceID.java)
settings-write path is `register` → `getOAIDOrOtherId` → `getOtherId` →
`getGUID` → `saveUuidToSystemSettings` → `Settings.System.putString`.
Neither these GUID entry points nor another settings-writing/requesting call
is used by app source. `PermissionUtils` contains only a settings-permission
display-name mapping; it does not request that permission. The source regression
guards the removal marker and absence of these unused entry points.

`AD_ID` is retained: the existing `getOAID` path reaches
[OAIDFactory](https://github.com/gzu-liyujiang/Android_CN_OAID/blob/4.2.17/library/src/main/java/com/github/gzuliyujiang/oaid/impl/OAIDFactory.java),
which selects Google services for Xiaomi Global or as its universal fallback.
[GmsImpl.doGet](https://github.com/gzu-liyujiang/Android_CN_OAID/blob/4.2.17/library/src/main/java/com/github/gzuliyujiang/oaid/impl/GmsImpl.java)
binds Google's advertising-ID service, checks the limit-ad-tracking flag and
calls `IAdvertisingIdService.getId`. The app retains OAID/AAID fields in existing
API requests. Removing this capability needs a separate compatibility/privacy
decision; these changes do **not** remove all device identifiers or establish
real-account safety. No advertising-ID service or actual permission grant was
tested during this source audit.

## Signing

See [SIGNING.md](SIGNING.md). Unsigned builds remain the default. Opt-in signing
must run only after successful build, tests and full lint on a fresh runner that
does not execute Gradle or repository scripts with signing secrets. The owner
controls key creation, backup and direct GitHub secret configuration. A public
certificate fingerprint pins the expected identity. Signing is not a login
security test.

## Required verification

- Source and policy regression checks, plus the complete Android unit suite.
- Full blocking Android lint and release assembly for the exact final commit.
- Mocked HTTP/redirect/cookie behavior; no production account or mutation tests.
- Device checks for navigation, deep links, login handoff and failure handling.
- Confirm native content/floor single taps do not invoke reply or its warning,
  while subreply details, images, links and long-press menus still work.
- Retain the explicit limitation that authenticated remote web pages can offer
  their own account actions; do not claim all in-app publication is impossible.

No key generation, real-account login, production posting or device installation
is part of these local source checks.
