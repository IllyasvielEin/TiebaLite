package com.huanchengfly.tieba.post.api.retrofit.interceptors

import com.huanchengfly.tieba.post.api.models.CommonResponse
import com.huanchengfly.tieba.post.api.models.protos.ProtoCommonResponse
import com.huanchengfly.tieba.post.api.models.protos.addPollPost.AddPollPostReponse
import com.huanchengfly.tieba.post.api.models.protos.getBawuInfo.GetBawuInfoResponse
import com.huanchengfly.tieba.post.api.models.protos.getLevelInfo.GetLevelInfoResponse
import com.huanchengfly.tieba.post.api.models.protos.getMemberInfo.GetMemberInfoResponse
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaApiException
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException

object ProtoFailureResponseInterceptor : Interceptor {
    // Applies to the decompressed protobuf body, not its compressed Content-Length.
    // This is a defensive application limit, not a measured Tieba response maximum.
    internal const val MAX_PROTOBUF_RESPONSE_BYTES = 8L * 1024 * 1024

    override fun intercept(chain: Interceptor.Chain): Response {
        val response = chain.proceed(chain.request())
        return response.withBoundedBody(MAX_PROTOBUF_RESPONSE_BYTES, "Protobuf") { _, source ->
            val error = try {
                // The bounded peek leaves the original bytes available to Retrofit.
                source.peek().use { peek ->
                    // These four API contracts put data in field 1 and error in
                    // field 2. Treating field 1 as Error rejects valid responses.
                    when (response.request.url.encodedPath) {
                        "/c/f/forum/getBawuInfo" -> GetBawuInfoResponse.ADAPTER.decode(peek).error
                        "/c/f/forum/getLevelInfo" -> GetLevelInfoResponse.ADAPTER.decode(peek).error
                        "/c/f/forum/getMemberInfo" -> GetMemberInfoResponse.ADAPTER.decode(peek).error
                        "/c/c/post/addPollPost" -> AddPollPostReponse.ADAPTER.decode(peek).error
                        else -> ProtoCommonResponse.ADAPTER.decode(peek).error
                    }
                }
            } catch (exception: Exception) {
                // OkHttp delivers IOExceptions to asynchronous onFailure callbacks.
                // Never let an unchecked parser exception escape that boundary.
                throw IOException("Malformed protobuf response", exception)
            }

            if (error != null && error.error_code != 0) {
                throw TiebaApiException(CommonResponse(error.error_code, error.error_msg))
            }
        }
    }
}
