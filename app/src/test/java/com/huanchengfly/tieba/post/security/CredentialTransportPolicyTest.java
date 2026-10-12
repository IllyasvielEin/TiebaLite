package com.huanchengfly.tieba.post.security;

import org.junit.Test;
import static org.junit.Assert.*;

public class CredentialTransportPolicyTest {
    @Test public void onlyExactHttpsWebOriginsCanReceiveCookies() {
        for (String host : new String[]{"tieba.baidu.com", "tiebac.baidu.com", "wapp.baidu.com"}) {
            assertTrue(CredentialTransportPolicy.permitsWebCookie("https", host, 443, null));
            assertFalse(CredentialTransportPolicy.permitsWebCookie("http", host, -1, null));
            assertFalse(CredentialTransportPolicy.permitsWebCookie("https", host, 444, null));
            assertFalse(CredentialTransportPolicy.permitsWebCookie("https", host, -1, "user"));
        }
        for (String host : new String[]{"baidu.com", "evil.baidu.com", "static.tieba.baidu.com",
                "tieba.baidu.com.evil.example", "tieba.baidu.com.", null}) {
            assertFalse(CredentialTransportPolicy.permitsWebCookie("https", host, -1, null));
        }
    }

    @Test public void cookiesAreSecureHttpOnlyHostOnlyAndSessionScoped() {
        String cookie = CredentialTransportPolicy.bdussCookie("synthetic_test-123");
        assertTrue(cookie.contains("; Secure"));
        assertTrue(cookie.contains("; HttpOnly"));
        assertTrue(cookie.contains("; SameSite=Lax"));
        assertFalse(cookie.contains("Domain="));
        assertFalse(cookie.contains("Max-Age="));
    }

    @Test(expected = IllegalArgumentException.class)
    public void cookieAttributeInjectionIsRejected() {
        CredentialTransportPolicy.bdussCookie("test; Domain=.baidu.com");
    }

    @Test public void publicationPathsBlockedWithoutDisablingOtherMutations() {
        for (String path : new String[]{"/c/c/post/add", "/c/c/thread/add", "/c/s/uploadPicture",
                "/mo/q/cooluploadpic", "/mo/q/apubpost", "/C/C/POST/ADD/"}) {
            assertTrue(path, CredentialTransportPolicy.isPublicationPath(path));
        }
        for (String path : new String[]{"/c/f/pb/page", "/c/c/post/addstore", "/c/c/post/addPollPost",
                "/c/c/img/portrait", "/c/c/user/follow", "/c/c/forum/sign", "/c/s/login"}) {
            assertFalse(path, CredentialTransportPolicy.isPublicationPath(path));
        }
    }
}
