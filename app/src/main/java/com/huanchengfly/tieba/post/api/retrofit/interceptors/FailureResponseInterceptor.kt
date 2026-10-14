package com.huanchengfly.tieba.post.api.retrofit.interceptors

import com.google.gson.Gson
import com.google.gson.stream.MalformedJsonException
import com.huanchengfly.tieba.post.api.models.CommonResponse
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaApiException
import okhttp3.Interceptor
import okhttp3.Response
import java.io.EOFException
import java.io.IOException
import java.util.concurrent.CancellationException

object FailureResponseInterceptor : Interceptor {
    // Independent from the protobuf limit: JSON is more verbose. This is a
    // defensive application default, not a measured maximum of Tieba responses.
    internal const val MAX_JSON_RESPONSE_BYTES = 16L * 1024 * 1024
    private val gson = Gson()

    override fun intercept(chain: Interceptor.Chain): Response {
        val response = chain.proceed(chain.request())
        return response.withBoundedBody(MAX_JSON_RESPONSE_BYTES, "JSON") { body, source ->
            val charset = body.contentType()?.charset(Charsets.UTF_8) ?: Charsets.UTF_8
            // Only the already bounded in-memory bytes are probed. Transport read
            // failures above remain IOExceptions, and the original bytes/charset
            // are still available to Retrofit's endpoint-specific converter.
            val commonResponse = source.buffer.clone().inputStream().reader(charset).use { reader ->
                try {
                    gson.fromJson<CommonResponse>(gson.newJsonReader(reader), CommonResponse::class.java)
                } catch (exception: RuntimeException) {
                    // Some endpoints return valid JSON that is not a CommonResponse.
                    // Preserve that existing converter fallback, never cancellation,
                    // wrapped I/O failures, or fatal VM errors.
                    when (exception) {
                        is CancellationException -> throw exception
                    }
                    when (val cause = exception.cause) {
                        // These are syntax/shape failures from the in-memory
                        // reader, after transport I/O completed successfully.
                        is MalformedJsonException, is EOFException -> Unit
                        is IOException -> throw cause
                        is CancellationException -> throw cause
                        is Error -> throw cause
                    }
                    null
                }
            } ?: return@withBoundedBody

            if (commonResponse.errorCode != 0) {
                throw TiebaApiException(commonResponse)
            }
        }
    }
}
