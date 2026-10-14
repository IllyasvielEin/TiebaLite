package com.huanchengfly.tieba.post.api.retrofit.exception

import com.huanchengfly.tieba.post.api.models.CommonResponse

class TiebaApiException(
    private val commonResponse: CommonResponse
) : TiebaException(commonResponse.errorMessageOrDefault()) {
    override val code: Int
        get() = commonResponse.errorCode

    override fun toString(): String {
        return "TiebaApiException(code=$code, message=$message, commonResponse=$commonResponse)"
    }
}

private fun CommonResponse.errorMessageOrDefault(): String {
    // Gson may assign null or leave this field null despite its Kotlin type,
    // including when ErrorMsgAdapter receives a null/array-shaped message.
    val message: String? = errorMsg
    return message?.takeIf { it.isNotEmpty() } ?: "未知错误"
}
