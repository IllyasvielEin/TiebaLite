# Bounded avatar CDN migration

Version code 390102 uses `https://himg.bdimg.com` for newly constructed normal
(`/sys/portrait/item/`) and large (`/sys/portraith/item/`) portrait URLs. It also
normalizes full legacy URLs only for exact `tb.himg.baidu.com`, HTTP/HTTPS default
ports, no userinfo, either exact nonempty portrait route. The raw encoded path,
query (including timestamps, duplicate/blank values, `+` and percent escapes) and
fragment are preserved; no `.jpg` suffix is invented. Unrelated hosts/routes,
lookalikes, unusual ports, literal/percent-encoded dot segments and malformed URLs
are not remapped.

Fresh StringUtil builders produce the new URL before image-cache key selection.
The anonymous application interceptor also handles pre-existing full legacy
URLs, after its method/credentials/HTTPS checks. The non-upgrading network guard
still rejects HTTP downgrade redirects; it does not perform migration. Cookies,
credential stripping, normal platform TLS/hostname checks and public-download
rules are unchanged. There is no endpoint selector, HTTP fallback, certificate
bypass, cache clearing or extra diagnostic request.

The opt-in diagnostic UI keeps separate fixed legacy/HIMG host buckets for both
portrait sizes. It remains off by default and preserves the 40-event memory-only
privacy boundary. The host shown for a network event is the original request
host, not a claim about which host was contacted or failed after route migration
or redirects. A pre-existing legacy URL can therefore retain a legacy diagnostic
bucket even when the interceptor connects to HIMG.

## Evidence and limits

The device's prior diagnostic reported TLS_CERTIFICATE on the old origin. The
replacement is supported by current community client source. The normal route
and legacy-host migration are directly tested here:
https://github.com/infinityf4p/TiebaPure-iOS/blob/5a87225190d6a79b1e3ad3b7d846edd407d416c7/TiebaPureTests/ContentMappingTests.swift#L12-L32

The large route and preservation of percentEncodedQuery are shown here
(the neighboring strict normal route uses portraitn and is not our normal-route precedent):
https://github.com/Minaduki-Shigure/tieba-plus-plus-swift/blob/f595d1d84e023c005edd2724037c6507d4d765b8/App/Sources/TiebaCoreBrowseService.swift#L2139-L2159

This is endpoint precedent, not a live TLS or account compatibility guarantee.
Normal TLS remains mandatory and the new endpoint still requires confirmation
on the affected device. We have not logged into Tieba, installed the production
APK on a device, or weakened transport policy to make a test pass.

`python3 scripts/test_avatar_url_policy.py` executes the production pure Java
URL helper and checks wiring. Gradle tests additionally exercise the interceptor
without network using an in-process response interceptor, plus fixed diagnostic
host classification. Neither substitutes for real-device image loading.
