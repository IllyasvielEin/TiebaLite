package com.huanchengfly.tieba.post.api.retrofit.interceptors

import com.huanchengfly.tieba.post.security.CredentialTransportPolicy
import com.huanchengfly.tieba.post.security.PublicationPolicy
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException

/** Runs before credential/signing interceptors. Clients must disable automatic redirects. */
class CredentialTransportInterceptor(baseUrl: String) : Interceptor {
    private val origin = baseUrl.toHttpUrl()

    init {
        require(origin.isHttps && origin.port == 443 && origin.username.isEmpty() && origin.password.isEmpty())
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val url = request.url
        if (!url.isHttps || url.host != origin.host || url.port != origin.port ||
            url.username.isNotEmpty() || url.password.isNotEmpty()) {
            // Do not put the URL or request body in an exception: either can contain credentials.
            throw IOException("Blocked an untrusted credential destination")
        }
        val path = "/" + url.pathSegments.joinToString("/")
        if (!PublicationPolicy.enabled && CredentialTransportPolicy.isPublicationPath(path)) {
            throw IOException(PublicationPolicy.DISABLED_MESSAGE)
        }
        val response = chain.proceed(request)
        if (response.code in setOf(300, 301, 302, 303, 307, 308)) {
            response.close()
            // Reject even same-origin redirects: do not replay signed bodies or credentials.
            throw IOException("Redirects are disabled for authenticated API requests")
        }
        return response
    }
}
