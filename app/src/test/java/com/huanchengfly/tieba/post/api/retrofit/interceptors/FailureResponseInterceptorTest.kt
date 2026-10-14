package com.huanchengfly.tieba.post.api.retrofit.interceptors

import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaApiException
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Interceptor
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody
import okio.Buffer
import okio.BufferedSource
import okio.ForwardingSource
import okio.GzipSink
import okio.GzipSource
import okio.Source
import okio.Timeout
import okio.buffer
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.io.InterruptedIOException
import java.util.concurrent.CancellationException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class FailureResponseInterceptorTest {
    private val limit = FailureResponseInterceptor.MAX_JSON_RESPONSE_BYTES
    private val validResponse = "{\"error_code\":0,\"data\":{\"text\":\"synthetic\",\"unknown\":[1,2]}}".toByteArray()

    private class TrackingBody(
        payload: Source,
        private val advertisedLength: Long,
        private val mediaType: MediaType? = null,
    ) : ResponseBody() {
        var bytesRead = 0L
        var closed = false
        private val trackedSource = object : ForwardingSource(payload) {
            override fun read(sink: Buffer, byteCount: Long): Long =
                super.read(sink, byteCount).also { if (it > 0) bytesRead += it }

            override fun close() {
                closed = true
                super.close()
            }
        }.buffer()

        override fun contentType(): MediaType? = mediaType
        override fun contentLength(): Long = advertisedLength
        override fun source(): BufferedSource = trackedSource
    }

    private fun body(bytes: ByteArray, advertised: Long = bytes.size.toLong(), mediaType: MediaType? = null) =
        TrackingBody(Buffer().write(bytes), advertised, mediaType)

    private fun request() = Request.Builder().url("https://unit-test.invalid/c/f/pb/page").build()

    // A terminal application interceptor supplies fixtures without a socket,
    // account, credential, or dependency on Android application state.
    private fun client(body: ResponseBody, code: Int = 200) = OkHttpClient.Builder()
        .addInterceptor(FailureResponseInterceptor)
        .addInterceptor(Interceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(code).message("synthetic").body(body).build()
        }).build()

    private fun repeatedSource(total: Long): Source = object : Source {
        private var remaining = total
        private val chunk = ByteArray(8192) { ' '.code.toByte() }
        override fun read(sink: Buffer, byteCount: Long): Long {
            if (byteCount == 0L) return 0
            if (remaining == 0L) return -1
            val count = minOf(byteCount, remaining, chunk.size.toLong()).toInt()
            sink.write(chunk, 0, count)
            remaining -= count
            return count.toLong()
        }
        override fun timeout(): Timeout = Timeout.NONE
        override fun close() = Unit
    }

    private fun gzipBody(bytes: ByteArray): TrackingBody {
        val compressed = Buffer()
        GzipSink(compressed).buffer().use { it.write(bytes) }
        // Models the decompressed, unknown-length body received by an application
        // interceptor after OkHttp's transparent-gzip bridge, not network gzip QA.
        return TrackingBody(GzipSource(compressed), -1)
    }

    @Test fun preservesSuccessfulBytesAndCallerOwnershipForEveryLengthShape() {
        for (advertised in listOf(validResponse.size.toLong(), -1L, 0L, 1L, limit)) {
            val body = body(validResponse, advertised)
            client(body).newCall(request()).execute().use {
                assertFalse(body.closed)
                // Source reads also exercise deliberately lying Content-Length;
                // ResponseBody.bytes() independently rejects length mismatches.
                assertArrayEquals(validResponse, it.body!!.source().readByteArray())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun preservesEveryBusinessErrorCodeAndMessageAliasAndClosesResponse() {
        for (codeField in listOf("error_code", "errno", "no")) {
            for (messageField in listOf("error_msg", "errmsg", "error")) {
                val body = body("{\"$codeField\":42,\"$messageField\":\"denied\"}".toByteArray(), 0)
                val failure = assertThrows(TiebaApiException::class.java) {
                    client(body).newCall(request()).execute()
                }
                assertEquals(42, failure.code)
                assertEquals("denied", failure.message)
                assertTrue(body.closed)
            }
        }
        val nested = body("{\"errno\":42,\"error\":{\"errmsg\":\"nested message\"}}".toByteArray(), -1)
        assertEquals("nested message", assertThrows(TiebaApiException::class.java) {
            client(nested).newCall(request()).execute()
        }.message)
        assertTrue(nested.closed)
    }

    @Test fun respectsGsonAndTheResponseCharset() {
        val charset = charset("UTF-16LE")
        val bytes = "{\"errno\":42,\"errmsg\":\"拒绝请求\"}".toByteArray(charset)
        val body = body(bytes, -1, "application/json; charset=utf-16le".toMediaType())
        assertEquals("拒绝请求", assertThrows(TiebaApiException::class.java) {
            client(body).newCall(request()).execute()
        }.message)
        assertTrue(body.closed)
        val success = body(validResponse, -1, "application/json; charset=utf-8".toMediaType())
        client(success).newCall(request()).execute().use {
            assertEquals("UTF-8", it.body!!.contentType()!!.charset()!!.name())
            assertArrayEquals(validResponse, it.body!!.source().readByteArray())
        }
    }

    @Test fun missingNullAndArrayMessagesRetainTheBusinessCodeAndSafeFallback() {
        for (json in listOf(
            "{\"error_code\":42}",
            "{\"error_code\":42,\"error_msg\":null}",
            "{\"errno\":42,\"errmsg\":[]}",
            "{\"no\":42,\"error\":\"\"}",
        )) {
            val body = body(json.toByteArray(), -1)
            val failure = assertThrows(TiebaApiException::class.java) {
                client(body).newCall(request()).execute()
            }
            assertEquals(42, failure.code)
            assertEquals("未知错误", failure.message)
            assertTrue(body.closed)
        }
    }

    @Test fun leavesValidNonEnvelopeJsonForItsEndpointConverter() {
        for (json in listOf("[]", "[1,2]", "\"text\"", "123", "null", "{\"data\":[1]}", "{\"error\":{\"other\":1}}")) {
            val bytes = json.toByteArray()
            val body = body(bytes, -1)
            client(body).newCall(request()).execute().use {
                assertFalse(body.closed)
                assertArrayEquals(bytes, it.body!!.source().readByteArray())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun syntaxProbeFailuresKeepTheOriginalConverterFallback() {
        for (json in listOf("{\"error_code\":", "{\"error_code\":0,", "{\"data\":\"unterminated", "{\"error_code\":\"not a number\"}")) {
            val bytes = json.toByteArray()
            val body = body(bytes, -1)
            client(body).newCall(request()).execute().use {
                assertFalse(body.closed)
                assertArrayEquals(bytes, it.body!!.source().readByteArray())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun preservesEmptySuccessfulAndHttpErrorBodies() {
        for (code in listOf(200, 503)) {
            for (advertised in listOf(0L, -1L)) {
                val body = body(byteArrayOf(), advertised)
                client(body, code).newCall(request()).execute().use {
                    assertEquals(code, it.code)
                    assertFalse(body.closed)
                    assertArrayEquals(byteArrayOf(), it.body!!.source().readByteArray())
                }
                assertTrue(body.closed)
            }
        }
    }

    @Test fun boundsHttpErrorBodiesWithoutProbingTheirBusinessEnvelope() {
        for (bytes in listOf("not JSON".toByteArray(), "{\"errno\":42,\"error\":\"denied\"}".toByteArray())) {
            val body = body(bytes, 0)
            client(body, 503).newCall(request()).execute().use {
                assertEquals(503, it.code)
                assertFalse(body.closed)
                assertArrayEquals(bytes, it.body!!.source().readByteArray())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun rejectsAdvertisedOversizeWithoutReadingForSuccessAndHttpError() {
        for (code in listOf(200, 503)) {
            val body = TrackingBody(repeatedSource(limit * 4), limit + 1)
            val failure = assertThrows(IOException::class.java) { client(body, code).newCall(request()).execute() }
            assertTrue(failure.message!!.contains("JSON response exceeds"))
            assertEquals(0L, body.bytesRead)
            assertTrue(body.closed)
        }
    }

    @Test fun boundsUnknownZeroAndUnderreportedLengthsWithoutDraining() {
        for (code in listOf(200, 503)) {
            for (advertised in listOf(-1L, 0L, 1L, limit)) {
                val body = TrackingBody(repeatedSource(limit * 4), advertised)
                assertThrows(IOException::class.java) { client(body, code).newCall(request()).execute() }
                assertTrue(body.bytesRead >= limit + 1)
                assertTrue("At most one Okio segment of read-ahead", body.bytesRead <= limit + 8192)
                assertTrue(body.closed)
            }
        }
    }

    @Test fun acceptsExactlyTheLimitAndRejectsOneMoreDecompressedByte() {
        val payload = Buffer().writeUtf8("{\"error_code\":0}")
        val spaces = ByteArray((limit - payload.size).toInt()) { ' '.code.toByte() }
        payload.write(spaces)
        for (code in listOf(200, 503)) {
            val accepted = TrackingBody(payload.clone(), -1)
            client(accepted, code).newCall(request()).execute().use {
                assertFalse(accepted.closed)
                assertEquals(limit, it.body!!.source().readByteArray().size.toLong())
            }
            assertTrue(accepted.closed)
            val rejected = TrackingBody(payload.clone().writeByte(' '.code), -1)
            assertThrows(IOException::class.java) { client(rejected, code).newCall(request()).execute() }
            assertEquals(limit + 1, rejected.bytesRead)
            assertTrue(rejected.closed)
        }
    }

    @Test fun boundsDecompressedGzipIncludingHttpErrorsAndPreservesSmallBodies() {
        val small = gzipBody(validResponse)
        client(small).newCall(request()).execute().use {
            assertFalse(small.closed)
            assertArrayEquals(validResponse, it.body!!.source().readByteArray())
        }
        assertTrue(small.closed)
        for (code in listOf(200, 503)) {
            val large = gzipBody(ByteArray((limit + 1).toInt()))
            assertThrows(IOException::class.java) { client(large, code).newCall(request()).execute() }
            assertTrue(large.closed)
            assertTrue(large.bytesRead >= limit + 1)
            assertTrue(large.bytesRead <= limit + 8192)
        }
    }

    @Test fun readFailuresTimeoutsCancellationAndFatalErrorsAreNotParseFallbacks() {
        for (expected in listOf(
            IOException("read failed"),
            InterruptedIOException("timeout"),
            CancellationException("cancelled"),
            OutOfMemoryError("synthetic fatal error"),
        )) {
            val body = TrackingBody(object : Source {
                override fun read(sink: Buffer, byteCount: Long): Long = throw expected
                override fun timeout(): Timeout = Timeout.NONE
                override fun close() = Unit
            }, -1)
            val actual = assertThrows(expected.javaClass) { client(body).newCall(request()).execute() }
            assertSame(expected, actual)
            assertTrue(body.closed)
        }
    }

    @Test fun cancellationDuringReadingClosesTheOwnedBody() {
        lateinit var call: Call
        val body = TrackingBody(object : Source {
            override fun read(sink: Buffer, byteCount: Long): Long {
                call.cancel()
                throw IOException("Canceled")
            }
            override fun timeout(): Timeout = Timeout.NONE
            override fun close() = Unit
        }, -1)
        call = client(body).newCall(request())
        assertEquals("Canceled", assertThrows(IOException::class.java) { call.execute() }.message)
        assertTrue(call.isCanceled())
        assertTrue(body.closed)
    }

    @Test fun oversizeCompletesTheAsyncFailureCallback() {
        val body = TrackingBody(repeatedSource(limit + 1), -1)
        val client = client(body)
        val completed = CountDownLatch(1)
        val failure = AtomicReference<IOException>()
        val gotResponse = AtomicBoolean(false)
        try {
            client.newCall(request()).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    failure.set(e)
                    completed.countDown()
                }
                override fun onResponse(call: Call, response: Response) {
                    response.close()
                    gotResponse.set(true)
                    completed.countDown()
                }
            })
            assertTrue("Expected asynchronous failure", completed.await(5, TimeUnit.SECONDS))
            assertNotNull(failure.get())
            assertFalse(gotResponse.get())
            assertTrue(body.closed)
        } finally {
            client.dispatcher.executorService.shutdownNow()
            client.connectionPool.evictAll()
        }
    }
}
