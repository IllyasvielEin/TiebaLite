package com.huanchengfly.tieba.post.api.retrofit.interceptors

import okhttp3.Response
import okhttp3.ResponseBody
import okio.BufferedSource
import java.io.IOException

/** Bounds the decompressed body and keeps ownership with the caller only on return. */
internal fun Response.withBoundedBody(
    maxBytes: Long,
    format: String,
    inspectSuccessfulBody: (ResponseBody, BufferedSource) -> Unit,
): Response {
    val body = body ?: return this
    var returnedToCaller = false
    try {
        if (body.contentLength() > maxBytes) {
            throw IOException("$format response exceeds the $maxBytes-byte safety limit")
        }
        val source = body.source()
        // Content-Length can be absent, dishonest, or removed by transparent gzip.
        // Probe the real decompressed bytes without consuming them. Okio may read
        // ahead by one segment; an oversized stream is never drained to EOF.
        if (source.request(maxBytes + 1)) {
            throw IOException("$format response exceeds the $maxBytes-byte safety limit")
        }
        // Retrofit can buffer non-2xx bodies too. Bound them without interpreting
        // their content as an API error envelope or changing their HTTP status.
        if (isSuccessful) inspectSuccessfulBody(body, source)
        returnedToCaller = true
        return this
    } finally {
        if (!returnedToCaller) close()
    }
}
