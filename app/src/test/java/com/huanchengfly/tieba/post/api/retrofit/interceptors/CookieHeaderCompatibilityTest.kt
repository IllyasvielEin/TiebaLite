package com.huanchengfly.tieba.post.api.retrofit.interceptors

import androidx.compose.runtime.mutableStateOf
import com.huanchengfly.tieba.post.api.Header
import com.huanchengfly.tieba.post.api.getCookie
import com.huanchengfly.tieba.post.models.database.Account
import com.huanchengfly.tieba.post.utils.AccountUtil
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class CookieHeaderCompatibilityTest {
    private fun response(request: Request) = Response.Builder()
        .request(request).protocol(Protocol.HTTP_1_1).code(200).message("synthetic")
        .body("{}".toResponseBody()).build()

    @Test fun suppliersRunOnceInOrderAndOnlyNullOrEmptyValuesAreOmitted() {
        val calls = mutableListOf<String>()
        fun entry(name: String, value: String?) = name to {
            calls += name
            value
        }
        val cookie = getCookie(
            entry("CUID", "opaque|Vabc+/=%2F:token"),
            entry("missing", null),
            entry("TBBRAND", " Pixel 9 Pro "),
            entry("empty", ""),
            entry("BDUSS", "synthetic=opaque/token"),
            entry("STOKEN", "synthetic+/%token"),
        )
        assertEquals("CUID=opaque|Vabc+/=%2F:token; TBBRAND= Pixel 9 Pro ; BDUSS=synthetic=opaque/token; STOKEN=synthetic+/%token", cookie)
        assertEquals(listOf("CUID", "missing", "TBBRAND", "empty", "BDUSS", "STOKEN"), calls)
        assertEquals("", getCookie())
        assertEquals("", getCookie("missing" to { null }, "empty" to { "" }))
        assertEquals("space= ", getCookie("space" to { " " }))
    }

    @Test fun commonHeaderEmitsFourCallerCookieShapesAndPreservesAnExplicitCookie() {
        val cuid = "opaque|Vabc+/=%2F:token"
        val official = listOf("ka" to "open", "CUID" to cuid, "TBBRAND" to "Pixel 9 Pro")
        val post = listOf("BAIDUZID" to "synthetic-zid") + official
        val hybrid = listOf(
            "CUID" to cuid, "TBBRAND" to "Pixel 9 Pro", "cuid_galaxy2" to cuid,
            "SP_FW_VER" to "3.340.42", "SG_FW_VER" to "1.38.0",
            "BDUSS" to "synthetic-bduss", "STOKEN" to "synthetic-stoken",
            "BAIDU_WISE_UID" to "synthetic-client", "USER_JUMP" to "-1",
            "BDUSS_BFESS" to "synthetic-bduss", "BAIDUID" to "synthetic-baidu",
            "BAIDUID_BFESS" to "synthetic-baidu", "mo_originid" to "2",
            "BAIDUZID" to "synthetic-zid",
        )
        val officialExpected = "ka=open; CUID=opaque|Vabc+/=%2F:token; TBBRAND=Pixel 9 Pro"
        val variants = listOf(
            Triple("V12", official, officialExpected),
            Triple("V22", official, officialExpected),
            Triple("POST", post, "BAIDUZID=synthetic-zid; $officialExpected"),
            Triple("HYBRID", hybrid, "CUID=opaque|Vabc+/=%2F:token; TBBRAND=Pixel 9 Pro; cuid_galaxy2=opaque|Vabc+/=%2F:token; SP_FW_VER=3.340.42; SG_FW_VER=1.38.0; BDUSS=synthetic-bduss; STOKEN=synthetic-stoken; BAIDU_WISE_UID=synthetic-client; USER_JUMP=-1; BDUSS_BFESS=synthetic-bduss; BAIDUID=synthetic-baidu; BAIDUID_BFESS=synthetic-baidu; mo_originid=2; BAIDUZID=synthetic-zid"),
        )
        for ((label, entries, expected) in variants) {
            for (explicit in listOf(null, "caller=synthetic")) {
                var received: Request? = null
                val client = OkHttpClient.Builder()
                    .addInterceptor(CommonHeaderInterceptor(Header.COOKIE to {
                        getCookie(*entries.map { (name, value) -> name to { value } }.toTypedArray())
                    }))
                    .addInterceptor { received = it.request(); response(it.request()) }
                    .build()
                val request = Request.Builder().url("https://tiebac.baidu.com/c/f/pb/page").apply {
                    if (explicit != null) header(Header.COOKIE, explicit)
                }.build()
                client.newCall(request).execute().close()
                assertEquals(label, explicit ?: expected, received!!.header(Header.COOKIE))
                assertEquals(1, received!!.headers.values(Header.COOKIE).size)
            }
        }
    }

    // Test-only fixture: no preferences, database, real account, or production API changes.
    // Serialize access and restore the exact prior state object even when assertions fail.
    private fun <T> withSavedCookie(cookie: String?, block: () -> T): T = synchronized(AccountUtil) {
        val field = AccountUtil::class.java.getDeclaredField("mutableCurrentAccountState")
        field.isAccessible = true
        val original = field.get(AccountUtil)
        field.set(AccountUtil, mutableStateOf<Account?>(cookie?.let { Account(cookie = it) }))
        try {
            block()
        } finally {
            field.set(AccountUtil, original)
        }
    }

    private fun hybridRequest(optOut: Boolean, explicit: String? = null): Request {
        var received: Request? = null
        val client = OkHttpClient.Builder()
            .addInterceptor(CommonHeaderInterceptor(Header.COOKIE to {
                getCookie("CUID" to { "opaque|Vabc+/=%2F:token" },
                    "TBBRAND" to { "Pixel 9 Pro" }, "BDUSS" to { "synthetic-built" },
                    "STOKEN" to { "synthetic-stoken" })
            }))
            .addInterceptor(AddWebCookieInterceptor)
            .addInterceptor { received = it.request(); response(it.request()) }
            .build()
        val request = Request.Builder().url("https://tieba.baidu.com/mo/q/search/thread").apply {
            if (optOut) header(Header.ADD_WEB_COOKIE, Header.ADD_WEB_COOKIE_FALSE)
            if (explicit != null) header(Header.COOKIE, explicit)
        }.build()
        client.newCall(request).execute().close()
        return received!!
    }

    @Test fun hybridDefaultUsesSavedWebCookieAndOptOutRetainsBuiltCookie() = withSavedCookie(
        "BDUSS=synthetic-saved; STOKEN=synthetic-saved-stoken"
    ) {
        val default = hybridRequest(optOut = false)
        assertEquals("BDUSS=synthetic-saved; STOKEN=synthetic-saved-stoken", default.header(Header.COOKIE))
        assertEquals(1, default.headers.values(Header.COOKIE).size)
        val explicitDefault = hybridRequest(optOut = false, explicit = "caller=synthetic")
        assertEquals("BDUSS=synthetic-saved; STOKEN=synthetic-saved-stoken", explicitDefault.header(Header.COOKIE))
        assertEquals(1, explicitDefault.headers.values(Header.COOKIE).size)
        val optedOut = hybridRequest(optOut = true)
        assertEquals("CUID=opaque|Vabc+/=%2F:token; TBBRAND=Pixel 9 Pro; BDUSS=synthetic-built; STOKEN=synthetic-stoken",
            optedOut.header(Header.COOKIE))
        assertNull(optedOut.header(Header.ADD_WEB_COOKIE))
        assertEquals(1, optedOut.headers.values(Header.COOKIE).size)
    }

    @Test fun hybridOptOutPreservesExplicitCookieAndMissingSavedCookieKeepsExistingBehavior() {
        withSavedCookie("BDUSS=synthetic-saved") {
            val received = hybridRequest(optOut = true, explicit = "caller=synthetic")
            assertEquals("caller=synthetic", received.header(Header.COOKIE))
            assertNull(received.header(Header.ADD_WEB_COOKIE))
        }
        withSavedCookie(null) {
            assertEquals("", hybridRequest(optOut = false).header(Header.COOKIE))
        }
    }

    @Test fun invalidCookieFailsAsyncThroughOnFailureWithoutReachingNextInterceptor() {
        val invalid = listOf(
            "bad name" to "synthetic-secret",
            "BDUSS" to "synthetic-secret;injected=1",
            "BDUSS" to "synthetic-secret\r\ninjected: 1",
            "BDUSS" to "synthetic-secret\u0000",
            "BDUSS" to "synthetic-secret\tvalue",
            "BDUSS" to "synthetic-secret\u007F",
            "BDUSS" to "synthetic-secret设备",
        )
        for ((name, value) in invalid) {
            val callback = CountDownLatch(1)
            val failure = AtomicReference<IOException?>()
            val responses = AtomicInteger()
            val terminalCalls = AtomicInteger()
            val client = OkHttpClient.Builder()
                .addInterceptor(CommonHeaderInterceptor(Header.COOKIE to { getCookie(name to { value }) }))
                .addInterceptor { terminalCalls.incrementAndGet(); response(it.request()) }
                .build()
            try {
                client.newCall(Request.Builder().url("https://tiebac.baidu.com/c/f/pb/page").build())
                    .enqueue(object : Callback {
                        override fun onFailure(call: Call, e: IOException) {
                            failure.set(e)
                            callback.countDown()
                        }
                        override fun onResponse(call: Call, response: Response) {
                            responses.incrementAndGet()
                            response.close()
                            callback.countDown()
                        }
                    })
                assertTrue("Expected failure callback", callback.await(5, TimeUnit.SECONDS))
                assertNotNull(failure.get())
                assertTrue(failure.get()!!.message in listOf("Invalid cookie name", "Invalid cookie value"))
                assertNull(failure.get()!!.cause)
                assertEquals(0, responses.get())
                assertEquals(0, terminalCalls.get())
            } finally {
                client.dispatcher.executorService.shutdownNow()
                client.connectionPool.evictAll()
            }
        }
    }
}
