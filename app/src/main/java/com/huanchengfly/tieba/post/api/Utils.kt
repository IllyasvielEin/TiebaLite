package com.huanchengfly.tieba.post.api

import com.huanchengfly.tieba.post.App
import com.huanchengfly.tieba.post.App.ScreenInfo
import java.io.IOException


private val defaultUserAgent: String =
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/135.0.0.0 Mobile Safari/537.36"

fun getUserAgent(appendString: String? = null): String {
    val append = " ${appendString?.trim()}".takeIf { !appendString.isNullOrEmpty() }.orEmpty()
    return "${App.Config.userAgent ?: defaultUserAgent}$append"
}

@Throws(IOException::class)
fun getCookie(vararg cookies: Pair<String, () -> String?>): String {
    return cookies.mapNotNull { (name, supplier) -> CookieHeaderBuilder.pair(name, supplier()) }
        .joinToString("; ")
}

fun getScreenHeight(): Int = ScreenInfo.EXACT_SCREEN_HEIGHT

fun getScreenWidth(): Int = ScreenInfo.EXACT_SCREEN_WIDTH

fun Boolean.booleanToString(): String = if (this) "1" else "0"
