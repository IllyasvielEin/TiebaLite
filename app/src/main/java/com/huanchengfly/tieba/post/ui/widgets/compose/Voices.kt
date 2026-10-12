package com.huanchengfly.tieba.post.ui.widgets.compose

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import com.huanchengfly.tieba.post.ui.widgets.VoicePlayerView

@Composable
fun VoicePlayer(
    url: String,
    duration: Int,
    modifier: Modifier = Modifier
) {
    AndroidView(
        modifier = modifier,
        factory = {
            VoicePlayerView(it)
        },
        update = {
            if (it.url != url) it.reset()
            it.url = url
            it.duration = duration
        },
        onReset = null,
        onRelease = { it.release() }
    )
}