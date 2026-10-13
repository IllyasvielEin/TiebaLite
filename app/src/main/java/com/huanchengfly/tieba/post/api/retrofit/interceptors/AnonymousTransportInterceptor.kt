package com.huanchengfly.tieba.post.api.retrofit.interceptors

import okhttp3.Interceptor
import okhttp3.Response
import com.huanchengfly.tieba.post.security.PublicDownloadPolicyException
import com.huanchengfly.tieba.post.security.PublicDownloadPolicyException.Reason

/** For image/public-download clients only; never share the authenticated API client/cookie jar. */
class AnonymousTransportInterceptor(private val upgradeHttp: Boolean = false) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        var url = request.url
        if (request.method != "GET" && request.method != "HEAD") {
            throw PublicDownloadPolicyException(Reason.METHOD)
        }
        if (url.username.isNotEmpty() || url.password.isNotEmpty() ||
            url.queryParameterNames.any { it.lowercase() in SECRET_QUERY_NAMES }) {
            throw PublicDownloadPolicyException(Reason.CREDENTIALS)
        }
        if (!url.isHttps) {
            if (!upgradeHttp || url.port != 80) throw PublicDownloadPolicyException(Reason.INSECURE_TRANSPORT)
            url = url.newBuilder().scheme("https").port(443).build()
        }
        val sanitized = request.newBuilder().url(url)
        for (header in request.headers.names()) {
            if (header.lowercase() in SECRET_HEADERS) sanitized.removeHeader(header)
        }
        return chain.proceed(sanitized.build())
    }

    private companion object {
        val SECRET_QUERY_NAMES = setOf("bduss", "bduss_bfess", "stoken", "ptoken", "cookie", "authorization", "access_token", "password")
        val SECRET_HEADERS = SECRET_QUERY_NAMES + setOf("cookie2", "proxy-authorization", "client_user_token", "referer")
    }
}
