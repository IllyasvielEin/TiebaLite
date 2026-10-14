package com.huanchengfly.tieba.post.ui.page.forum.paging

import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test

class OwnedPaginationTest {
    private data class Request(
        val query: String,
        val cursor: GeneralPagingCursor,
        val reply: CompletableDeferred<PagingPage<GeneralPagingCursor, Long, Unit>> = CompletableDeferred(),
        val finished: CompletableDeferred<Unit> = CompletableDeferred(),
    ) {
        fun succeed(rawLastId: Long, visibleIds: List<Long>, hasMore: Boolean = true) {
            val next = cursor.nextPage(rawLastId)
            reply.complete(PagingPage(next, visibleIds, hasMore, cursor.progressedTo(next)))
        }
        fun fail() { reply.completeExceptionally(IllegalStateException("network error")) }
    }

    private class Fixture(scope: CoroutineScope, ignoreCancellation: Boolean = false, accountVersion: () -> Long = { 0L }) {
        val actions = Channel<PagingAction<String>>(Channel.UNLIMITED)
        val requests = Channel<Request>(Channel.UNLIMITED)
        val output = Channel<OwnedPagingChange<String, GeneralPagingCursor, Long, Unit>>(Channel.UNLIMITED)
        private val allRequests = mutableListOf<Request>()
        private val owner = OwnedPagination<String, GeneralPagingCursor, Long, Unit>(
            initialCursor = { GeneralPagingCursor() },
            accountSession = accountVersion,
            itemId = { it },
            fetch = { query, cursor ->
                val request = Request(query, cursor)
                allRequests += request
                requests.send(request)
                try {
                    if (ignoreCancellation) withContext(NonCancellable) { request.reply.await() }
                    else request.reply.await()
                } finally {
                    request.finished.complete(Unit)
                }
            },
        )
        private val job = scope.launch(start = CoroutineStart.UNDISPATCHED) {
            owner.changes(actions.receiveAsFlow()).collect { output.send(it) }
        }
        suspend fun request(): Request = withTimeout(3000) { requests.receive() }
        suspend fun event() = withTimeout(3000) { output.receive() }
        suspend fun start(replacing: Boolean, clearList: Boolean = false): OwnedPagingChange<String, GeneralPagingCursor, Long, Unit> {
            val result = event()
            assertEquals(PagingChange.Start(replacing, clearList), result.change)
            result.applied()
            return result
        }
        suspend fun success(): PagingChange.Success<String, GeneralPagingCursor, Long, Unit> {
            val result = event()
            assertTrue(result.change is PagingChange.Success)
            result.applied() // Same acknowledgement as the production reducer.
            @Suppress("UNCHECKED_CAST")
            return result.change as PagingChange.Success<String, GeneralPagingCursor, Long, Unit>
        }
        suspend fun seed(query: String = "old", id: Long = 10) {
            actions.send(PagingAction.Replace(query))
            start(true)
            request().succeed(id, listOf(id))
            success()
        }
        suspend fun close() {
            allRequests.forEach { it.reply.cancel() }
            job.cancelAndJoin()
        }
    }

    @Test fun refreshImmediatelyInvalidatesOldLoadingSuccessAndDelayedSideEffects() = runBlocking {
        val f = Fixture(this, ignoreCancellation = true)
        try {
            f.seed()
            f.actions.send(PagingAction.More())
            val oldLoading = f.start(false)
            val old = f.request()
            f.actions.send(PagingAction.Replace("new"))
            f.start(true)
            val fresh = f.request()
            assertFalse(oldLoading.isCurrent())
            old.succeed(20, listOf(20))
            old.finished.await()
            fresh.succeed(30, listOf(30))
            val result = f.success()
            assertEquals("new", result.query)
            assertEquals(listOf(30L), result.items)
            assertTrue(f.output.tryReceive().isFailure)
        } finally { f.close() }
    }

    @Test fun oldFailureThatIgnoresCancellationCannotProduceToastOrFailure() = runBlocking {
        val f = Fixture(this, ignoreCancellation = true)
        try {
            f.seed()
            f.actions.send(PagingAction.More())
            f.start(false)
            val old = f.request()
            f.actions.send(PagingAction.Replace("new"))
            f.start(true)
            val fresh = f.request()
            old.fail()
            old.finished.await()
            fresh.succeed(30, listOf(30))
            assertEquals("new", f.success().query)
            assertTrue(f.output.tryReceive().isFailure)
        } finally { f.close() }
    }

    @Test fun queuedOldFailureHasFinalUiGuardAfterRefreshAcceptance() = runBlocking {
        val f = Fixture(this)
        try {
            f.seed()
            f.actions.send(PagingAction.More())
            f.start(false)
            f.request().fail()
            val queued = f.event()
            assertTrue(queued.change is PagingChange.Failure)
            f.actions.send(PagingAction.Replace("new"))
            f.start(true)
            val request = f.request()
            var toastCount = 0
            queued.ifCurrent(Unit) { toastCount++ }
            assertEquals(0, toastCount)
            request.succeed(30, listOf(30))
            f.success()
        } finally { f.close() }
    }

    @Test fun twoOwnersNeverShareQueryCursorGenerationOrJobs() = runBlocking {
        val a = Fixture(this, ignoreCancellation = true)
        val b = Fixture(this)
        try {
            a.actions.send(PagingAction.Replace("A"))
            a.start(true)
            val oldA = a.request()
            b.actions.send(PagingAction.Replace("B"))
            val bLoading = b.start(true)
            val pendingB = b.request()
            a.actions.send(PagingAction.Replace("A-new"))
            a.start(true)
            val newA = a.request()
            assertTrue(bLoading.isCurrent())
            pendingB.succeed(99, listOf(99))
            assertEquals("B", b.success().query)
            oldA.succeed(1, listOf(1))
            oldA.finished.await()
            newA.succeed(2, listOf(2))
            assertEquals("A-new", a.success().query)
            b.actions.send(PagingAction.More())
            b.start(false)
            val nextB = b.request()
            assertEquals(99L, nextB.cursor.lastThreadId)
            nextB.succeed(100, listOf(100))
            b.success()
        } finally { a.close(); b.close() }
    }

    @Test fun repeatedLoadMoreDuringFlightIsDroppedInsteadOfQueuedSnapshots() = runBlocking {
        val f = Fixture(this, ignoreCancellation = true)
        try {
            f.seed()
            f.actions.send(PagingAction.More())
            f.start(false)
            val old = f.request()
            repeat(20) { f.actions.send(PagingAction.More()) }
            f.actions.send(PagingAction.Replace("barrier"))
            f.start(true)
            val barrier = f.request()
            assertEquals("barrier", barrier.query)
            assertTrue(f.requests.tryReceive().isFailure)
            old.succeed(20, listOf(20))
            old.finished.await()
            barrier.succeed(30, listOf(30))
            f.success()
            f.actions.send(PagingAction.More())
            f.start(false)
            val next = f.request()
            assertEquals(30L, next.cursor.lastThreadId)
            assertEquals(1, next.cursor.page)
            next.succeed(40, listOf(40))
            f.success()
            assertTrue(f.requests.tryReceive().isFailure)
        } finally { f.close() }
    }

    @Test fun filteredTailUsesRawCursorAndEmptyDuplicatePagesContinueUntilNewId() = runBlocking {
        val f = Fixture(this)
        try {
            f.actions.send(PagingAction.Replace("raw"))
            f.start(true)
            f.request().succeed(100, listOf(10)) // Displayed tail differs from raw tail.
            f.success()
            f.actions.send(PagingAction.More())
            f.start(false)
            val filtered = f.request()
            assertEquals(100L, filtered.cursor.lastThreadId)
            filtered.succeed(200, emptyList())
            val duplicate = f.request()
            assertEquals(200L, duplicate.cursor.lastThreadId)
            duplicate.succeed(300, listOf(10))
            val visible = f.request()
            visible.succeed(400, listOf(20))
            val result = f.success()
            assertEquals(listOf(20L), result.items)
            assertEquals(4, result.cursor.page)
            assertFalse(result.manualContinue)
            assertTrue(f.requests.tryReceive().isFailure)
        } finally { f.close() }
    }

    @Test fun budgetIsThreeTotalRequestsAndOnlyManualContinueCanResetIt() = runBlocking {
        val f = Fixture(this)
        try {
            f.actions.send(PagingAction.Replace("empty"))
            f.start(true)
            repeat(3) { index -> f.request().succeed((index + 1).toLong(), emptyList()) }
            val paused = f.success()
            assertEquals(3, paused.cursor.page)
            assertTrue(paused.hasMore)
            assertTrue(paused.manualContinue)
            assertTrue(f.requests.tryReceive().isFailure)
            f.actions.send(PagingAction.More(manual = true))
            f.start(false)
            val next = f.request()
            assertEquals(3, next.cursor.page)
            next.succeed(4, listOf(44))
            val resumed = f.success()
            assertFalse(resumed.replacing)
            assertEquals(listOf(44L), resumed.items)
            assertFalse(resumed.manualContinue)
        } finally { f.close() }
    }

    @Test fun delayedAutomaticUiTriggersCannotRestartExhaustedBudget() = runBlocking {
        val f = Fixture(this)
        try {
            f.actions.send(PagingAction.Replace("empty"))
            f.start(true)
            repeat(3) { index -> f.request().succeed((index + 1).toLong(), emptyList()) }
            assertTrue(f.success().manualContinue)
            repeat(20) { f.actions.send(PagingAction.More()) }
            // A newer query is a deterministic mailbox barrier, with no sleeps or polling.
            f.actions.send(PagingAction.Replace("barrier"))
            f.start(true)
            val next = f.request()
            assertEquals("barrier", next.query)
            assertTrue(f.requests.tryReceive().isFailure)
            next.succeed(4, listOf(4))
            f.success()
        } finally { f.close() }
    }

    @Test fun repeatedRawCursorAndEmptyRawPageStopSafely() = runBlocking {
        val f = Fixture(this)
        try {
            f.seed(id = 10)
            f.actions.send(PagingAction.More())
            f.start(false)
            f.request().succeed(10, emptyList())
            val result = f.success()
            assertFalse(result.hasMore)
            assertFalse(result.manualContinue)
            f.actions.send(PagingAction.More(manual = true))
            f.actions.send(PagingAction.Replace("barrier"))
            f.start(true)
            val next = f.request()
            assertEquals("barrier", next.query)
            next.succeed(0, emptyList())
            assertFalse(f.success().hasMore)
        } finally { f.close() }
    }

    @Test fun refreshFailureRetainsDisplayedQueryAndCursor() = runBlocking {
        val f = Fixture(this)
        try {
            f.seed("old", 10)
            f.actions.send(PagingAction.Replace("new"))
            f.start(true)
            f.request().fail()
            assertTrue(f.event().change is PagingChange.Failure)
            f.actions.send(PagingAction.More())
            f.start(false)
            val request = f.request()
            assertEquals("old", request.query)
            assertEquals(10L, request.cursor.lastThreadId)
            request.succeed(20, listOf(20))
            f.success()
        } finally { f.close() }
    }

    @Test fun refreshFailureCannotRestoreAnOldSuccessNeverAppliedToUi() = runBlocking {
        val f = Fixture(this)
        try {
            f.seed("displayed", 10)
            f.actions.send(PagingAction.More())
            f.start(false)
            f.request().succeed(20, listOf(20))
            val queued = f.event() // Intentionally not acknowledged by the UI reducer.
            f.actions.send(PagingAction.Replace("new"))
            f.start(true)
            val refresh = f.request()
            assertFalse(queued.isCurrent())
            queued.applied()
            refresh.fail()
            f.event()
            f.actions.send(PagingAction.More())
            f.start(false)
            val next = f.request()
            assertEquals("displayed", next.query)
            assertEquals(10L, next.cursor.lastThreadId)
            next.succeed(30, listOf(30))
            f.success()
        } finally { f.close() }
    }

    @Test fun errorAfterSuccessfulEmptyAppendRetainsProgressButNotFailedPage() = runBlocking {
        val f = Fixture(this)
        try {
            f.seed()
            f.actions.send(PagingAction.More())
            f.start(false)
            f.request().succeed(20, emptyList())
            f.request().fail()
            val event = f.event()
            @Suppress("UNCHECKED_CAST")
            val error = event.change as PagingChange.Failure<String, GeneralPagingCursor, Long, Unit>
            assertEquals(20L, error.progress?.cursor?.lastThreadId)
            event.applied()
            f.actions.send(PagingAction.More())
            f.start(false)
            val retry = f.request()
            assertEquals(20L, retry.cursor.lastThreadId)
            assertEquals(2, retry.cursor.page)
            retry.succeed(30, listOf(30))
            f.success()
        } finally { f.close() }
    }

    @Test fun accountSwitchIncludingAtoBtoAInvalidatesOldResultsAndCursor() = runBlocking {
        val version = AtomicLong(0)
        val f = Fixture(this, ignoreCancellation = true, accountVersion = { version.get() })
        try {
            f.seed()
            f.actions.send(PagingAction.More())
            val oldLoading = f.start(false)
            val old = f.request()
            // A -> B -> A has the same final UID, but a different non-credential session epoch.
            version.incrementAndGet()
            version.incrementAndGet()
            assertFalse(oldLoading.isCurrent())
            f.actions.send(PagingAction.SessionChanged)
            f.start(true, clearList = true)
            val fresh = f.request()
            assertEquals(GeneralPagingCursor(), fresh.cursor)
            old.fail()
            old.finished.await()
            fresh.succeed(30, listOf(30))
            assertEquals(listOf(30L), f.success().items)
            assertTrue(f.output.tryReceive().isFailure)
        } finally { f.close() }
    }

    @Test fun logoutFailedReloadNeverRestoresPreviousAccountsPrivateListOrCursor() = runBlocking {
        val version = AtomicLong(0)
        val f = Fixture(this, accountVersion = { version.get() })
        try {
            f.seed("private", 10)
            version.incrementAndGet() // Logout also advances the session, including null account.
            f.actions.send(PagingAction.More()) // A stale UI action is safely converted into first page.
            f.start(true, clearList = true)
            val publicReload = f.request()
            assertEquals(0, publicReload.cursor.page)
            publicReload.fail()
            f.event()
            f.actions.send(PagingAction.More())
            f.actions.send(PagingAction.Replace("barrier"))
            f.start(true)
            val barrier = f.request()
            assertEquals("barrier", barrier.query)
            assertEquals(0, barrier.cursor.page)
            barrier.succeed(20, listOf(20))
            f.success()
        } finally { f.close() }
    }

    @Test fun initialSessionChangedDoesNotCreateDuplicateFirstPageRequest() = runBlocking {
        val version = AtomicLong(12)
        val f = Fixture(this, accountVersion = { version.get() })
        try {
            f.actions.send(PagingAction.SessionChanged)
            f.seed()
            assertTrue(f.requests.tryReceive().isFailure)
            f.actions.send(PagingAction.SessionChanged)
            f.actions.send(PagingAction.More())
            f.start(false)
            val more = f.request()
            assertEquals(1, more.cursor.page)
            more.succeed(20, listOf(20))
            f.success()
        } finally { f.close() }
    }

    @Test fun queuedAccountClearSurvivesNewerReplaceUntilActuallyApplied() = runBlocking {
        val version = AtomicLong(0)
        val f = Fixture(this, accountVersion = { version.get() })
        try {
            f.seed("private", 10)
            version.incrementAndGet()
            f.actions.send(PagingAction.SessionChanged)
            val queuedClear = f.event() // UI has not yet cleared the previous account's list.
            assertEquals(PagingChange.Start(true, true), queuedClear.change)
            f.request()
            f.actions.send(PagingAction.Replace("newer"))
            f.start(true, clearList = true)
            val newer = f.request()
            assertFalse(queuedClear.isCurrent())
            queuedClear.applied()
            newer.fail()
            f.event()
            f.actions.send(PagingAction.More())
            f.actions.send(PagingAction.Replace("barrier"))
            f.start(true)
            val barrier = f.request()
            assertEquals("barrier", barrier.query)
            assertEquals(0, barrier.cursor.page)
            barrier.succeed(20, listOf(20))
            f.success()
        } finally { f.close() }
    }

}
