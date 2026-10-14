package com.huanchengfly.tieba.post.repository

import com.huanchengfly.tieba.post.App
import com.huanchengfly.tieba.post.api.TiebaApi
import com.huanchengfly.tieba.post.api.models.protos.GeneralTabList.GeneralTabListResponse
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaUnknownException
import com.huanchengfly.tieba.post.utils.appPreferences
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

object GeneralTabListRepository {
    data class PageResult(val response: GeneralTabListResponse, val rawLastThreadId: Long)

    @Suppress("UNUSED_PARAMETER") // Compatibility only; no process-global response cache.
    fun generalTabList(
        forumId: Long,
        forumName: String,
        tabId: Int,
        tabType: Int,
        tabName: String,
        isGeneralTab: Int,
        pn: Int = 1,
        sortType: Int = -1,
        lastThreadId: Long = 0,
        isDefaultNavTab: Int = 0,
        forceNew: Boolean = false,
    ): Flow<GeneralTabListResponse> {
        return generalTabListResult(
            forumId, forumName, tabId, tabType, tabName, isGeneralTab,
            pn, sortType, lastThreadId, isDefaultNavTab
        ).map { it.response }
    }

    fun generalTabListResult(
        forumId: Long,
        forumName: String,
        tabId: Int,
        tabType: Int,
        tabName: String,
        isGeneralTab: Int,
        pn: Int = 1,
        sortType: Int = -1,
        lastThreadId: Long = 0,
        isDefaultNavTab: Int = 0,
    ): Flow<PageResult> {
        return TiebaApi.getInstance().generalTabList(
            forumId, forumName, tabId, tabType, tabName, isGeneralTab,
            pn, sortType, lastThreadId, isDefaultNavTab
        ).map { preparePage(it, App.INSTANCE.appPreferences.blockVideo) }
    }

    internal fun preparePage(response: GeneralTabListResponse, blockVideo: Boolean): PageResult {
        val data = response.data_ ?: throw TiebaUnknownException
        val threads = data.general_list
            .map { it.copy(author = data.user_list.find { user -> user.id == it.authorId }) }
            .filter { !blockVideo || it.videoInfo == null }
            .filter { it.ala_info == null }
        return PageResult(
            response.copy(data_ = data.copy(general_list = threads)),
            data.general_list.lastOrNull()?.id ?: 0,
        )
    }
}
