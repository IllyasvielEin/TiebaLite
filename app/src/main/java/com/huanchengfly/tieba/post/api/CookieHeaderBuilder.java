package com.huanchengfly.tieba.post.api;

import java.io.IOException;

/** Formats one caller-built cookie without rewriting its opaque value. */
public final class CookieHeaderBuilder {
    private CookieHeaderBuilder() {}

    public static String pair(String name, String value) throws IOException {
        if (value == null || value.isEmpty()) return null;
        if (name == null || name.isEmpty()) throw new IOException("Invalid cookie name");
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                    || (c >= '0' && c <= '9') || "!#$%&'*+-.^_`|~".indexOf(c) >= 0)) {
                throw new IOException("Invalid cookie name");
            }
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            // Keep device-model spaces and opaque CUID punctuation. Reject separators,
            // controls, and non-ASCII characters that OkHttp cannot put in a header.
            // IOException reaches OkHttp's onFailure rather than killing its dispatcher.
            if (c == ';' || c < 0x20 || c >= 0x7F) {
                throw new IOException("Invalid cookie value");
            }
        }
        return name + "=" + value;
    }
}
