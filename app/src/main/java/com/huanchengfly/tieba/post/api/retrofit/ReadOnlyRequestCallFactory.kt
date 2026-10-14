package com.huanchengfly.tieba.post.api.retrofit

import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import retrofit2.Invocation
import java.util.concurrent.TimeUnit

/**
 * Selects a whole-call execution budget only for explicitly audited read methods.
 *
 * Derive the client before creating the call: setting Call.timeout() in an interceptor is
 * too late for execution already in progress and is not retained by a raw Call.clone().
 * newBuilder() preserves the original transport restrictions, interceptors, dispatcher
 * and connection pool. Unmarked requests use the original client unchanged.
 *
 * OkHttp's asynchronous dispatcher queue is outside this budget. This is not a
 * wall-clock deadline for an entire page, coroutine or arbitrary interceptor work.
 */
internal class ReadOnlyRequestCallFactory(
    private val client: OkHttpClient,
    timeout: Long = 60L,
    unit: TimeUnit = TimeUnit.SECONDS,
) : Call.Factory {
    init {
        require(timeout > 0L) { "The read request budget must be positive" }
    }

    private val readOnlyClient = client.newBuilder()
        .callTimeout(timeout, unit)
        .build()

    override fun newCall(request: Request): Call {
        val method = request.tag(Invocation::class.java)?.method()
        val selectedClient = if (method?.isAnnotationPresent(BudgetedReadRequest::class.java) == true) {
            readOnlyClient
        } else {
            client
        }
        return selectedClient.newCall(request)
    }
}
