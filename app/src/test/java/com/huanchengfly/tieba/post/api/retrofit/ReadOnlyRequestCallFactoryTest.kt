package com.huanchengfly.tieba.post.api.retrofit

import com.huanchengfly.tieba.post.api.retrofit.adapter.DeferredCallAdapterFactory
import com.huanchengfly.tieba.post.api.retrofit.adapter.FlowCallAdapterFactory
import com.huanchengfly.tieba.post.api.retrofit.interceptors.CredentialTransportInterceptor
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Call
import okhttp3.Connection
import okhttp3.Dispatcher
import okhttp3.EventListener
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import retrofit2.Callback
import retrofit2.Invocation
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.IOException
import java.io.InputStream
import java.io.InterruptedIOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Collections
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/** Uses the production factory, real Retrofit Invocation tags and real loopback HTTP I/O. */
class ReadOnlyRequestCallFactoryTest {
    interface TestApi {
        @BudgetedReadRequest
        @GET("read")
        fun read(): retrofit2.Call<ResponseBody>

        @BudgetedReadRequest
        @POST("read")
        fun readPost(@Body body: RequestBody): retrofit2.Call<ResponseBody>

        @GET("read")
        fun unmarkedRead(): retrofit2.Call<ResponseBody>

        @POST("write")
        fun write(@Body body: RequestBody): retrofit2.Call<ResponseBody>

        @POST("upload")
        fun upload(@Body body: RequestBody): retrofit2.Call<ResponseBody>

        @BudgetedReadRequest
        @GET("read")
        fun readFlow(): Flow<ResponseBody>

        @GET("upload")
        fun unmarkedFlow(): Flow<ResponseBody>

        @BudgetedReadRequest
        @GET("read")
        fun readDeferred(): Deferred<ApiResult<ResponseBody>>

        @GET("upload")
        fun unmarkedDeferred(): Deferred<ApiResult<ResponseBody>>
    }

    private fun baseClient() = OkHttpClient.Builder()
        .followRedirects(false)
        .followSslRedirects(false)
        .readTimeout(5, TimeUnit.SECONDS)
        .connectTimeout(5, TimeUnit.SECONDS)
        .writeTimeout(5, TimeUnit.SECONDS)
        .build()

    private fun api(baseUrl: String, factory: Call.Factory): TestApi = Retrofit.Builder()
        .baseUrl(baseUrl)
        .callFactory(factory)
        .addCallAdapterFactory(DeferredCallAdapterFactory())
        .addCallAdapterFactory(FlowCallAdapterFactory.create())
        .build()
        .create(TestApi::class.java)

    private fun budget(base: OkHttpClient, millis: Long) =
        ReadOnlyRequestCallFactory(base, millis, TimeUnit.MILLISECONDS)

    private fun closeClient(client: OkHttpClient) {
        client.dispatcher.cancelAll()
        client.dispatcher.executorService.shutdownNow()
        client.connectionPool.evictAll()
    }

    @Test fun defaultBudgetComesFromRealInvocationAndBothKindsOfCloneRetainIt() {
        val base = baseClient()
        try {
            val factory = ReadOnlyRequestCallFactory(base)
            val service = api("http://127.0.0.1/", factory)
            val original = service.read()
            val request = original.request()
            val invocation = request.tag(Invocation::class.java)!!
            assertEquals(TestApi::class.java.getMethod("read"), invocation.method())
            assertTrue(invocation.method().isAnnotationPresent(BudgetedReadRequest::class.java))
            for (call in listOf(original, original.clone(), original.clone().clone())) {
                assertEquals(TimeUnit.SECONDS.toNanos(60), call.timeout().timeoutNanos())
                assertEquals(invocation.method(), call.request().tag(Invocation::class.java)!!.method())
            }
            val raw = factory.newCall(request)
            assertEquals(TimeUnit.SECONDS.toNanos(60), raw.timeout().timeoutNanos())
            assertEquals(TimeUnit.SECONDS.toNanos(60), raw.clone().timeout().timeoutNanos())
            assertSame(request, raw.clone().request())
            assertEquals(0, base.callTimeoutMillis)
        } finally {
            closeClient(base)
        }
    }

    @Test fun unmarkedGetWriteUploadAndMissingInvocationKeepOriginalClientBudget() {
        val base = baseClient().newBuilder().callTimeout(7, TimeUnit.SECONDS).build()
        try {
            val factory = budget(base, 100)
            val service = api("http://127.0.0.1/", factory)
            val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("data", "fixture").build()
            for (call in listOf(service.unmarkedRead(), service.write("fixture".toRequestBody()), service.upload(multipart))) {
                assertFalse(call.request().tag(Invocation::class.java)!!.method()
                    .isAnnotationPresent(BudgetedReadRequest::class.java))
                assertEquals(TimeUnit.SECONDS.toNanos(7), call.timeout().timeoutNanos())
                assertEquals(TimeUnit.SECONDS.toNanos(7), call.clone().timeout().timeoutNanos())
            }
            // An otherwise identical path is not sufficient to opt in without the annotation.
            val noInvocation = Request.Builder().url("http://127.0.0.1/read").build()
            assertNull(noInvocation.tag(Invocation::class.java))
            assertEquals(TimeUnit.SECONDS.toNanos(7), factory.newCall(noInvocation).timeout().timeoutNanos())
            // A protobuf-style multipart read remains opted in because its method is audited.
            assertEquals(TimeUnit.MILLISECONDS.toNanos(100), service.readPost(multipart).timeout().timeoutNanos())
        } finally {
            closeClient(base)
        }
    }

    @Test fun normalReadAndRetrofitCloneSucceedWithoutAnyExtraRequest() {
        HttpFixture { socket, _ -> respond(socket, "ok") }.use { server ->
            val base = baseClient()
            try {
                val service = api(server.baseUrl, budget(base, 2_000))
                val original = service.read()
                assertEquals("ok", original.execute().body()!!.use { it.string() })
                assertEquals("ok", original.clone().execute().body()!!.use { it.string() })
                assertEquals(2, server.requestCount.get())
            } finally {
                closeClient(base)
            }
        }
    }

    @Test fun stalledHeadersHitCallBudgetBeforeReadTimeoutWithoutRetry() {
        val release = CountDownLatch(1)
        HttpFixture { _, _ -> release.await(5, TimeUnit.SECONDS) }.use { server ->
            val base = baseClient()
            try {
                val service = api(server.baseUrl, budget(base, 300))
                val call = service.read()
                val probe = Probe().also(call::enqueue)
                server.awaitRequest()
                probe.await()
                assertNull(probe.response)
                assertTrue(probe.failure is InterruptedIOException)
                assertTrue(call.isCanceled)
                assertEquals(1, server.requestCount.get())
            } finally {
                release.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun progressingSlowBodyStillHitsWholeCallBudgetWithoutRetry() {
        val chunks = AtomicInteger()
        val scheduler = Executors.newSingleThreadScheduledExecutor()
        HttpFixture { socket, _ ->
            val output = socket.getOutputStream()
            output.write("HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n".toByteArray())
            output.flush()
            val finished = CountDownLatch(1)
            val writer = scheduler.scheduleAtFixedRate({
                try {
                    output.write('x'.code)
                    output.flush()
                    chunks.incrementAndGet()
                } catch (_: IOException) {
                    finished.countDown()
                }
            }, 0, 40, TimeUnit.MILLISECONDS)
            try {
                finished.await(5, TimeUnit.SECONDS)
            } finally {
                writer.cancel(true)
            }
        }.use { server ->
            val base = baseClient()
            try {
                val call = api(server.baseUrl, budget(base, 800)).read()
                val probe = Probe().also(call::enqueue)
                server.awaitRequest()
                probe.await()
                assertNull(probe.response)
                assertTrue(probe.failure is InterruptedIOException)
                assertTrue("The socket must have delivered progressing data", chunks.get() > 1)
                assertTrue(call.isCanceled)
                assertEquals(1, server.requestCount.get())
            } finally {
                closeClient(base)
                scheduler.shutdownNow()
            }
        }
    }

    @Test fun cancelStopsInFlightReadAndDoesNotWaitForItsBudget() {
        val release = CountDownLatch(1)
        HttpFixture { _, _ -> release.await(5, TimeUnit.SECONDS) }.use { server ->
            val base = baseClient()
            try {
                val call = api(server.baseUrl, budget(base, 5_000)).read()
                val probe = Probe().also(call::enqueue)
                server.awaitRequest()
                call.cancel()
                assertTrue("Cancellation must report before the five-second budget", probe.done.await(2, TimeUnit.SECONDS))
                assertTrue(probe.failure is IOException)
                assertNull(probe.response)
                assertTrue(call.isCanceled)
                assertEquals(1, server.requestCount.get())
                assertFalse(call.clone().isCanceled)
            } finally {
                release.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun unmarkedUploadCanCompleteAfterTheReadBudget() {
        val release = CountDownLatch(1)
        HttpFixture { socket, _ ->
            release.await(5, TimeUnit.SECONDS)
            respond(socket, "uploaded")
        }.use { server ->
            val base = baseClient()
            try {
                val call = api(server.baseUrl, budget(base, 100)).upload("fixture".toRequestBody())
                val probe = Probe().also(call::enqueue)
                server.awaitRequest()
                assertFalse(probe.done.await(350, TimeUnit.MILLISECONDS))
                assertFalse(call.isCanceled)
                release.countDown()
                probe.await()
                assertNull(probe.failure)
                assertEquals("uploaded", probe.response!!.body()!!.use { it.string() })
                assertEquals(1, server.requestCount.get())
            } finally {
                release.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun dispatcherQueueIsSharedAndIsOutsideTheReadExecutionBudget() {
        val releaseFirst = CountDownLatch(1)
        HttpFixture { socket, request ->
            if (request.path == "/upload") releaseFirst.await(5, TimeUnit.SECONDS)
            respond(socket, request.path)
        }.use { server ->
            val dispatcher = Dispatcher().apply { maxRequests = 1; maxRequestsPerHost = 1 }
            val base = baseClient().newBuilder().dispatcher(dispatcher).build()
            try {
                val service = api(server.baseUrl, budget(base, 200))
                val first = Probe().also(service.upload("fixture".toRequestBody())::enqueue)
                server.awaitRequest()
                val read = service.read()
                val second = Probe().also(read::enqueue)
                assertEquals(1, dispatcher.queuedCallsCount())
                assertFalse(second.done.await(600, TimeUnit.MILLISECONDS))
                assertFalse(read.isCanceled)
                assertEquals(1, server.requestCount.get())
                releaseFirst.countDown()
                first.await()
                second.await()
                assertNull(first.failure)
                assertNull(second.failure)
                assertEquals("/read", second.response!!.body()!!.use { it.string() })
                first.response!!.body()!!.close()
                assertEquals(2, server.requestCount.get())
            } finally {
                releaseFirst.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun derivedClientKeepsInterceptorsEventListenerAndSharedConnectionPool() {
        val connections = Collections.synchronizedList(mutableListOf<Connection>())
        val order = Collections.synchronizedList(mutableListOf<String>())
        HttpFixture { socket, _ -> respond(socket, "ok", keepAlive = true) }.use { server ->
            val base = baseClient().newBuilder()
                .eventListener(object : EventListener() {
                    override fun connectionAcquired(call: Call, connection: Connection) { connections.add(connection) }
                })
                .addInterceptor { chain ->
                    order.add("application")
                    chain.proceed(chain.request().newBuilder().header("X-Application", "retained").build())
                }
                .addNetworkInterceptor { chain ->
                    order.add("network")
                    chain.proceed(chain.request().newBuilder().header("X-Network", "retained").build())
                }
                .build()
            try {
                val service = api(server.baseUrl, budget(base, 2_000))
                service.read().execute().body()!!.close()
                service.unmarkedRead().execute().body()!!.close()
                val first = server.awaitRequest()
                val second = server.awaitRequest()
                for (request in listOf(first, second)) {
                    assertEquals("retained", request.headers["x-application"])
                    assertEquals("retained", request.headers["x-network"])
                }
                assertEquals(listOf("application", "network", "application", "network"), order)
                assertEquals(2, connections.size)
                assertSame("Read and original clients should reuse the same pooled connection", connections[0], connections[1])
            } finally {
                closeClient(base)
            }
        }
    }

    @Test fun derivedClientKeepsRedirectsDisabled() {
        HttpFixture { socket, _ ->
            socket.getOutputStream().apply {
                write("HTTP/1.1 302 Found\r\nLocation: /redirected\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
                flush()
            }
        }.use { server ->
            val base = baseClient()
            try {
                val response = api(server.baseUrl, budget(base, 2_000)).read().execute()
                assertEquals(302, response.code())
                response.errorBody()?.close()
                assertEquals(1, server.requestCount.get())
            } finally {
                closeClient(base)
            }
        }
    }

    @Test fun derivedClientKeepsCredentialGuardAheadOfOtherInterceptors() {
        var credentialsReached = false
        val base = baseClient().newBuilder()
            .addInterceptor(CredentialTransportInterceptor("https://tiebac.baidu.com/"))
            .addInterceptor { chain ->
                credentialsReached = true
                okhttp3.Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("fixture").body("ok".toResponseBody()).build()
            }.build()
        try {
            val service = api("https://untrusted.example/", ReadOnlyRequestCallFactory(base))
            assertThrows(IOException::class.java) { service.read().execute() }
            assertThrows(IOException::class.java) { service.unmarkedRead().execute() }
            assertFalse(credentialsReached)
        } finally {
            closeClient(base)
        }
    }

    @Test fun productionFlowAndDeferredAdaptersCompleteNormally() = runBlocking {
        HttpFixture { socket, _ -> respond(socket, "ok") }.use { server ->
            val base = baseClient()
            try {
                val service = api(server.baseUrl, budget(base, 2_000))
                assertEquals("ok", withTimeout(4_000) { service.readFlow().first() }.use { it.string() })
                val result = withTimeout(4_000) { service.readDeferred().await() }
                assertTrue(result is ApiResult.Success)
                assertEquals("ok", (result as ApiResult.Success).data.use { it.string() })
                assertEquals(2, server.requestCount.get())
            } finally {
                closeClient(base)
            }
        }
    }

    @Test fun productionFlowAndDeferredAdaptersPreserveTimeoutFailures() = runBlocking {
        val release = CountDownLatch(1)
        HttpFixture { _, _ -> release.await(5, TimeUnit.SECONDS) }.use { server ->
            val base = baseClient()
            try {
                val service = api(server.baseUrl, budget(base, 300))
                val failure = try {
                    withTimeout(4_000) { service.readFlow().first() }
                    null
                } catch (error: IOException) {
                    error
                }
                assertTrue(failure is InterruptedIOException)
                val result = withTimeout(4_000) { service.readDeferred().await() }
                assertTrue(result is ApiResult.Failure)
                assertTrue((result as ApiResult.Failure).error is InterruptedIOException)
                assertEquals(2, server.requestCount.get())
            } finally {
                release.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun unmarkedProductionFlowAndDeferredKeepTheirOriginalBudget() = runBlocking {
        val release = CountDownLatch(1)
        HttpFixture { socket, _ ->
            release.await(5, TimeUnit.SECONDS)
            respond(socket, "ok")
        }.use { server ->
            val base = baseClient()
            try {
                val service = api(server.baseUrl, budget(base, 100))
                val flow = async(Dispatchers.Default) { service.unmarkedFlow().first() }
                val deferred = service.unmarkedDeferred()
                server.awaitRequest()
                server.awaitRequest()
                val done = CountDownLatch(2)
                flow.invokeOnCompletion { done.countDown() }
                deferred.invokeOnCompletion { done.countDown() }
                assertFalse(done.await(350, TimeUnit.MILLISECONDS))
                assertFalse(flow.isCompleted)
                assertFalse(deferred.isCompleted)
                release.countDown()
                assertEquals("ok", withTimeout(4_000) { flow.await() }.use { it.string() })
                val result = withTimeout(4_000) { deferred.await() }
                assertTrue(result is ApiResult.Success)
                assertEquals("ok", (result as ApiResult.Success).data.use { it.string() })
                assertEquals(2, server.requestCount.get())
            } finally {
                release.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun productionFlowAndDeferredCancellationCancelsUnderlyingCalls() = runBlocking {
        val release = CountDownLatch(1)
        val canceled = LinkedBlockingQueue<Call>()
        HttpFixture { _, _ -> release.await(5, TimeUnit.SECONDS) }.use { server ->
            val base = baseClient().newBuilder().eventListener(object : EventListener() {
                override fun canceled(call: Call) { canceled.add(call) }
            }).build()
            try {
                val service = api(server.baseUrl, budget(base, 5_000))
                val flow = async(Dispatchers.Default) { service.readFlow().first() }
                server.awaitRequest()
                flow.cancelAndJoin()
                assertTrue(canceled.poll(2, TimeUnit.SECONDS)!!.isCanceled())
                val deferred = service.readDeferred()
                server.awaitRequest()
                deferred.cancelAndJoin()
                assertTrue(canceled.poll(2, TimeUnit.SECONDS)!!.isCanceled())
                assertEquals(2, server.requestCount.get())
            } finally {
                release.countDown()
                closeClient(base)
            }
        }
    }

    @Test fun readBudgetCannotBeDisabledByPassingZero() {
        val base = baseClient()
        try {
            assertThrows(IllegalArgumentException::class.java) { budget(base, 0) }
        } finally {
            closeClient(base)
        }
    }

    private class Probe : Callback<ResponseBody> {
        val done = CountDownLatch(1)
        @Volatile var response: retrofit2.Response<ResponseBody>? = null
        @Volatile var failure: Throwable? = null
        override fun onResponse(call: retrofit2.Call<ResponseBody>, response: retrofit2.Response<ResponseBody>) {
            this.response = response
            done.countDown()
        }
        override fun onFailure(call: retrofit2.Call<ResponseBody>, t: Throwable) {
            failure = t
            done.countDown()
        }
        fun await() { assertTrue("HTTP callback did not finish", done.await(4, TimeUnit.SECONDS)) }
    }

    private data class ReceivedRequest(val path: String, val headers: Map<String, String>)

    /** Small JDK fixture keeps this regression independent of an added MockWebServer dependency. */
    private class HttpFixture(private val handler: (Socket, ReceivedRequest) -> Unit) : Closeable {
        private val listener = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
        private val workers = Executors.newCachedThreadPool()
        private val sockets = Collections.synchronizedList(mutableListOf<Socket>())
        private val received = LinkedBlockingQueue<ReceivedRequest>()
        val requestCount = AtomicInteger()
        val baseUrl = "http://127.0.0.1:${listener.localPort}/"
        @Volatile private var closed = false
        private val acceptor = thread(isDaemon = true, name = "read-budget-http-fixture") {
            while (!closed) {
                val socket = try { listener.accept() } catch (_: IOException) { break }
                sockets.add(socket)
                workers.execute {
                    socket.use {
                        socket.soTimeout = 5_000
                        try {
                            val input = socket.getInputStream()
                            while (!closed) {
                                val start = readLine(input) ?: break
                                val headers = linkedMapOf<String, String>()
                                while (true) {
                                    val line = readLine(input) ?: return@execute
                                    if (line.isEmpty()) break
                                    headers[line.substringBefore(':').lowercase()] = line.substringAfter(':').trim()
                                }
                                repeat(headers["content-length"]?.toInt() ?: 0) {
                                    if (input.read() == -1) throw IOException("Incomplete fixture request")
                                }
                                val request = ReceivedRequest(start.split(' ')[1], headers)
                                requestCount.incrementAndGet()
                                received.add(request)
                                handler(socket, request)
                            }
                        } catch (_: IOException) {
                            // Expected for timeout, cancellation and closing the fixture.
                        } catch (_: InterruptedException) {
                            Thread.currentThread().interrupt()
                        }
                    }
                    sockets.remove(socket)
                }
            }
        }

        fun awaitRequest(): ReceivedRequest = received.poll(3, TimeUnit.SECONDS)
            ?: throw AssertionError("Loopback server received no request")

        override fun close() {
            closed = true
            listener.close()
            acceptor.join(2_000)
            synchronized(sockets) { sockets.forEach { it.close() } }
            workers.shutdownNow()
            assertTrue("Fixture workers leaked", workers.awaitTermination(2, TimeUnit.SECONDS))
        }

        private fun readLine(input: InputStream): String? {
            val bytes = ByteArrayOutputStream()
            while (true) {
                val next = input.read()
                if (next == -1) return if (bytes.size() == 0) null else bytes.toString("US-ASCII")
                if (next == '\n'.code) return bytes.toString("US-ASCII").removeSuffix("\r")
                bytes.write(next)
            }
        }
    }

    companion object {
        private fun respond(socket: Socket, body: String, keepAlive: Boolean = false) {
            val bytes = body.toByteArray()
            socket.getOutputStream().apply {
                write(("HTTP/1.1 200 OK\r\nContent-Length: ${bytes.size}\r\nConnection: " +
                    (if (keepAlive) "keep-alive" else "close") + "\r\n\r\n").toByteArray())
                write(bytes)
                flush()
            }
            if (!keepAlive) socket.shutdownOutput()
        }
    }
}
