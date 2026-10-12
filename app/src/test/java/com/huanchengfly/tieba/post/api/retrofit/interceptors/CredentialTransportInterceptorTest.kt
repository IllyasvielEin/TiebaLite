package com.huanchengfly.tieba.post.api.retrofit.interceptors

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class CredentialTransportInterceptorTest {
    // The terminal application interceptor returns a synthetic response: no socket/account needed.
    private fun client(terminal: Interceptor) = OkHttpClient.Builder()
        .followRedirects(false)
        .followSslRedirects(false)
        .addInterceptor(CredentialTransportInterceptor("https://tiebac.baidu.com/"))
        .addInterceptor(terminal)
        .build()

    private fun response(request: Request, code: Int = 200) = Response.Builder()
        .request(request).protocol(Protocol.HTTP_1_1).code(code).message("synthetic")
        .body("{}".toResponseBody()).build()

    @Test fun rejectsUntrustedOriginsBeforeCredentialsOrNetwork() {
        var reached = false
        val client = client { reached = true; response(it.request()) }
        for (url in listOf("http://tiebac.baidu.com/c/s/login", "https://evil.example/",
            "https://tiebac.baidu.com.evil.example/", "https://tiebac.baidu.com:444/",
            "https://user:password@tiebac.baidu.com/")) {
            assertThrows(IOException::class.java) { client.newCall(Request.Builder().url(url).build()).execute() }
        }
        assertFalse(reached)
    }

    @Test fun rejectsEveryRedirectWithoutReplayingCredentials() {
        for (code in listOf(300, 301, 302, 303, 307, 308)) {
            for (location in listOf("http://tiebac.baidu.com/", "https://evil.example/", "/same-host")) {
                var calls = 0
                val client = client {
                    calls++
                    response(it.request(), code).newBuilder().header("Location", location).build()
                }
                assertFalse(client.followRedirects)
                assertFalse(client.followSslRedirects)
                assertThrows(IOException::class.java) {
                    client.newCall(Request.Builder().url("https://tiebac.baidu.com/c/s/login").build()).execute()
                }
                assertEquals(1, calls)
            }
        }
    }

    @Test fun blocksPublicationWithEncodedPathsAndQueriesBeforeProceeding() {
        var calls = 0
        val client = client { calls++; response(it.request()) }
        for (path in listOf("/c/c/post/add?cmd=309731", "/c/c/thread/add", "/c/s/uploadPicture",
            "/mo/q/cooluploadpic", "/mo/q/apubpost", "/c/c/post/%61dd")) {
            assertThrows(IOException::class.java) {
                client.newCall(Request.Builder().url("https://tiebac.baidu.com$path").build()).execute()
            }
        }
        assertEquals(0, calls)
        client.newCall(Request.Builder().url("https://tiebac.baidu.com/c/f/pb/page").build()).execute().close()
        assertEquals(1, calls)
    }
}
