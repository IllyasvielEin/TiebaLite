package com.huanchengfly.tieba.post.utils;

import org.junit.Test;
import java.net.URI;
import static org.junit.Assert.*;

public class TrustedWebHostsTest {
    @Test public void acceptsOnlyKnownHostsCaseInsensitively() {
        for (String host : new String[]{"tieba.baidu.com", "wapp.baidu.com", "tiebac.baidu.com", "TIEBA.BAIDU.COM"}) {
            assertTrue(TrustedWebHosts.isTiebaHost(host));
            assertTrue(TrustedWebHosts.isInternalHost(host));
        }
        for (String host : new String[]{"wappass.baidu.com", "ufosdk.baidu.com", "m.help.baidu.com"}) {
            assertFalse(TrustedWebHosts.isTiebaHost(host));
            assertTrue(TrustedWebHosts.isInternalHost(host));
        }
    }

    @Test public void rejectsLookalikesSubdomainsIdnAndTrailingDots() {
        for (String host : new String[]{null, "", "tieba.baidu.com.evil.example", "eviltieba.baidu.com",
                "evil.wappass.baidu.com", "ufosdk.baidu.com.evil", "m.help.baidu.com.evil",
                "tieba.baidu.com.", "ｔieba.baidu.com", "xn--tieba-9za.baidu.com", "tieba.baidu.com@evil.example"}) {
            assertFalse(TrustedWebHosts.isTiebaHost(host));
            assertFalse(TrustedWebHosts.isInternalHost(host));
        }
    }

    @Test public void classifiesParsedHostNotUserInfoOrPath() throws Exception {
        assertFalse(TrustedWebHosts.isInternalHost(new URI("https://tieba.baidu.com@evil.example/").getHost()));
        assertFalse(TrustedWebHosts.isInternalHost(new URI("https://evil.example/tieba.baidu.com").getHost()));
        assertTrue(TrustedWebHosts.isInternalHost(new URI("http://user@tieba.baidu.com/").getHost()));
    }

    @Test public void preservesHttpAndHttpsButRejectsLookalikeSchemes() {
        for (String scheme : new String[]{"http", "https", "HTTP", "HTTPS"}) assertTrue(TrustedWebHosts.isWebScheme(scheme));
        for (String scheme : new String[]{null, "", "httpx", "https-evil", "javascript", "file", "intent"}) assertFalse(TrustedWebHosts.isWebScheme(scheme));
    }
}
