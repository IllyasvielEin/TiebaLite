package com.huanchengfly.tieba.post.security;

import java.net.URI;
import java.net.URISyntaxException;

/** Exact public portrait-route migration; no decoding, credential removal, or TLS override. */
public final class AvatarUrlPolicy {
    private static final String LEGACY_HOST = "tb.himg.baidu.com";
    private static final String ORIGIN = "https://himg.bdimg.com";
    private static final String SMALL = "/sys/portrait/item/";
    private static final String LARGE = "/sys/portraith/item/";

    private AvatarUrlPolicy() {}

    public static String small(String portrait) { return build(portrait, SMALL); }
    public static String large(String portrait) { return build(portrait, LARGE); }

    private static String build(String portrait, String path) {
        if (portrait == null || portrait.isEmpty()) return "";
        if (portrait.regionMatches(true, 0, "http://", 0, 7) ||
                portrait.regionMatches(true, 0, "https://", 0, 8)) {
            return normalizeLegacy(portrait);
        }
        // Preserve the existing portrait token/query representation without inventing a suffix.
        return ORIGIN + path + portrait;
    }

    public static String normalizeLegacy(String value) {
        if (value == null || value.isEmpty()) return value;
        try {
            URI uri = new URI(value);
            String scheme = uri.getScheme();
            boolean http = "http".equalsIgnoreCase(scheme);
            boolean https = "https".equalsIgnoreCase(scheme);
            if ((!http && !https) || !LEGACY_HOST.equalsIgnoreCase(uri.getHost()) ||
                    uri.getRawUserInfo() != null ||
                    (uri.getPort() != -1 && uri.getPort() != (http ? 80 : 443))) return value;
            String path = uri.getRawPath();
            if (path == null || !((path.startsWith(SMALL) && path.length() > SMALL.length()) ||
                    (path.startsWith(LARGE) && path.length() > LARGE.length()))) return value;
            // OkHttp removes literal and percent-encoded dot segments later. Do not
            // move a URL whose effective path can leave the approved portrait route.
            for (String segment : path.split("/", -1)) {
                String dots = segment.replaceAll("(?i)%2e", ".");
                if (dots.equals(".") || dots.equals("..")) return value;
            }
            return ORIGIN + path + (uri.getRawQuery() == null ? "" : "?" + uri.getRawQuery()) +
                    (uri.getRawFragment() == null ? "" : "#" + uri.getRawFragment());
        } catch (URISyntaxException ignored) {
            return value;
        }
    }
}
