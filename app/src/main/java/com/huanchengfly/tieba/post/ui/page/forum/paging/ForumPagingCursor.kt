package com.huanchengfly.tieba.post.ui.page.forum.paging

internal data class ForumListQuery(
    val forumId: Long,
    val forumName: String,
    val isGood: Boolean,
    val sortType: Int = -1,
    val goodClassifyId: Int? = null,
) {
    val requestSort: Int get() = if (isGood) -1 else sortType
    val requestBatchSort: Int get() = if (isGood) 0 else sortType
    val requestClassify: Int? get() = if (isGood) goodClassifyId ?: 0 else null
}

internal data class ForumPagingCursor(
    val page: Int = 0,
    val remainingIds: List<Long> = emptyList(),
    val serverHasMore: Boolean = true,
    val rawThreadIds: List<Long> = emptyList(),
) {
    val hasMore: Boolean get() = remainingIds.isNotEmpty() || serverHasMore
    val batch: List<Long> get() = remainingIds.take(30)

    /** Called only after a successful ID response, which has no has_more field of its own. */
    fun consumeBatch(): ForumPagingCursor = copy(remainingIds = remainingIds.drop(batch.size))

    fun nextPage(
        rawIds: List<Long>,
        ids: List<Long>,
        hasMore: Boolean,
    ): ForumPagingCursor = ForumPagingCursor(page + 1, ids, hasMore, rawIds)

    fun progressedTo(next: ForumPagingCursor): Boolean = if (remainingIds.isNotEmpty()) {
        next.remainingIds.size < remainingIds.size
    } else {
        val nextRaw = next.rawThreadIds + next.remainingIds
        nextRaw.isNotEmpty() && nextRaw != rawThreadIds + remainingIds
    }
}

internal data class GeneralListQuery(
    val forumId: Long,
    val forumName: String,
    val tabId: Int,
    val tabType: Int,
    val tabName: String,
    val isGeneralTab: Int,
    val isDefaultNavTab: Int,
    val sortType: Int,
)

internal data class GeneralPagingCursor(val page: Int = 0, val lastThreadId: Long = 0) {
    fun nextPage(rawLastThreadId: Long): GeneralPagingCursor = copy(page = page + 1, lastThreadId = rawLastThreadId)
    fun progressedTo(next: GeneralPagingCursor): Boolean = next.lastThreadId != 0L && next.lastThreadId != lastThreadId
}
