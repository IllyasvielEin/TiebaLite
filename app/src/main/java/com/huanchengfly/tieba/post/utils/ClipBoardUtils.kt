package com.huanchengfly.tieba.post.utils

import android.content.ClipboardManager
import android.content.Context

val Context.clipBoardManager
    get() = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager

fun Context.getClipBoardHtmlText(): String? {
    val data = clipBoardManager.primaryClip ?: return null
    val item = data.getItemAt(0)
    return item?.coerceToHtmlText(this)
}

fun Context.getClipBoardText(): String? {
    val data = clipBoardManager.primaryClip ?: return null
    val item = data.getItemAt(0)
    return item?.text?.toString()
}

fun Context.getClipBoardTimestamp(): Long {
    val clipDescription = clipBoardManager.primaryClipDescription ?: return 0
    return clipDescription.timestamp
}