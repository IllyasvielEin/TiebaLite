package com.huanchengfly.tieba.post.diagnostics

import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Category
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Host
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.RedirectScheme
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Source
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Stage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.Handshake
import okhttp3.Response
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Proxy

/** No persistence, logging, analytics, or diagnostic network requests. */
object AvatarDiagnostics {
    data class Session(val enabled: Boolean, val generation: Long)

    val store = AvatarDiagnosticStore()
    private val mutableSnapshot = MutableStateFlow(store.snapshot())
    private val mutableSession = MutableStateFlow(Session(false, 0))
    val snapshots = mutableSnapshot.asStateFlow()
    val sessions = mutableSession.asStateFlow()

    init {
        store.observe { snapshot ->
            mutableSnapshot.value = snapshot
            mutableSession.value = Session(snapshot.enabled, snapshot.generation)
        }
    }

    /** Observe only the existing known avatar route. Other image requests remain unobserved. */
    val networkListenerFactory = EventListener.Factory { call ->
        val url = call.request().url
        val knownPortraitRoute = url.host == "tb.himg.baidu.com" &&
            (url.encodedPath.startsWith("/sys/portrait/item/") ||
                url.encodedPath.startsWith("/sys/portraith/item/"))
        val lease = if (knownPortraitRoute) {
            store.open(
                Source.NETWORK,
                if (url.isHttps) AvatarDiagnosticStore.InputKind.HTTPS_URL
                else AvatarDiagnosticStore.InputKind.HTTP_URL,
                Host.AVATAR_CDN,
            )
        } else null
        if (lease == null) EventListener.NONE else object : EventListener() {
            override fun callStart(call: Call) = store.record(lease, Stage.START)

            override fun dnsStart(call: Call, domainName: String) = store.record(lease, Stage.DNS)

            override fun connectStart(call: Call, inetSocketAddress: InetSocketAddress, proxy: Proxy) =
                store.record(lease, Stage.CONNECT)

            override fun secureConnectStart(call: Call) = store.record(lease, Stage.TLS)

            override fun secureConnectEnd(call: Call, handshake: Handshake?) = store.record(lease, Stage.TLS_OK)

            override fun responseHeadersEnd(call: Call, response: Response) {
                // Resolve only to fixed scheme/host buckets. Never retain Location or any URL.
                val location = if (response.code in 300..399) response.header("Location") else null
                val redirect = location?.let { response.request.url.resolve(it) }
                store.record(
                    lease, Stage.RESPONSE, Category.NONE, response.code,
                    when {
                        redirect?.scheme == "https" -> RedirectScheme.HTTPS
                        redirect?.scheme == "http" -> RedirectScheme.HTTP
                        location != null -> RedirectScheme.OTHER
                        else -> RedirectScheme.NONE
                    },
                    if (location != null && redirect == null) Host.OTHER
                    else AvatarDiagnosticStore.classifyHost(redirect?.host),
                )
            }

            override fun callEnd(call: Call) = store.record(lease, Stage.COMPLETE)

            override fun callFailed(call: Call, ioe: IOException) {
                if (call.isCanceled()) store.record(lease, Stage.CANCELLED)
                else store.recordError(lease, ioe)
            }
        }
    }
}
