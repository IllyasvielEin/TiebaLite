package com.huanchengfly.tieba.post.security;

public final class AvatarUrlPolicyHarness {
    private static void equal(String expected, String actual) {
        if (!java.util.Objects.equals(expected, actual)) throw new AssertionError("Avatar URL policy mismatch");
    }
    public static void run() {
        equal("", AvatarUrlPolicy.small(null)); equal("", AvatarUrlPolicy.large(""));
        equal("https://himg.bdimg.com/sys/portrait/item/token?t=1", AvatarUrlPolicy.small("token?t=1"));
        equal("https://himg.bdimg.com/sys/portraith/item/token%2Bwith+plus?t=1", AvatarUrlPolicy.large("token%2Bwith+plus?t=1"));
        String suffix = "a%2Fb%2B+c?t=123&x=&x=2&blank&encoded=%2F%3F#part%20one";
        for (String path : new String[]{"/sys/portrait/item/", "/sys/portraith/item/"}) {
            for (String origin : new String[]{"http://tb.himg.baidu.com", "http://tb.himg.baidu.com:80", "https://tb.himg.baidu.com", "https://tb.himg.baidu.com:443", "HTTPS://TB.HIMG.BAIDU.COM"}) {
                String url = origin + path + suffix;
                equal("https://himg.bdimg.com" + path + suffix, AvatarUrlPolicy.normalizeLegacy(url));
                equal("https://himg.bdimg.com" + path + suffix, AvatarUrlPolicy.small(url));
                equal("https://himg.bdimg.com" + path + suffix, AvatarUrlPolicy.large(url));
            }
            for (String tail : new String[]{"../private", "./private", "%2e%2E/private", ".%2e/private", "%2e./private", "safe/../../private", "safe/%2e/private"}) {
                String traversal = "https://tb.himg.baidu.com" + path + tail;
                equal(traversal, AvatarUrlPolicy.normalizeLegacy(traversal));
                equal(traversal, AvatarUrlPolicy.small(traversal));
                equal(traversal, AvatarUrlPolicy.large(traversal));
            }
            equal("https://himg.bdimg.com" + path + "a?#", AvatarUrlPolicy.normalizeLegacy("http://tb.himg.baidu.com" + path + "a?#"));
        }
        for (String unchanged : new String[]{
                "https://himg.bdimg.com/sys/portrait/item/a?x=1", "https://other.example/sys/portrait/item/a",
                "https://tb.himg.baidu.com.evil.example/sys/portrait/item/a", "https://tb.himg.baidu.com./sys/portrait/item/a",
                "https://tb.himg.baidu.com@other.example/sys/portrait/item/a", "https://user@tb.himg.baidu.com/sys/portrait/item/a",
                "https://user:pass@tb.himg.baidu.com/sys/portrait/item/a", "http://tb.himg.baidu.com:443/sys/portrait/item/a",
                "https://tb.himg.baidu.com:80/sys/portrait/item/a", "https://tb.himg.baidu.com:8443/sys/portrait/item/a",
                "https://tb.himg.baidu.com/sys/portrait/item/", "https://tb.himg.baidu.com/sys/portraith/item/",
                "https://tb.himg.baidu.com/sys/portrait/items/a", "https://tb.himg.baidu.com/not-avatar/a",
                "https://tb.himg.baidu.com/SYS/portrait/item/a", "ftp://tb.himg.baidu.com/sys/portrait/item/a",
                "//tb.himg.baidu.com/sys/portrait/item/a", "https://tb.himg.baidu.com/sys/portrait/item/bad%escape"}) {
            equal(unchanged, AvatarUrlPolicy.normalizeLegacy(unchanged));
        }
        equal(null, AvatarUrlPolicy.normalizeLegacy(null));
    }
    public static void main(String[] args) { run(); System.out.println("Avatar URL route-preservation scenarios passed"); }
}
