package com.huanchengfly.tieba.post.utils;

import java.util.Locale;

/** Exact host classification, independent of transport policy. HTTP remains supported here. */
public final class TrustedWebHosts {
    private TrustedWebHosts() {}

    public static boolean isWebScheme(String scheme) {
        return "http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme);
    }

    public static boolean isTiebaHost(String host) {
        if (host == null) return false;
        switch (host.toLowerCase(Locale.ROOT)) {
            case "tieba.baidu.com":
            case "wapp.baidu.com":
            case "tiebac.baidu.com":
                return true;
            default:
                return false;
        }
    }

    /** No suffix, IDN, or trailing-dot normalization: unlisted hosts remain external. */
    public static boolean isInternalHost(String host) {
        if (isTiebaHost(host)) return true;
        if (host == null) return false;
        switch (host.toLowerCase(Locale.ROOT)) {
            case "wappass.baidu.com":
            case "ufosdk.baidu.com":
            case "m.help.baidu.com":
                return true;
            default:
                return false;
        }
    }
}
