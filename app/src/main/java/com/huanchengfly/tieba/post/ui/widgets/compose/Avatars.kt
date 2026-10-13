package com.huanchengfly.tieba.post.ui.widgets.compose

import android.graphics.drawable.Drawable
import androidx.annotation.DrawableRes
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.Icon
import androidx.compose.material.LocalContentAlpha
import androidx.compose.material.LocalContentColor
import androidx.compose.material.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.github.panpf.sketch.compose.AsyncImage
import com.github.panpf.sketch.compose.AsyncImageState
import com.github.panpf.sketch.compose.rememberAsyncImageState
import com.github.panpf.sketch.datasource.DataFrom
import com.github.panpf.sketch.fetch.newResourceUri
import com.github.panpf.sketch.request.DisplayRequest
import com.github.panpf.sketch.request.LoadState
import com.google.accompanist.drawablepainter.rememberDrawablePainter
import com.eygraber.compose.placeholder.PlaceholderHighlight
import com.eygraber.compose.placeholder.material.fade
import com.eygraber.compose.placeholder.material.placeholder
import com.huanchengfly.tieba.post.utils.ImageUtil
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Stage
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.Category
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticObserver
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnostics
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.combine

object Sizes {
    val Tiny = 24.dp
    val Small = 36.dp
    val Medium = 48.dp
    val Large = 56.dp
}

@Composable
fun AvatarIcon(
    icon: ImageVector,
    size: Dp,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    iconSize: Dp = 24.dp,
    color: Color = LocalContentColor.current.copy(alpha = LocalContentAlpha.current),
    backgroundColor: Color = Color.Transparent,
    shape: Shape = CircleShape,
) {
    Icon(
        imageVector = icon,
        contentDescription = contentDescription,
        tint = color,
        modifier = modifier
            .size(size)
            .clip(shape)
            .background(color = backgroundColor)
            .padding((size - iconSize) / 2),
    )
}

@Composable
fun AvatarIcon(
    @DrawableRes
    resId: Int,
    size: Dp,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    iconSize: Dp = 24.dp,
    color: Color = LocalContentColor.current.copy(alpha = LocalContentAlpha.current),
    backgroundColor: Color = Color.Transparent,
    shape: Shape = CircleShape,
) {
    Icon(
        imageVector = ImageVector.vectorResource(id = resId),
        contentDescription = contentDescription,
        tint = color,
        modifier = modifier
            .size(size)
            .clip(shape)
            .background(color = backgroundColor)
            .padding((size - iconSize) / 2),
    )
}

@Composable
fun AvatarPlaceholder(
    size: Dp,
    modifier: Modifier = Modifier,
) {
    Avatar(
        data = ImageUtil.getPlaceHolder(LocalContext.current, 0),
        size = size,
        contentDescription = null,
        modifier = modifier.placeholder(
            visible = true,
            color = MaterialTheme.colors.surface,
            highlight = PlaceholderHighlight.fade(),
            shape = CircleShape
        )
    )
}

@Composable
fun Avatar(
    data: String?,
    size: Dp,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    shape: Shape = CircleShape,
    diagnosticInputKind: AvatarDiagnosticStore.InputKind? = null,
) {
    Avatar(
        data = data,
        contentDescription = contentDescription,
        modifier = modifier.size(size),
        shape = shape,
        diagnosticInputKind = diagnosticInputKind,
    )
}

@Composable
fun Avatar(
    data: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    shape: Shape = CircleShape,
    diagnosticInputKind: AvatarDiagnosticStore.InputKind? = null,
) {
    val context = LocalContext.current
    val state = rememberAsyncImageState()
    val inputKind = diagnosticInputKind ?: AvatarDiagnosticStore.classifyInput(data)
    val host = AvatarDiagnosticStore.hostFromInput(data)
    LaunchedEffect(state, inputKind, host) {
        val observer = AvatarDiagnosticObserver(AvatarDiagnostics.store, inputKind, host)
        try {
            combine(
                AvatarDiagnostics.sessions,
                snapshotFlow { sanitizedAvatarState(state) },
            ) { session, observation -> session to observation }.collect { (session, observation) ->
                observer.observe(
                    session.enabled, session.generation, observation?.transition ?: 0,
                    observation?.stage, observation?.category ?: Category.NONE,
                )
            }
        } finally {
            observer.close()
        }
    }

    AsyncImage(
        request = DisplayRequest(context, data) {
            placeholder(ImageUtil.getPlaceHolder(context, 0))
            crossfade()
        },
        state = state,
        contentDescription = contentDescription,
        contentScale = ContentScale.Crop,
        modifier = modifier.clip(shape),
    )
}

/** Only fixed metadata crosses the observation flow; the existing image state owns its request. */
private data class AvatarStateObservation(val transition: Int, val stage: Stage, val category: Category)

private fun sanitizedAvatarState(state: AsyncImageState): AvatarStateObservation? {
    val loadState = state.loadState ?: return null
    // Ignore an old result while AsyncImage is switching to another URI.
    if (loadState.request.uriString != state.request?.uriString) return null
    val category = if (loadState is LoadState.Error) {
        AvatarDiagnosticStore.classifyFailure(loadState.result.throwable)
    } else Category.NONE
    val stage = when (loadState) {
        is LoadState.Started -> Stage.START
        is LoadState.Canceled -> Stage.CANCELLED
        is LoadState.Error -> if (category == Category.NONE) Stage.CANCELLED else Stage.ERROR
        is LoadState.Success -> when (loadState.result.dataFrom) {
            DataFrom.NETWORK -> Stage.SUCCESS_NETWORK
            DataFrom.DOWNLOAD_CACHE -> Stage.SUCCESS_DOWNLOAD_CACHE
            DataFrom.MEMORY_CACHE, DataFrom.RESULT_CACHE -> Stage.SUCCESS_MEMORY_OR_RESULT_CACHE
            else -> Stage.SUCCESS_OTHER
        }
    }
    // This ephemeral identity distinguishes repeated state objects; it is never reported or retained as user data.
    return AvatarStateObservation(System.identityHashCode(loadState), stage, category)
}

@Composable
fun Avatar(
    data: Int,
    size: Dp,
    contentDescription: String?,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current

    AsyncImage(
        request = DisplayRequest(LocalContext.current, newResourceUri(data)) {
            placeholder(ImageUtil.getPlaceHolder(context, 0))
            crossfade()
        },
        contentDescription = contentDescription,
        contentScale = ContentScale.Crop,
        modifier = modifier
            .size(size)
            .clip(CircleShape),
    )
}

@Composable
fun Avatar(
    data: Drawable,
    size: Dp,
    contentDescription: String?,
    modifier: Modifier = Modifier,
) {
    Image(
        painter = rememberDrawablePainter(drawable = data),
        contentDescription = contentDescription,
        modifier = modifier
            .size(size)
            .clip(CircleShape),
    )
}
