package com.huanchengfly.tieba.post.ui.widgets.media;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Map;
import java.util.TreeMap;

/** Saved-state discriminator, not a credential store or an authentication mechanism. */
public final class PlaybackSourceIdentity {
    private PlaybackSourceIdentity() {}

    public static String none() { return "v1:none"; }

    public static String forRaw(int resourceId) {
        MessageDigest digest = digest();
        add(digest, "raw");
        add(digest, Integer.toString(resourceId));
        return finish(digest);
    }

    public static String forNetwork(String url, Map<String, String> headers) {
        MessageDigest digest = digest();
        add(digest, "network");
        add(digest, url);
        // Source equality is independent of Map insertion order. Include header values only
        // in the digest, so account/source variants cannot inherit another variant's state.
        for (Map.Entry<String, String> header : new TreeMap<>(headers).entrySet()) {
            add(digest, header.getKey());
            add(digest, header.getValue());
        }
        return finish(digest);
    }

    public static <T> T restoreOrDefault(String savedIdentity, String currentIdentity,
                                         T savedState, T initialState) {
        return savedIdentity != null && savedIdentity.equals(currentIdentity) ? savedState : initialState;
    }

    private static MessageDigest digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is required", impossible);
        }
    }

    private static void add(MessageDigest digest, String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        // Length framing prevents ambiguous concatenations of URLs, header names and values.
        digest.update((byte) (bytes.length >>> 24));
        digest.update((byte) (bytes.length >>> 16));
        digest.update((byte) (bytes.length >>> 8));
        digest.update((byte) bytes.length);
        digest.update(bytes);
    }

    private static String finish(MessageDigest digest) {
        char[] alphabet = "0123456789abcdef".toCharArray();
        StringBuilder result = new StringBuilder("v1:");
        for (byte value : digest.digest()) {
            result.append(alphabet[(value & 0xff) >>> 4]);
            result.append(alphabet[value & 0x0f]);
        }
        return result.toString();
    }
}
