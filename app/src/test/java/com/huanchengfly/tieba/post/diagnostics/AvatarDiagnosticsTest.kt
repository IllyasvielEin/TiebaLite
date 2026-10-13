package com.huanchengfly.tieba.post.diagnostics

import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Category
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Stage
import okhttp3.EventListener
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

/** Manually invoke listener events; never execute a call or open a network connection. */
class AvatarDiagnosticsTest {
    @Test fun networkObserverIsOffByDefaultAndRestrictedToKnownRoute() {
        val store = AvatarDiagnostics.store
        store.setEnabled(false)
        val client = OkHttpClient()
        val avatar = client.newCall(Request.Builder()
            .url("https://tb.himg.baidu.com/sys/portrait/item/synthetic-secret").build())
        assertSame(EventListener.NONE, AvatarDiagnostics.networkListenerFactory.create(avatar))
        try {
            store.setEnabled(true)
            for (url in listOf("https://secret.example/sys/portrait/item/synthetic-secret",
                "https://tb.himg.baidu.com/not-an-avatar/synthetic-secret",
                "https://tb.himg.baidu.com.evil.example/sys/portrait/item/synthetic-secret",
                "https://himg.bdimg.com.evil.example/sys/portrait/item/synthetic-secret",
                "https://himg.bdimg.com/not-an-avatar/synthetic-secret")) {
                val call = client.newCall(Request.Builder().url(url).build())
                assertSame(EventListener.NONE, AvatarDiagnostics.networkListenerFactory.create(call))
            }
            assertEquals(0, store.snapshot().events.size)
        } finally {
            store.setEnabled(false)
        }
    }

    @Test fun listenerExportsOnlyBoundedMetadataAndRejectsLateEvents() {
        val store = AvatarDiagnostics.store
        store.setEnabled(false)
        try {
            store.setEnabled(true)
            val call = OkHttpClient().newCall(Request.Builder()
                .url("http://tb.himg.baidu.com/sys/portrait/item/synthetic-portrait?private=synthetic-query").build())
            val listener = AvatarDiagnostics.networkListenerFactory.create(call)
            listener.callStart(call)
            listener.dnsStart(call, "synthetic-private-dns.example")
            listener.secureConnectStart(call)
            val response = Response.Builder().request(call.request()).protocol(Protocol.HTTP_1_1)
                .code(302).message("synthetic-secret-message")
                .header("Location", "http://synthetic-private-host.example/private?token=synthetic-secret")
                .body("".toResponseBody()).build()
            listener.responseHeadersEnd(call, response)
            response.close()
            listener.callFailed(call, IOException("synthetic-private-exception-and-url"))
            val report = store.snapshot().report()
            for (secret in listOf("synthetic", "/sys/", "private=", "token=", "Location")) {
                assertFalse(secret, report.contains(secret))
            }
            assertEquals(Category.IO_OR_HTTP, store.snapshot().events.last().category)
            assertEquals(302, store.snapshot().events.first { it.stage == Stage.RESPONSE }.httpStatus)
            store.clear()
            listener.callFailed(call, IOException("late-secret"))
            listener.callEnd(call)
            assertEquals(0, store.snapshot().events.size)
            val currentListener = AvatarDiagnostics.networkListenerFactory.create(call)
            call.cancel()
            currentListener.callFailed(call, IOException("do-not-classify-cancellation-by-message"))
            assertEquals(Stage.CANCELLED, store.snapshot().events.single().stage)
        } finally {
            store.setEnabled(false)
        }
    }
    @Test fun newAvatarHostIsObservedAndReportedAsDistinctFixedBucket() {
        val store = AvatarDiagnostics.store
        store.setEnabled(false)
        try {
            store.setEnabled(true)
            for (path in listOf("portrait", "portraith")) {
                val call = OkHttpClient().newCall(Request.Builder()
                    .url("https://himg.bdimg.com/sys/$path/item/synthetic-secret").build())
                val listener = AvatarDiagnostics.networkListenerFactory.create(call)
                listener.callStart(call)
                assertEquals(AvatarDiagnosticStore.Host.HIMG_CDN, store.snapshot().events.last().host)
            }
            assertTrue(store.snapshot().report().contains("himg.bdimg.com"))
            assertFalse(store.snapshot().report().contains("synthetic-secret"))
        } finally { store.setEnabled(false) }
    }

}
