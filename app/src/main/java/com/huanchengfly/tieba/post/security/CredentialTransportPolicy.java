package com.huanchengfly.tieba.post.security;

/** Credential destinations are deliberately narrower than general in-app navigation. */
public final class CredentialTransportPolicy {
    private CredentialTransportPolicy() {}

    public static boolean permitsWebCookie(String scheme, String host, int port, String userInfo) {
        if (!"https".equalsIgnoreCase(scheme) || (port != -1 && port != 443)
                || (userInfo != null && !userInfo.isEmpty())) return false;
        return "tieba.baidu.com".equalsIgnoreCase(host)
                || "tiebac.baidu.com".equalsIgnoreCase(host)
                || "wapp.baidu.com".equalsIgnoreCase(host);
    }

    public static String bdussCookie(String bduss) {
        // Host-only, session lifetime: never grant every baidu.com subdomain this credential.
        // RFC 6265 cookie-octet: allow opaque encodings, forbid separators and control bytes.
        if (bduss == null || bduss.isEmpty()) throw new IllegalArgumentException("Invalid session credential");
        for (int i = 0; i < bduss.length(); i++) {
            char c = bduss.charAt(i);
            if (!(c == 0x21 || (c >= 0x23 && c <= 0x2B) || (c >= 0x2D && c <= 0x3A)
                    || (c >= 0x3C && c <= 0x5B) || (c >= 0x5D && c <= 0x7E))) {
                throw new IllegalArgumentException("Invalid session credential");
            }
        }
        return "BDUSS=" + bduss + "; Path=/; Secure; HttpOnly; SameSite=Lax";
    }

    public static boolean isPublicationPath(String path) {
        if (path == null) return false;
        // HttpUrl has already canonicalized dot segments. Compare decoded, case-insensitive paths.
        String normalized = path.toLowerCase(java.util.Locale.ROOT).replaceAll("/+$", "");
        switch (normalized) {
            case "/c/c/post/add":
            case "/c/c/thread/add":
            case "/c/s/uploadpicture":
            case "/mo/q/cooluploadpic":
            case "/mo/q/apubpost":
                return true;
            default:
                return false;
        }
    }
}
