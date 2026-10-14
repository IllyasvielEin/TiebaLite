package com.huanchengfly.tieba.post.repository

import com.huanchengfly.tieba.post.api.models.protos.AlaLiveInfo
import com.huanchengfly.tieba.post.api.models.protos.GeneralTabList.GeneralTabListResponse
import com.huanchengfly.tieba.post.api.models.protos.GeneralTabList.GeneralTabListResponseData
import com.huanchengfly.tieba.post.api.models.protos.Page
import com.huanchengfly.tieba.post.api.models.protos.ThreadInfo
import com.huanchengfly.tieba.post.api.models.protos.User
import com.huanchengfly.tieba.post.api.models.protos.VideoInfo
import com.huanchengfly.tieba.post.api.models.protos.frsPage.FrsPageResponse
import com.huanchengfly.tieba.post.api.models.protos.frsPage.FrsPageResponseData
import org.junit.Assert.*
import org.junit.Test

class ForumPageMappingTest {
    private val plain = ThreadInfo(id = 10, authorId = 5)
    private val video = ThreadInfo(id = 20, videoInfo = VideoInfo())
    private val live = ThreadInfo(id = 30, ala_info = AlaLiveInfo())

    @Test fun generalRawTailIsTakenBeforeVideoAndLiveFiltering() {
        val result = GeneralTabListRepository.preparePage(
            GeneralTabListResponse(data_ = GeneralTabListResponseData(
                general_list = listOf(plain, video, live), has_more = 1, user_list = listOf(User(id = 5))
            )), blockVideo = true
        )
        assertEquals(30L, result.rawLastThreadId)
        assertEquals(listOf(10L), result.response.data_!!.general_list.map { it.id })
        assertEquals(5L, result.response.data_!!.general_list.single().author!!.id)
        assertEquals(1, result.response.data_!!.has_more)
    }

    @Test fun fullyFilteredGeneralPageRetainsRawCursorAndServerHasMore() {
        val result = GeneralTabListRepository.preparePage(
            GeneralTabListResponse(data_ = GeneralTabListResponseData(
                general_list = listOf(video, live), has_more = 1
            )), blockVideo = true
        )
        assertTrue(result.response.data_!!.general_list.isEmpty())
        assertEquals(30L, result.rawLastThreadId)
        assertEquals(1, result.response.data_!!.has_more)
    }

    @Test fun frsRawIdsRemainingIdsAndServerHasMoreSurviveFiltering() {
        val result = FrsPageRepository.preparePage(
            FrsPageResponse(data_ = FrsPageResponseData(
                thread_list = listOf(plain, video, live), thread_id_list = listOf(40, 50), page = Page(has_more = 1)
            )), blockVideo = true
        )
        assertEquals(listOf(10L, 20L, 30L), result.rawThreadIds)
        assertEquals(listOf(10L), result.response.data_!!.thread_list.map { it.id })
        assertEquals(listOf(40L, 50L), result.response.data_!!.thread_id_list)
        assertEquals(1, result.response.data_!!.page!!.has_more)
    }

    @Test fun videoPreferenceNeverChangesRawTailAndLiveAlwaysRemainsFiltered() {
        val raw = GeneralTabListResponse(data_ = GeneralTabListResponseData(general_list = listOf(plain, video, live)))
        val result = GeneralTabListRepository.preparePage(raw, blockVideo = false)
        assertEquals(listOf(10L, 20L), result.response.data_!!.general_list.map { it.id })
        assertEquals(30L, result.rawLastThreadId)
        assertEquals(3, raw.data_!!.general_list.size)
    }
}
