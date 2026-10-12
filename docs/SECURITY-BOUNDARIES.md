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
