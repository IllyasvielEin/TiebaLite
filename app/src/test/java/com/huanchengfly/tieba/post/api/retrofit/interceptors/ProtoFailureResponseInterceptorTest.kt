package com.huanchengfly.tieba.post.api.retrofit.interceptors

import com.huanchengfly.tieba.post.api.models.protos.ProtoCommonResponse
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaApiException
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Interceptor
import okhttp3.MediaType
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
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class ProtoFailureResponseInterceptorTest {
    private val limit = ProtoFailureResponseInterceptor.MAX_PROTOBUF_RESPONSE_BYTES
    private val defaultPath = "/c/f/pb/page"
    // Empty Error and data messages, plus a forward-compatible unknown field.
    private val validResponse = byteArrayOf(0x0a, 0, 0x12, 0, 0x1a, 2, 0x61, 0x62)
    // Error { error_code = 42, error_msg = "denied" }.
    private val errorMessage = byteArrayOf(8, 42, 18, 6) + "denied".toByteArray()
    private val swappedResponses = mapOf(
        "/c/f/forum/getBawuInfo" to byteArrayOf(0x0a, 2, 0x0a, 0),
        "/c/f/forum/getLevelInfo" to byteArrayOf(0x0a, 2, 0x0a, 0),
        "/c/f/forum/getMemberInfo" to byteArrayOf(0x0a, 2, 0x0a, 0),
        "/c/c/post/addPollPost" to byteArrayOf(0x0a, 2, 8, 0),
    )

    private class TrackingBody(payload: Source, private val advertisedLength: Long) : ResponseBody() {
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

        override fun contentType(): MediaType? = null
        override fun contentLength(): Long = advertisedLength
        override fun source(): BufferedSource = trackedSource
    }

    private fun body(bytes: ByteArray, advertised: Long = bytes.size.toLong()) =
        TrackingBody(Buffer().write(bytes), advertised)

    private fun request(path: String = defaultPath) =
        Request.Builder().url("https://unit-test.invalid$path").build()

    // The terminal interceptor never opens a socket or reads account/app state.
    private fun client(body: ResponseBody, code: Int = 200) = OkHttpClient.Builder()
        .addInterceptor(ProtoFailureResponseInterceptor)
        .addInterceptor(Interceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(code).message("synthetic").body(body).build()
        }).build()

    private fun repeatedSource(total: Long): Source = object : Source {
        private var remaining = total
        private val chunk = ByteArray(8192)
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
        // This is the decompressed/unknown-length body seen after OkHttp's bridge.
        return TrackingBody(GzipSource(compressed), -1)
    }

    @Test fun leavesValidBodyAndUnknownFieldsIntactForTheRealConverter() {
        for (advertised in listOf(validResponse.size.toLong(), -1L)) {
            val body = body(validResponse, advertised)
            client(body).newCall(request()).execute().use {
                assertFalse(body.closed)
                assertArrayEquals(validResponse, it.body!!.bytes())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun acceptsEmptyBodiesWithKnownOrUnknownLength() {
        for (advertised in listOf(0L, -1L)) {
            val body = body(byteArrayOf(), advertised)
            client(body).newCall(request()).execute().use {
                assertArrayEquals(byteArrayOf(), it.body!!.bytes())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun preservesHttpErrorStatusAndBodyWithoutProtobufDecoding() {
        val bytes = "not a protobuf error body".toByteArray()
        val body = body(bytes)
        client(body, 503).newCall(request()).execute().use {
            assertEquals(503, it.code)
            assertFalse(body.closed)
            assertArrayEquals(bytes, it.body!!.bytes())
        }
        assertTrue(body.closed)
    }

    @Test fun preservesBusinessErrorAndClosesRejectedBody() {
        val body = body(byteArrayOf(0x0a, errorMessage.size.toByte()) + errorMessage)
        val failure = assertThrows(TiebaApiException::class.java) {
            client(body).newCall(request()).execute()
        }
        assertEquals(42, failure.code)
        assertEquals("denied", failure.message)
        assertTrue(body.closed)
    }

    @Test fun acceptsEveryDataFirstSchemaAndPreservesBytes() {
        for ((path, bytes) in swappedResponses) {
            val body = body(bytes)
            client(body).newCall(request(path)).execute().use {
                assertArrayEquals(bytes, it.body!!.bytes())
            }
            assertTrue(body.closed)
        }
    }

    @Test fun recognizesEveryDataFirstSchemasRealErrorField() {
        for ((path, data) in swappedResponses) {
            val body = body(data + byteArrayOf(0x12, errorMessage.size.toByte()) + errorMessage)
            val failure = assertThrows(TiebaApiException::class.java) {
                client(body).newCall(request(path)).execute()
            }
            assertEquals(42, failure.code)
            assertEquals("denied", failure.message)
            assertTrue(body.closed)
        }
    }

    @Test fun closesTruncatedAndMaliciousLengthResponsesAsIoFailures() {
        val malformed = listOf(
            byteArrayOf(0x0a, 2, 8), // Truncated nested Error varint.
            byteArrayOf(0x0a, -1, -1, -1, -1, 7), // Positive Int.MAX_VALUE length.
            byteArrayOf(0x1a, -1, -1, -1, -1, 7), // Oversized unknown field.
        )
        for (bytes in malformed) {
            val body = body(bytes)
            val failure = assertThrows(IOException::class.java) {
                client(body).newCall(request()).execute()
            }
            assertEquals("Malformed protobuf response", failure.message)
            assertNotNull(failure.cause)
            assertTrue(body.closed)
        }
    }

    @Test fun patchedWireRejectsOverflowPayloadsWithoutUncheckedExceptions() {
        // Test the dependency directly: an interceptor catch must not mask an old runtime.
        for (bytes in listOf(
            byteArrayOf(0x0a, -1, -1, -1, -1, 7),
            byteArrayOf(0x1a, -1, -1, -1, -1, 7),
        )) {
            assertThrows(IOException::class.java) { ProtoCommonResponse.ADAPTER.decode(bytes) }
            assertThrows(IOException::class.java) { ProtoCommonResponse.ADAPTER.decode(Buffer().write(bytes)) }
        }
    }

    @Test fun rejectsAdvertisedOversizeBeforeReadingForSuccessAndHttpError() {
        for (code in listOf(200, 503)) {
            val body = TrackingBody(repeatedSource(limit + 1), limit + 1)
            assertThrows(IOException::class.java) { client(body, code).newCall(request()).execute() }
            assertEquals(0L, body.bytesRead)
            assertTrue(body.closed)
        }
    }

    @Test fun boundsUnknownAndUnderreportedLengthsWithoutDrainingTheBody() {
        for (code in listOf(200, 503)) {
            for (advertised in listOf(-1L, 0L, 1L)) {
                val body = TrackingBody(repeatedSource(limit * 4), advertised)
                assertThrows(IOException::class.java) { client(body, code).newCall(request()).execute() }
                assertTrue(body.bytesRead >= limit + 1)
                assertTrue("Only one Okio segment of read-ahead is allowed", body.bytesRead <= limit + 8192)
                assertTrue(body.closed)
            }
        }
    }

    @Test fun acceptsExactlyTheLimitAndRejectsOneByteMore() {
        // Unknown length-delimited field 3: one tag + four varint length bytes.
        val payload = Buffer().writeByte(0x1a)
        var length = (limit - 5).toInt()
        while (length >= 128) {
            payload.writeByte((length and 127) or 128)
            length = length ushr 7
        }
        payload.writeByte(length)
        payload.write(ByteArray((limit - 5).toInt()))
        val bytes = payload.readByteArray()
        assertEquals(limit, bytes.size.toLong())
        val accepted = body(bytes, -1)
        client(accepted).newCall(request()).execute().use {
            assertEquals(limit, it.body!!.bytes().size.toLong())
        }
        assertTrue(accepted.closed)
        val rejected = TrackingBody(repeatedSource(limit + 1), -1)
        assertThrows(IOException::class.java) { client(rejected).newCall(request()).execute() }
        assertTrue(rejected.closed)
    }

    @Test fun boundsDecompressedGzipContentAndPreservesSmallResponses() {
        val small = gzipBody(validResponse)
        client(small).newCall(request()).execute().use {
            assertArrayEquals(validResponse, it.body!!.bytes())
        }
        assertTrue(small.closed)
        val large = gzipBody(ByteArray((limit + 1).toInt()))
        assertThrows(IOException::class.java) { client(large).newCall(request()).execute() }
        assertTrue(large.closed)
        assertTrue(large.bytesRead <= limit + 8192)
    }

    @Test fun closesBodyWhenReadingFails() {
        val body = TrackingBody(object : Source {
            override fun read(sink: Buffer, byteCount: Long): Long = throw IOException("read failed")
            override fun timeout(): Timeout = Timeout.NONE
            override fun close() = Unit
        }, -1)
        val failure = assertThrows(IOException::class.java) { client(body).newCall(request()).execute() }
        assertEquals("read failed", failure.message)
        assertTrue(body.closed)
    }

    @Test fun malformedResponseInvokesAsyncFailureInsteadOfHanging() {
        val body = body(byteArrayOf(0x0a, 2, 8))
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
            assertTrue("Expected an asynchronous failure callback", completed.await(5, TimeUnit.SECONDS))
            assertNotNull(failure.get())
            assertFalse(gotResponse.get())
            assertTrue(body.closed)
        } finally {
            client.dispatcher.executorService.shutdownNow()
            client.connectionPool.evictAll()
        }
    }
}
