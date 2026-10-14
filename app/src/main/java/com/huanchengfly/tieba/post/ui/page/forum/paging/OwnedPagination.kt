package com.huanchengfly.tieba.post.ui.page.forum.paging

import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch

/** An action carries no UI cursor snapshot. A paused budget requires an explicit button click. */
internal sealed interface PagingAction<out Q> {
    data class Replace<Q>(val query: Q) : PagingAction<Q>
    data object SessionChanged : PagingAction<Nothing>
    data class More(val manual: Boolean = false) : PagingAction<Nothing>
}

internal data class PagingPage<C, T, M>(
    val cursor: C,
    val items: List<T>,
    val hasMore: Boolean,
    val progressed: Boolean,
    val metadata: M? = null,
)

internal sealed interface PagingChange<out Q, out C, out T, out M> {
    data class Start(val replacing: Boolean, val clearList: Boolean = false) : PagingChange<Nothing, Nothing, Nothing, Nothing>
    data class Success<Q, C, T, M>(
        val replacing: Boolean,
        val query: Q,
        val cursor: C,
        val items: List<T>,
        val metadata: M?,
        val hasMore: Boolean,
        val manualContinue: Boolean,
    ) : PagingChange<Q, C, T, M>
    data class Failure<Q, C, T, M>(
        val replacing: Boolean,
        val error: Throwable,
        // Successful append pages stay consumed if a later page fails. Failed pages never do.
        val progress: Success<Q, C, T, M>? = null,
    ) : PagingChange<Q, C, T, M>
}

/** The guard is checked again at reduction and at the final UI side effect, not just at fetch. */
internal class OwnedPagingChange<Q, C, T, M>(
    val change: PagingChange<Q, C, T, M>,
    private val epoch: AtomicLong,
    private val generation: Long,
    private val accountSession: Long = 0L,
    private val currentAccountSession: () -> Long = { 0L },
    private val acknowledge: () -> Unit = {},
) {
    fun isCurrent(): Boolean = epoch.get() == generation && currentAccountSession() == accountSession
    fun <R> ifCurrent(fallback: R, action: () -> R): R = synchronized(epoch) {
        if (isCurrent()) action() else fallback
    }
    fun applied() = ifCurrent(Unit) { acknowledge() }
}

/**
 * One instance per list ViewModel. The mailbox serializes intent acceptance and network results;
 * cancellation only saves work. The epoch, including queued output guards, establishes correctness.
 */
internal class OwnedPagination<Q, C, T, M>(
    private val initialCursor: (Q) -> C,
    private val fetch: suspend (Q, C) -> PagingPage<C, T, M>,
    private val itemId: (T) -> Long,
    private val requestBudget: Int = 3,
    private val accountSession: () -> Long = { 0L },
) {
    private val epoch = AtomicLong(0)

    private data class Session<Q, C, M>(
        val query: Q,
        val cursor: C,
        val seen: Set<Long>,
        val metadata: M?,
        val hasMore: Boolean,
        val manualContinue: Boolean,
    )

    private class Operation<Q, C, T, M>(
        val generation: Long,
        val accountSession: Long,
        val replacing: Boolean,
        val query: Q,
        var cursor: C,
        var seen: Set<Long>,
        var metadata: M?,
        var hasMore: Boolean = true,
        var pages: Int = 0,
        val items: MutableList<T> = mutableListOf(),
    )

    private sealed interface Command<out Q, out C, out T, out M> {
        data class Action<Q>(val action: PagingAction<Q>) : Command<Q, Nothing, Nothing, Nothing>
        data class Result<C, T, M>(
            val generation: Long,
            val page: PagingPage<C, T, M>?,
            val error: Throwable?,
        ) : Command<Nothing, C, T, M>
    }

    fun changes(actions: Flow<PagingAction<Q>>): Flow<OwnedPagingChange<Q, C, T, M>> = channelFlow {
        require(requestBudget > 0)
        val mailbox = Channel<Command<Q, C, T, M>>(Channel.UNLIMITED)
        var session: Session<Q, C, M>? = null
        val displayedSession = AtomicReference<Session<Q, C, M>?>(null)
        val pendingAccountClear = AtomicBoolean(false)
        var operation: Operation<Q, C, T, M>? = null
        var request: Job? = null
        var activeAccountSession = accountSession()
        var lastQuery: Q? = null
        launch {
            actions.collect { mailbox.send(Command.Action(it)) }
        }

        suspend fun emit(change: PagingChange<Q, C, T, M>, generation: Long) {
            val snapshot = when (change) {
                is PagingChange.Success -> session
                is PagingChange.Failure -> if (change.progress != null) session else null
                is PagingChange.Start -> null
            }
            send(OwnedPagingChange(change, epoch, generation, activeAccountSession, accountSession) {
                if (snapshot != null) displayedSession.set(snapshot)
                if ((change is PagingChange.Start && change.clearList) || change is PagingChange.Success) {
                    pendingAccountClear.set(false)
                }
            })
        }

        fun requestPage(op: Operation<Q, C, T, M>) {
            val cursor = op.cursor
            request = launch {
                try {
                    if (accountSession() != op.accountSession) {
                        mailbox.trySend(Command.Action(PagingAction.SessionChanged))
                        return@launch
                    }
                    val page = fetch(op.query, cursor)
                    mailbox.trySend(Command.Result(op.generation, page, null))
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Throwable) {
                    mailbox.trySend(Command.Result(op.generation, null, error))
                }
            }
        }

        fun success(op: Operation<Q, C, T, M>, paused: Boolean) = PagingChange.Success(
            op.replacing, op.query, op.cursor, op.items.toList(), op.metadata, op.hasMore, paused
        )

        fun commit(op: Operation<Q, C, T, M>, paused: Boolean) {
            session = Session(op.query, op.cursor, op.seen, op.metadata, op.hasMore, paused)
        }

        suspend fun replace(query: Q, clearList: Boolean) {
            val generation = synchronized(epoch) { epoch.incrementAndGet() }
            val newAccountSession = accountSession()
            val effectiveClear = clearList || newAccountSession != activeAccountSession || pendingAccountClear.get()
            activeAccountSession = newAccountSession
            lastQuery = query
            if (effectiveClear) {
                pendingAccountClear.set(true)
                displayedSession.set(null)
            }
            session = displayedSession.get()
            request?.cancel()
            val op = Operation<Q, C, T, M>(
                generation, activeAccountSession, true, query, initialCursor(query), emptySet(), null
            )
            operation = op
            emit(PagingChange.Start(true, effectiveClear), generation)
            requestPage(op)
        }

        try {
            for (command in mailbox) {
                when (command) {
                    is Command.Action -> {
                        val action = command.action
                        val changedAccount = accountSession() != activeAccountSession
                        if (changedAccount) {
                            val query = if (action is PagingAction.Replace) action.query else lastQuery
                            if (query != null) replace(query, clearList = true)
                            continue
                        }
                        when (action) {
                            is PagingAction.Replace -> replace(action.query, clearList = false)
                            PagingAction.SessionChanged -> Unit
                            is PagingAction.More -> {
                                val current = session ?: continue
                                if (operation != null || !current.hasMore ||
                                    (current.manualContinue && !action.manual)) continue
                                val op = Operation<Q, C, T, M>(
                                    epoch.get(), activeAccountSession, false, current.query, current.cursor,
                                    current.seen, current.metadata
                                )
                                operation = op
                                emit(PagingChange.Start(false), op.generation)
                                requestPage(op)
                            }
                        }
                    }
                    is Command.Result -> {
                        if (accountSession() != activeAccountSession) {
                            lastQuery?.let { replace(it, clearList = true) }
                            continue
                        }
                        val op = operation ?: continue
                        if (command.generation != epoch.get() || command.generation != op.generation) continue
                        if (command.error != null) {
                            // Replace is transactional, so failure retains the old list/query/cursor.
                            val progress = if (!op.replacing && op.pages > 0) {
                                commit(op, false)
                                success(op, false)
                            } else null
                            if (op.replacing) session = displayedSession.get()
                            operation = null
                            emit(PagingChange.Failure(op.replacing, command.error, progress), op.generation)
                            continue
                        }
                        val page = checkNotNull(command.page)
                        op.pages++
                        op.cursor = page.cursor
                        op.metadata = page.metadata ?: op.metadata
                        val added = page.items.filter { itemId(it) !in op.seen }.distinctBy(itemId)
                        op.items += added
                        op.seen = op.seen + added.map(itemId)
                        // A repeated raw cursor / empty raw response cannot spin, even across clicks.
                        op.hasMore = page.hasMore && page.progressed
                        if (added.isNotEmpty() || !op.hasMore || op.pages >= requestBudget) {
                            val paused = added.isEmpty() && op.hasMore && op.pages >= requestBudget
                            commit(op, paused)
                            operation = null
                            emit(success(op, paused), op.generation)
                        } else {
                            requestPage(op)
                        }
                    }
                }
            }
        } finally {
            synchronized(epoch) { epoch.incrementAndGet() }
            request?.cancel()
            mailbox.close()
        }
    }
}
