package com.huanchengfly.tieba.post.ui.page.forum.paging

import org.junit.Assert.*
import org.junit.Test

class ForumPagingCursorTest {
    @Test fun goodClassifyAndSortStayInOwnerQueryAcrossSubsequentPages() {
        val good = ForumListQuery(7, "forum", true, sortType = 99, goodClassifyId = 8)
        assertEquals(8, good.requestClassify)
        assertEquals(-1, good.requestSort)
        assertEquals(0, good.requestBatchSort)
        assertEquals(0, good.copy(goodClassifyId = null).requestClassify)
        val latest = good.copy(isGood = false, sortType = 5)
        assertNull(latest.requestClassify)
        assertEquals(5, latest.requestSort)
    }

    @Test fun idBatchesKeepServerHasMoreIndependentOfFilteredThreads() {
        val ids = (1L..65L).toList()
        val page = ForumPagingCursor().nextPage(listOf(100), ids, hasMore = true)
        assertEquals(30, page.batch.size)
        val first = page.consumeBatch()
        assertEquals(35, first.remainingIds.size)
        assertTrue(first.serverHasMore)
        assertTrue(first.hasMore)
        assertEquals(1, first.page)
        val last = first.consumeBatch().consumeBatch()
        assertTrue(last.remainingIds.isEmpty())
        assertTrue(last.serverHasMore)
        assertTrue(last.hasMore) // Next request goes back to frsPage page 2.
    }

    @Test fun remainingIdsStayLoadableEvenWhenServerPageHasNoMore() {
        val first = ForumPagingCursor().nextPage(listOf(1), listOf(2, 3), hasMore = false)
        assertTrue(first.hasMore)
        val last = first.consumeBatch()
        assertFalse(last.serverHasMore)
        assertFalse(last.hasMore)
    }

    @Test fun cursorIsImmutableSoFailedIdBatchConsumesNothing() {
        val before = ForumPagingCursor(3, (1L..35L).toList(), false, listOf(100))
        val successful = before.consumeBatch()
        assertEquals(35, before.remainingIds.size)
        assertEquals(listOf(31L, 32L, 33L, 34L, 35L), successful.remainingIds)
        assertTrue(before.progressedTo(successful))
    }

    @Test fun repeatedRawPageCannotLoopJustBecausePageNumberIncreases() {
        val first = ForumPagingCursor().nextPage(listOf(1, 2), emptyList(), true)
        val repeated = first.nextPage(listOf(1, 2), emptyList(), true)
        assertFalse(first.progressedTo(repeated))
        assertFalse(first.progressedTo(first.nextPage(emptyList(), emptyList(), true)))
        assertTrue(first.progressedTo(first.nextPage(listOf(3), emptyList(), true)))
    }

    @Test fun generalCursorComesFromRawTailIncludingFilteredVideoOrLiveTail() {
        val first = GeneralPagingCursor().nextPage(100)
        assertEquals(100L, first.lastThreadId)
        assertEquals(1, first.page)
        assertTrue(GeneralPagingCursor().progressedTo(first))
        assertFalse(first.progressedTo(first.nextPage(100)))
    }

    @Test fun generalOwnerQueryPreservesEveryRequestDimension() {
        val query = GeneralListQuery(1, "forum", 2, 3, "tab", 1, 1, 4)
        assertNotEquals(query, query.copy(forumName = "other"))
        assertNotEquals(query, query.copy(tabName = "other"))
        assertNotEquals(query, query.copy(isGeneralTab = 0))
        assertNotEquals(query, query.copy(isDefaultNavTab = 0))
        assertNotEquals(query, query.copy(sortType = 5))
    }
}
