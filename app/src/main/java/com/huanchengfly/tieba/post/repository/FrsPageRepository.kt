package com.huanchengfly.tieba.post.repository

import com.huanchengfly.tieba.post.App
import com.huanchengfly.tieba.post.api.TiebaApi
import com.huanchengfly.tieba.post.api.models.protos.frsPage.FrsPageResponse
import com.huanchengfly.tieba.post.api.models.protos.threadList.ThreadListResponse
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaUnknownException
import com.huanchengfly.tieba.post.utils.appPreferences
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

object FrsPageRepository {
    data class PageResult(val response: FrsPageResponse, val rawThreadIds: List<Long>)

    @Suppress("UNUSED_PARAMETER") // Kept for existing callers; every collection now fetches fresh data.
    fun frsPage(
        forumName: String,
        page: Int,
        loadType: Int,
        sortType: Int,
        goodClassifyId: Int? = null,
        forceNew: Boolean = false,
    ): Flow<FrsPageResponse> {
        return frsPageResult(forumName, page, loadType, sortType, goodClassifyId).map { it.response }
    }

    fun frsPageResult(
        forumName: String,
        page: Int,
        loadType: Int,
        sortType: Int,
        goodClassifyId: Int? = null,
    ): Flow<PageResult> {
        return TiebaApi.getInstance().frsPage(forumName, page, loadType, sortType, goodClassifyId)
            .map { preparePage(it, App.INSTANCE.appPreferences.blockVideo) }
    }

    internal fun preparePage(response: FrsPageResponse, blockVideo: Boolean): PageResult {
        val data = response.data_ ?: throw TiebaUnknownException
        val threads = data.thread_list
            .map { it.copy(author = data.user_list.find { user -> user.id == it.authorId }) }
            .filter { !blockVideo || it.videoInfo == null }
            .filter { it.ala_info == null }
        return PageResult(
            response.copy(data_ = data.copy(thread_list = threads)),
            data.thread_list.map { it.id },
        )
    }

    fun threadList(
        forumId: Long,
        forumName: String,
        page: Int,
        sortType: Int,
        threadIds: String = "",
    ): Flow<ThreadListResponse> =
        TiebaApi.getInstance()
            .threadList(forumId, forumName, page, sortType, threadIds)
            .map { response ->
                if (response.data_ == null) throw TiebaUnknownException
                val userList = response.data_.user_list
                val threadList = response.data_.thread_list
                    .map { threadInfo ->
                        threadInfo.copy(author = userList.find { it.id == threadInfo.authorId })
                    }
                    .filter { !App.INSTANCE.appPreferences.blockVideo || it.videoInfo == null }
                    .filter { it.ala_info == null } // 去他妈的直播
                response.copy(data_ = response.data_.copy(thread_list = threadList))
            }
}