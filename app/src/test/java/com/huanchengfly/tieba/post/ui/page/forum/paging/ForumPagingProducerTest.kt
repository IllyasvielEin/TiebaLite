package com.huanchengfly.tieba.post.ui.page.forum.paging

import com.huanchengfly.tieba.post.api.models.protos.FrsTabInfo
import com.huanchengfly.tieba.post.api.models.protos.ThreadInfo
import com.huanchengfly.tieba.post.arch.PartialChange
import com.huanchengfly.tieba.post.arch.PartialChangeProducer
import com.huanchengfly.tieba.post.arch.UiIntent
import com.huanchengfly.tieba.post.arch.UiState
import com.huanchengfly.tieba.post.arch.wrapImmutable
import com.huanchengfly.tieba.post.ui.models.ThreadItemData
import com.huanchengfly.tieba.post.ui.page.forum.generaltablist.*
import com.huanchengfly.tieba.post.ui.page.forum.threadlist.*
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test

/** Exercises the actual per-VM producers, query construction, reducers and event projection. */
class ForumPagingProducerTest {
    private fun item(id: Long) = ThreadItemData(ThreadInfo(id = id).wrapImmutable(), blocked = false, hidden = false)

    private data class Fetch<Q, C, M>(
        val query: Q,
        val cursor: C,
        val reply: CompletableDeferred<PagingPage<C, ThreadItemData, M>> = CompletableDeferred(),
    )

    private class Harness<I : UiIntent, PC : PartialChange<S>, S : UiState>(
        scope: CoroutineScope,
        producer: PartialChangeProducer<I, PC, S>,
    ) {
        private val intents = MutableSharedFlow<I>()
        private val output = Channel<PC>(Channel.UNLIMITED)
        private val job = scope.launch(start = CoroutineStart.UNDISPATCHED) {
            producer.toPartialChangeFlow(intents).collect { output.send(it) }
        }
        suspend fun send(intent: I) {
            withTimeout(3000) { intents.subscriptionCount.first { it >= 2 } }
            intents.emit(intent)
        }
        suspend fun next(): PC = withTimeout(3000) { output.receive() }
        suspend fun close() { job.cancelAndJoin() }
    }

    @Test fun forumFailureRetainsOwnershipThroughPublicChangeAndEventBaseTypes() {
        val epoch = AtomicLong(1)
        val error = IllegalStateException("old failure")
        val owned = OwnedPagingChange<ForumListQuery, ForumPagingCursor, ThreadItemData, ForumPageMetadata>(
            PagingChange.Failure(replacing = false, error = error), epoch, 1,
        )
        val paging = ForumThreadListPartialChange.Paging(owned)
        val change: ForumThreadListPartialChange = paging
        val event: ForumThreadListUiEvent = paging.failureEvent() as ForumThreadListUiEvent
        val failure = event as ForumThreadListUiEvent.LoadFailure
        assertSame(error, failure.error)
        val loading = ForumThreadListUiState(isLoadingMore = true)
        assertFalse(change.reduce(loading).isLoadingMore)

        epoch.incrementAndGet()
        assertNull(paging.failureEvent())
        assertSame(loading, change.reduce(loading))
        var delivered = false
        failure.owned.ifCurrent(Unit) { delivered = true }
        assertFalse(delivered)
    }

    @Test fun goodProducerRetainsSelectedClassifyForEveryLoadMoreAndClearsOldLoadingOnRefresh() = runBlocking {
        val calls = Channel<Fetch<ForumListQuery, ForumPagingCursor, ForumPageMetadata>>(Channel.UNLIMITED)
        val producer = ForumThreadListPartialChangeProducer(ForumThreadListType.Good, fetchPage = { query, cursor ->
            Fetch<ForumListQuery, ForumPagingCursor, ForumPageMetadata>(query, cursor).also { calls.send(it) }.reply.await()
        })
        val h = Harness(this, producer)
        try {
            h.send(ForumThreadListUiIntent.FirstLoad("forum", goodClassifyId = 8, forumId = 7))
            var state = h.next().reduce(ForumThreadListUiState())
            assertTrue(state.isRefreshing)
            val first = withTimeout(3000) { calls.receive() }
            assertEquals(8, first.query.requestClassify)
            assertEquals(-1, first.query.requestSort)
            val cursor = first.cursor.nextPage(listOf(10, 100), emptyList(), true)
            first.reply.complete(PagingPage(cursor, listOf(item(10)), true, true))
            state = h.next().reduce(state)
            h.send(ForumThreadListUiIntent.LoadMore())
            state = h.next().reduce(state)
            assertTrue(state.isLoadingMore)
            val more = withTimeout(3000) { calls.receive() }
            assertEquals(8, more.query.requestClassify)
            assertEquals(7L, more.query.forumId)
            assertEquals(cursor, more.cursor)
            h.send(ForumThreadListUiIntent.Refresh("forum", goodClassifyId = 9, forumId = 7))
            state = h.next().reduce(state)
            assertFalse(state.isLoadingMore)
            assertTrue(state.isRefreshing)
            val refresh = withTimeout(3000) { calls.receive() }
            assertEquals(9, refresh.query.requestClassify)
            refresh.reply.complete(PagingPage(refresh.cursor.nextPage(listOf(20), emptyList(), false), listOf(item(20)), false, true))
            state = h.next().reduce(state)
            assertEquals(9, state.goodClassifyId)
            assertEquals(listOf(20L), state.threadList.map { it.thread.get { id } })
            assertFalse(state.isRefreshing)
        } finally { h.close() }
    }

    @Test fun goodProducerNullCategoryRemainsGoodAndIdBatchErrorDoesNotConsumeIds() = runBlocking {
        val calls = Channel<Fetch<ForumListQuery, ForumPagingCursor, ForumPageMetadata>>(Channel.UNLIMITED)
        val producer = ForumThreadListPartialChangeProducer(ForumThreadListType.Good, fetchPage = { query, cursor ->
            Fetch<ForumListQuery, ForumPagingCursor, ForumPageMetadata>(query, cursor).also { calls.send(it) }.reply.await()
        })
        val h = Harness(this, producer)
        try {
            h.send(ForumThreadListUiIntent.Refresh("forum", goodClassifyId = null, forumId = 7))
            var state = h.next().reduce(ForumThreadListUiState())
            val first = withTimeout(3000) { calls.receive() }
            assertEquals(0, first.query.requestClassify)
            val ids = (1L..35L).toList()
            first.reply.complete(PagingPage(first.cursor.nextPage(listOf(100), ids, false), listOf(item(100)), true, true))
            state = h.next().reduce(state)
            h.send(ForumThreadListUiIntent.LoadMore())
            state = h.next().reduce(state)
            val failedBatch = withTimeout(3000) { calls.receive() }
            assertEquals(30, failedBatch.cursor.batch.size)
            assertEquals(0, failedBatch.query.requestBatchSort)
            failedBatch.reply.completeExceptionally(IllegalStateException("batch failed"))
            val failure = h.next() as ForumThreadListPartialChange.Paging
            assertNotNull(failure.failureEvent())
            state = failure.reduce(state)
            assertEquals(ids, state.threadListIds)
            assertTrue(state.hasMore)
            h.send(ForumThreadListUiIntent.LoadMore())
            h.next().reduce(state)
            val retry = withTimeout(3000) { calls.receive() }
            assertEquals(failedBatch.cursor, retry.cursor)
            retry.reply.complete(PagingPage(retry.cursor.consumeBatch(), listOf(item(1)), true, true))
            state = h.next().reduce(state)
            assertEquals(ids.drop(30), state.threadListIds)
        } finally { h.close() }
    }

    @Test fun generalProducerUsesRawCursorAndQueuedFailureCannotReduceOrDispatchAfterNewQuery() = runBlocking {
        val calls = Channel<Fetch<GeneralListQuery, GeneralPagingCursor, Unit>>(Channel.UNLIMITED)
        val producer = GeneralTabListPartialChangeProducer(fetchPage = { query, cursor ->
            Fetch<GeneralListQuery, GeneralPagingCursor, Unit>(query, cursor).also { calls.send(it) }.reply.await()
        })
        val h = Harness(this, producer)
        try {
            val tab = FrsTabInfo(tabId = 2, tabType = 3, tabName = "tab", isGeneralTab = 1, isDefault = 1)
            h.send(GeneralTabListUiIntent.FirstLoad(7, "forum", tab, sortType = 5))
            var state = h.next().reduce(GeneralTabListUiState())
            val first = withTimeout(3000) { calls.receive() }
            assertEquals(GeneralListQuery(7, "forum", 2, 3, "tab", 1, 1, 5), first.query)
            first.reply.complete(PagingPage(first.cursor.nextPage(100), listOf(item(10)), true, true))
            state = h.next().reduce(state)
            assertEquals(100L, state.lastThreadId)
            h.send(GeneralTabListUiIntent.LoadMore())
            state = h.next().reduce(state)
            val more = withTimeout(3000) { calls.receive() }
            assertEquals(100L, more.cursor.lastThreadId)
            more.reply.completeExceptionally(IllegalStateException("old failure"))
            val failure = h.next() as GeneralTabListPartialChange.Paging
            val delayedEvent = failure.failureEvent() as GeneralTabListUiEvent.LoadFailure
            h.send(GeneralTabListUiIntent.Refresh(7, "forum", tab, sortType = 6))
            state = h.next().reduce(state)
            val refresh = withTimeout(3000) { calls.receive() }
            assertFalse(state.isLoadingMore)
            assertNull(failure.failureEvent())
            assertEquals(state, failure.reduce(state))
            var delivered = false
            delayedEvent.owned.ifCurrent(Unit) { delivered = true }
            assertFalse(delivered)
            refresh.reply.complete(PagingPage(refresh.cursor.nextPage(200), listOf(item(20)), false, true))
            state = h.next().reduce(state)
            assertEquals(6, state.sortType)
            assertEquals(listOf(20L), state.threadList.map { it.thread.get { id } })
        } finally { h.close() }
    }

    @Test fun sessionChangedClearsActualReducerListAndFailureDoesNotRestorePrivateData() = runBlocking {
        val version = AtomicLong(0)
        val calls = Channel<Fetch<GeneralListQuery, GeneralPagingCursor, Unit>>(Channel.UNLIMITED)
        val producer = GeneralTabListPartialChangeProducer(
            fetchPage = { query, cursor ->
                Fetch<GeneralListQuery, GeneralPagingCursor, Unit>(query, cursor).also { calls.send(it) }.reply.await()
            }, accountSessionVersion = { version.get() }
        )
        val h = Harness(this, producer)
        try {
            h.send(GeneralTabListUiIntent.FirstLoad(7, "forum", FrsTabInfo()))
            var state = h.next().reduce(GeneralTabListUiState())
            val first = withTimeout(3000) { calls.receive() }
            first.reply.complete(PagingPage(first.cursor.nextPage(100), listOf(item(10)), true, true))
            state = h.next().reduce(state)
            assertFalse(state.threadList.isEmpty())
            version.incrementAndGet()
            h.send(GeneralTabListUiIntent.SessionChanged)
            state = h.next().reduce(state)
            assertTrue(state.threadList.isEmpty())
            assertEquals(0L, state.lastThreadId)
            val reload = withTimeout(3000) { calls.receive() }
            assertEquals(0, reload.cursor.page)
            reload.reply.completeExceptionally(IllegalStateException("public reload failed"))
            state = h.next().reduce(state)
            assertTrue(state.threadList.isEmpty())
            assertFalse(state.isRefreshing)
        } finally { h.close() }
    }

    @Test fun newerRefreshCannotSupersedeAccountClearAndLeaveOldPrivateListAfterFailure() = runBlocking {
        val version = AtomicLong(0)
        val calls = Channel<Fetch<GeneralListQuery, GeneralPagingCursor, Unit>>(Channel.UNLIMITED)
        val producer = GeneralTabListPartialChangeProducer(
            fetchPage = { query, cursor ->
                Fetch<GeneralListQuery, GeneralPagingCursor, Unit>(query, cursor).also { calls.send(it) }.reply.await()
            }, accountSessionVersion = { version.get() }
        )
        val h = Harness(this, producer)
        try {
            val tab = FrsTabInfo()
            h.send(GeneralTabListUiIntent.FirstLoad(7, "forum", tab))
            var state = h.next().reduce(GeneralTabListUiState())
            val first = withTimeout(3000) { calls.receive() }
            first.reply.complete(PagingPage(first.cursor.nextPage(100), listOf(item(10)), true, true))
            state = h.next().reduce(state)
            version.incrementAndGet()
            h.send(GeneralTabListUiIntent.SessionChanged)
            val queuedClear = h.next() // Deliberately leave the old UI state unchanged.
            withTimeout(3000) { calls.receive() }
            h.send(GeneralTabListUiIntent.Refresh(7, "forum", tab, sortType = 6))
            state = h.next().reduce(state)
            assertTrue(state.threadList.isEmpty())
            assertEquals(state, queuedClear.reduce(state))
            val reload = withTimeout(3000) { calls.receive() }
            reload.reply.completeExceptionally(IllegalStateException("reload failed"))
            state = h.next().reduce(state)
            assertTrue(state.threadList.isEmpty())
            assertEquals(0L, state.lastThreadId)
        } finally { h.close() }
    }

}
