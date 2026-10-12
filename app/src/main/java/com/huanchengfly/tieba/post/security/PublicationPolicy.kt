package com.huanchengfly.tieba.post.security

/** Learning builds cannot create threads, replies, or upload publication media.
 * This is a source-level capability, never a user preference or remote flag.
 */
object PublicationPolicy {
    @JvmField
    val enabled: Boolean = false

    const val DISABLED_MESSAGE = "此学习版本已关闭发帖、回复和图片上传。"

    fun requireEnabled() {
        check(enabled) { DISABLED_MESSAGE }
    }
}
