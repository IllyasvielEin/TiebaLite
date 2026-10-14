package com.huanchengfly.tieba.post.api;

import java.io.IOException;
import java.util.Objects;

/** Runs the production formatter without Android, Kotlin, or network dependencies. */
public final class CookieHeaderBuilderHarness {
    private static void equal(String expected, String actual) {
        if (!Objects.equals(expected, actual)) throw new AssertionError("Cookie formatting mismatch");
    }

    private static void rejected(String name, String value) throws Exception {
        try {
            CookieHeaderBuilder.pair(name, value);
            throw new AssertionError("Invalid cookie accepted");
        } catch (IOException expected) {
            if (!"Invalid cookie name".equals(expected.getMessage())
                    && !"Invalid cookie value".equals(expected.getMessage())) {
                throw new AssertionError("Cookie error exposed input");
            }
            if (expected.getCause() != null) throw new AssertionError("Cookie error retained input cause");
        }
    }

    public static void run() throws Exception {
        equal(null, CookieHeaderBuilder.pair("omitted", null));
        equal(null, CookieHeaderBuilder.pair("omitted", ""));
        equal("CUID=opaque|Vabc+/=%2F:token", CookieHeaderBuilder.pair("CUID", "opaque|Vabc+/=%2F:token"));
        equal("TBBRAND= Pixel 9 Pro ", CookieHeaderBuilder.pair("TBBRAND", " Pixel 9 Pro "));
        equal("BDUSS=synthetic=opaque/token", CookieHeaderBuilder.pair("BDUSS", "synthetic=opaque/token"));
        equal("punct!#$%&'*+-.^_`|~=value", CookieHeaderBuilder.pair("punct!#$%&'*+-.^_`|~", "value"));
        for (int c = 0; c < 128; c++) {
            char ch = (char) c;
            if ((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
                    || (ch >= '0' && ch <= '9') || "!#$%&'*+-.^_`|~".indexOf(ch) >= 0) {
                equal("a" + ch + "b=value", CookieHeaderBuilder.pair("a" + ch + "b", "value"));
            } else {
                rejected("a" + ch + "b", "value");
            }
            if (c >= 0x20 && c < 0x7F && ch != ';') {
                equal("test=before" + ch + "after", CookieHeaderBuilder.pair("test", "before" + ch + "after"));
            } else {
                rejected("test", "before" + ch + "after");
            }
        }
        for (String name : new String[]{null, "", "bad name", "bad=name", "bad:name", "设备"}) {
            rejected(name, "synthetic-secret");
        }
        for (String value : new String[]{"secret;injected=1", "secret\r\ninjected: 1", "secret\tvalue",
                "secret\u007Fvalue", "设备", "secret\u0080value"}) {
            rejected("BDUSS", value);
        }
    }

    public static void main(String[] args) throws Exception {
        run();
        System.out.println("Production cookie formatter ASCII, preservation, and failure scenarios passed");
    }
}
