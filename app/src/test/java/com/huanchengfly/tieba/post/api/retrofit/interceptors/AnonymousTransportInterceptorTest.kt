package com.huanchengfly.tieba.post.api.retrofit.interceptors

import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class AnonymousTransportInterceptorTest {
    @Test fun imageRequestsUpgradeHttpsAndStripCredentials() {
        var received: Request? = null
        val client = OkHttpClient.Builder()
            .addInterceptor(AnonymousTransportInterceptor(true))
            .addInterceptor {
                received = it.request()
                Response.Builder().request(it.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("synthetic").body("".toResponseBody()).build()
            }.build()
        client.newCall(Request.Builder().url("http://imgsrc.baidu.com/example.png")
            .header("Cookie", "BDUSS=synthetic").header("Authorization", "synthetic")
            .header("Referer", "https://example.invalid/?BDUSS=synthetic").build()).execute().close()
        assertTrue(received!!.url.isHttps)
        assertEquals("https://imgsrc.baidu.com/example.png", received!!.url.toString())
        assertEquals(443, received!!.url.port)
        assertNull(received!!.header("Cookie"))
        assertNull(received!!.header("Authorization"))
        assertNull(received!!.header("Referer"))
    }

    @Test fun rejectsCredentialQueriesAndDowngradesBeforeProceeding() {
        var reached = false
        val client = OkHttpClient.Builder().addInterceptor(AnonymousTransportInterceptor())
            .addInterceptor { reached = true; error("must not reach network") }.build()
        for (url in listOf("https://example.invalid/?BDUSS=synthetic", "https://example.invalid/?%62duss=synthetic",
            "https://example.invalid/?STOKEN=synthetic", "http://example.invalid/image.png",
            "https://user:pass@example.invalid/")) {
            assertThrows(IOException::class.java) { client.newCall(Request.Builder().url(url).build()).execute() }
        }
        assertFalse(reached)
    }
    @Test fun legacyAvatarMigrationPreservesEncodedDataAndAnonymousBoundaries() {
        var received: Request? = null
        val client = OkHttpClient.Builder().addInterceptor(AnonymousTransportInterceptor(true))
            .addInterceptor {
                received = it.request()
                Response.Builder().request(it.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("synthetic").body("".toResponseBody()).build()
            }.build()
        for (path in listOf("portrait", "portraith")) {
            client.newCall(Request.Builder()
                .url("http://tb.himg.baidu.com/sys/$path/item/a%2Fb+z?t=123&x=&x=2")
                .header("Cookie", "BDUSS=synthetic").header("Authorization", "synthetic").build()).execute().close()
            assertEquals("https://himg.bdimg.com/sys/$path/item/a%2Fb+z?t=123&x=&x=2", received!!.url.toString())
            assertNull(received!!.header("Cookie"))
            assertNull(received!!.header("Authorization"))
        }
        for (url in listOf("http://tb.himg.baidu.com/sys/portrait/item/a?BDUSS=synthetic",
            "https://user:pass@tb.himg.baidu.com/sys/portrait/item/a")) {
            received = null
            assertThrows(IOException::class.java) { client.newCall(Request.Builder().url(url).build()).execute() }
            assertNull(received)
        }
    }

    @Test fun legacyHttpAvatarStillRejectedByNonUpgradingNetworkGuard() {
        var reached = false
        val client = OkHttpClient.Builder().addInterceptor(AnonymousTransportInterceptor(false))
            .addInterceptor { reached = true; error("must not reach network") }.build()
        assertThrows(IOException::class.java) {
            client.newCall(Request.Builder().url("http://tb.himg.baidu.com/sys/portrait/item/a").build()).execute()
        }
        assertFalse(reached)
    }

}
