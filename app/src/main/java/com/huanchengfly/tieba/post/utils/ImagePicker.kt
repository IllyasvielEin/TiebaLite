package com.huanchengfly.tieba.post.utils

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts.PickMultipleVisualMedia
import androidx.activity.result.contract.ActivityResultContracts.PickVisualMedia
import androidx.appcompat.app.AppCompatActivity

/**
 * Adapter for the retained global multi-media request API. Active avatar/background
 * screens register their own PickVisualMedia launcher directly. AndroidX handles
 * the system picker and the ACTION_OPEN_DOCUMENT fallback on API 19+, without
 * requesting access to the whole media library.
 */
fun AppCompatActivity.registerPickMediasLauncher(callback: (PickMediasResult) -> Unit): ActivityResultLauncher<PickMediasRequest> {
    return registerForActivityResult(PickMediasContract()) { callback(it) }
}

fun Uri.isPickerContentUri(): Boolean = PickerUriPolicy.isAllowed(scheme, authority)

fun Intent.getClipDataUris(): List<Uri> {
    val resultSet = LinkedHashSet<Uri>()
    data?.let(resultSet::add)
    clipData?.let { clip ->
        for (i in 0 until clip.itemCount) {
            clip.getItemAt(i).uri?.let(resultSet::add)
        }
    }
    return resultSet.filter(Uri::isPickerContentUri)
}

data class PickMediasRequest(
    val id: String = "",
    val maxItems: Int = 1,
    val mediaType: MediaType = ImageAndVideo
) {
    init {
        require(maxItems > 0) { "At least one media item must be selectable" }
    }

    sealed interface MediaType
    data object ImageOnly : MediaType
    data object VideoOnly : MediaType
    data object ImageAndVideo : MediaType
    data class SingleMimeType(val mimeType: String) : MediaType
}

data class PickMediasResult(
    val id: String,
    val uris: List<Uri>
)

private class PickMediasContract : ActivityResultContract<PickMediasRequest, PickMediasResult>() {
    // Scoped to this launcher, never shared between activities. A result whose
    // in-flight request was lost after process death is safely discarded.
    private var currentRequest: PickMediasRequest? = null

    override fun createIntent(context: Context, input: PickMediasRequest): Intent {
        val mediaType: PickVisualMedia.VisualMediaType = when (val type = input.mediaType) {
            PickMediasRequest.ImageOnly -> PickVisualMedia.ImageOnly
            PickMediasRequest.VideoOnly -> PickVisualMedia.VideoOnly
            PickMediasRequest.ImageAndVideo -> PickVisualMedia.ImageAndVideo
            is PickMediasRequest.SingleMimeType -> PickVisualMedia.SingleMimeType(type.mimeType)
        }
        val request = PickVisualMediaRequest(mediaType)
        val intent = if (input.maxItems == 1) {
            PickVisualMedia().createIntent(context, request)
        } else {
            PickMultipleVisualMedia(input.maxItems).createIntent(context, request)
        }
        currentRequest = input
        return intent
    }

    override fun parseResult(resultCode: Int, intent: Intent?): PickMediasResult {
        val request = currentRequest
        currentRequest = null
        if (request == null || resultCode != Activity.RESULT_OK || intent == null) {
            return PickMediasResult(request?.id.orEmpty(), emptyList())
        }
        // ACTION_OPEN_DOCUMENT may ignore the requested selection maximum.
        return PickMediasResult(request.id, intent.getClipDataUris().take(request.maxItems))
    }
}
