package com.huanchengfly.tieba.post.ui.page.forum.threadlist

import androidx.compose.runtime.Stable
import com.huanchengfly.tieba.post.api.TiebaApi
import com.huanchengfly.tieba.post.api.models.AgreeBean
import com.huanchengfly.tieba.post.api.models.protos.frsPage.Classify
import com.huanchengfly.tieba.post.api.models.protos.updateAgreeStatus
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaUnknownException
import com.huanchengfly.tieba.post.api.retrofit.exception.getErrorCode
import com.huanchengfly.tieba.post.api.retrofit.exception.getErrorMessage
import com.huanchengfly.tieba.post.arch.BaseViewModel
import com.huanchengfly.tieba.post.arch.ImmutableHolder
import com.huanchengfly.tieba.post.arch.PartialChange
import com.huanchengfly.tieba.post.arch.PartialChangeProducer
import com.huanchengfly.tieba.post.arch.UiEvent
import com.huanchengfly.tieba.post.arch.UiIntent
import com.huanchengfly.tieba.post.arch.UiState
import com.huanchengfly.tieba.post.arch.wrapImmutable
import com.huanchengfly.tieba.post.repository.FrsPageRepository
import com.huanchengfly.tieba.post.ui.models.ThreadItemData
import com.huanchengfly.tieba.post.ui.models.distinctById
import com.huanchengfly.tieba.post.ui.page.forum.paging.ForumListQuery
import com.huanchengfly.tieba.post.ui.page.forum.paging.ForumPagingCursor
import com.huanchengfly.tieba.post.ui.page.forum.paging.OwnedPagination
import com.huanchengfly.tieba.post.ui.page.forum.paging.OwnedPagingChange
import com.huanchengfly.tieba.post.ui.page.forum.paging.PagingAction
import com.huanchengfly.tieba.post.ui.page.forum.paging.PagingChange
import com.huanchengfly.tieba.post.ui.page.forum.paging.PagingPage
import com.huanchengfly.tieba.post.utils.AccountUtil
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.collections.immutable.ImmutableList
import kotlinx.collections.immutable.persistentListOf
import kotlinx.collections.immutable.toImmutableList
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapConcat
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.mapNotNull
import kotlinx.coroutines.flow.merge
import kotlinx.coroutines.flow.onStart
import javax.inject.Inject

abstract class ForumThreadListViewModel :
    BaseViewModel<ForumThreadListUiIntent, ForumThreadListPartialChange, ForumThreadListUiState, ForumThreadListUiEvent>() {
    override fun createInitialState(): ForumThreadListUiState = ForumThreadListUiState()

    override fun dispatchEvent(partialChange: ForumThreadListPartialChange): UiEvent? =
        when (partialChange) {
            is ForumThreadListPartialChange.Paging -> partialChange.failureEvent()
            is ForumThreadListPartialChange.Agree.Failure -> {
                ForumThreadListUiEvent.AgreeFail(
                    partialChange.threadId,
                    partialChange.postId,
                    partialChange.hasAgree,
                    partialChange.error.getErrorCode(),
                    partialChange.error.getErrorMessage()
                )
            }

            else -> null
        }
}

enum class ForumThreadListType {
    Latest, Good
}

@Stable
@HiltViewModel
class LatestThreadListViewModel @Inject constructor() : ForumThreadListViewModel() {
    override fun createPartialChangeProducer(): PartialChangeProducer<ForumThreadListUiIntent, ForumThreadListPartialChange, ForumThreadListUiState> =
        ForumThreadListPartialChangeProducer(ForumThreadListType.Latest)
}

@Stable
@HiltViewModel
class GoodThreadListViewModel @Inject constructor() : ForumThreadListViewModel() {
    override fun createPartialChangeProducer(): PartialChangeProducer<ForumThreadListUiIntent, ForumThreadListPartialChange, ForumThreadListUiState> =
        ForumThreadListPartialChangeProducer(ForumThreadListType.Good)
}

internal data class ForumPageMetadata(
    val forumRuleTitle: String?,
    val goodClassifies: List<ImmutableHolder<Classify>>,
)

internal suspend fun fetchForumListPage(
    query: ForumListQuery,
    cursor: ForumPagingCursor,
): PagingPage<ForumPagingCursor, ThreadItemData, ForumPageMetadata> {
    return if (cursor.remainingIds.isNotEmpty()) {
        val response = FrsPageRepository.threadList(
            query.forumId, query.forumName, cursor.page, query.requestBatchSort,
            cursor.batch.joinToString(",")
        ).first()
        val data = response.data_ ?: throw TiebaUnknownException
        val next = cursor.consumeBatch()
        PagingPage(
            next,
            data.thread_list.map { ThreadItemData(it.wrapImmutable()) }.filterNot { it.hidden },
            next.hasMore, cursor.progressedTo(next),
        )
    } else {
        val result = FrsPageRepository.frsPageResult(
            query.forumName, cursor.page + 1, if (cursor.page == 0) 1 else 2,
            query.requestSort, query.requestClassify
        ).first()
        val data = result.response.data_ ?: throw TiebaUnknownException
        val page = data.page ?: throw TiebaUnknownException
        val next = cursor.nextPage(result.rawThreadIds, data.thread_id_list, page.has_more == 1)
        PagingPage(
            next,
            data.thread_list.map { ThreadItemData(it.wrapImmutable()) }.filterNot { it.hidden },
            next.hasMore, cursor.progressedTo(next),
            if (cursor.page == 0) ForumPageMetadata(
                data.forum_rule?.title.takeIf {
                    !query.isGood && data.forum_rule?.has_forum_rule == 1
                },
                (data.forum?.good_classify ?: emptyList()).wrapImmutable(),
            ) else null,
        )
    }
}

internal class ForumThreadListPartialChangeProducer(
    private val type: ForumThreadListType,
    fetchPage: suspend (ForumListQuery, ForumPagingCursor) -> PagingPage<ForumPagingCursor, ThreadItemData, ForumPageMetadata> = ::fetchForumListPage,
    accountSessionVersion: () -> Long = { AccountUtil.sessionGeneration },
) :
    PartialChangeProducer<ForumThreadListUiIntent, ForumThreadListPartialChange, ForumThreadListUiState> {
    private val paging = OwnedPagination<ForumListQuery, ForumPagingCursor, ThreadItemData, ForumPageMetadata>(
        initialCursor = { ForumPagingCursor() },
        fetch = fetchPage,
        itemId = { it.thread.get { id } },
        accountSession = accountSessionVersion,
    )

    private fun query(forumId: Long, forumName: String, sortType: Int, goodClassifyId: Int?) =
        ForumListQuery(forumId, forumName, type == ForumThreadListType.Good, sortType, goodClassifyId)

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun toPartialChangeFlow(intentFlow: Flow<ForumThreadListUiIntent>): Flow<ForumThreadListPartialChange> =
        merge(
            paging.changes(intentFlow.mapNotNull { intent ->
                when (intent) {
                    is ForumThreadListUiIntent.FirstLoad -> PagingAction.Replace(
                        query(intent.forumId, intent.forumName, intent.sortType, intent.goodClassifyId)
                    )
                    is ForumThreadListUiIntent.Refresh -> PagingAction.Replace(
                        query(intent.forumId, intent.forumName, intent.sortType, intent.goodClassifyId)
                    )
                    ForumThreadListUiIntent.SessionChanged -> PagingAction.SessionChanged
                    is ForumThreadListUiIntent.LoadMore -> PagingAction.More(intent.manual)
                    else -> null
                }
            }).map { ForumThreadListPartialChange.Paging(it) },
            intentFlow.filterIsInstance<ForumThreadListUiIntent.Agree>()
                .flatMapConcat { it.producePartialChange() },
        )

    private fun ForumThreadListUiIntent.Agree.producePartialChange(): Flow<ForumThreadListPartialChange.Agree> =
        TiebaApi.getInstance().opAgreeFlow(
            threadId.toString(),
            postId.toString(),
            hasAgree,
            objType = 3
        ).map<AgreeBean, ForumThreadListPartialChange.Agree> {
            ForumThreadListPartialChange.Agree.Success(
                threadId,
                hasAgree xor 1
            )
        }
            .catch {
                emit(
                    ForumThreadListPartialChange.Agree.Failure(
                        threadId,
                        postId,
                        hasAgree,
                        it
                    )
                )
            }
            .onStart { emit(ForumThreadListPartialChange.Agree.Start(threadId, hasAgree xor 1)) }
}

sealed interface ForumThreadListUiIntent : UiIntent {
    data class FirstLoad(
        val forumName: String,
        val sortType: Int = -1,
        val goodClassifyId: Int? = null,
        val forumId: Long = 0,
    ) : ForumThreadListUiIntent

    data class Refresh(
        val forumName: String,
        val sortType: Int = -1,
        val goodClassifyId: Int? = null,
        val forumId: Long = 0,
    ) : ForumThreadListUiIntent

    data object SessionChanged : ForumThreadListUiIntent

    data class LoadMore(val manual: Boolean = false) : ForumThreadListUiIntent

    data class Agree(
        val threadId: Long,
        val postId: Long,
        val hasAgree: Int
    ) : ForumThreadListUiIntent
}

sealed interface ForumThreadListPartialChange : PartialChange<ForumThreadListUiState> {
    internal data class Paging(
        val owned: OwnedPagingChange<ForumListQuery, ForumPagingCursor, ThreadItemData, ForumPageMetadata>,
    ) : ForumThreadListPartialChange {
        fun failureEvent(): UiEvent? = owned.ifCurrent<UiEvent?>(null) {
            val change = owned.change
            if (change is PagingChange.Failure) ForumThreadListUiEvent.LoadFailure(change.error, owned)
            else null
        }

        private fun PagingChange.Success<ForumListQuery, ForumPagingCursor, ThreadItemData, ForumPageMetadata>.applyTo(
            oldState: ForumThreadListUiState,
        ): ForumThreadListUiState = oldState.copy(
            isRefreshing = false,
            isLoadingMore = false,
            forumRuleTitle = if (replacing) metadata?.forumRuleTitle else oldState.forumRuleTitle,
            threadList = (if (replacing) items else oldState.threadList + items).distinctById(),
            threadListIds = cursor.remainingIds.toImmutableList(),
            goodClassifies = metadata?.goodClassifies?.toImmutableList() ?: oldState.goodClassifies,
            goodClassifyId = query.requestClassify,
            currentPage = cursor.page,
            hasMore = hasMore,
            manualContinue = manualContinue,
        )

        override fun reduce(oldState: ForumThreadListUiState): ForumThreadListUiState = owned.ifCurrent(oldState) {
            val state = when (val change = owned.change) {
                is PagingChange.Start -> (if (change.clearList) ForumThreadListUiState() else oldState).copy(
                    isRefreshing = change.replacing, isLoadingMore = !change.replacing
                )
                is PagingChange.Success -> change.applyTo(oldState)
                is PagingChange.Failure -> (change.progress?.applyTo(oldState) ?: oldState).copy(
                    isRefreshing = false, isLoadingMore = false
                )
            }
            owned.applied()
            state
        }
    }

    sealed class Agree private constructor() : ForumThreadListPartialChange {
        private fun List<ThreadItemData>.updateAgreeStatus(
            threadId: Long,
            hasAgree: Int,
        ): ImmutableList<ThreadItemData> {
            return map { data ->
                val (thread) = data
                if (thread.get { id } == threadId) {
                    ThreadItemData(thread.getImmutable { updateAgreeStatus(hasAgree) })
                } else data
            }.toImmutableList()
        }

        override fun reduce(oldState: ForumThreadListUiState): ForumThreadListUiState =
            when (this) {
                is Start -> {
                    oldState.copy(
                        threadList = oldState.threadList.updateAgreeStatus(
                            threadId,
                            hasAgree
                        )
                    )
                }

                is Success -> {
                    oldState.copy(
                        threadList = oldState.threadList.updateAgreeStatus(
                            threadId,
                            hasAgree
                        )
                    )
                }

                is Failure -> {
                    oldState.copy(
                        threadList = oldState.threadList.updateAgreeStatus(
                            threadId,
                            hasAgree
                        )
                    )
                }
            }

        data class Start(
            val threadId: Long,
            val hasAgree: Int
        ) : Agree()

        data class Success(
            val threadId: Long,
            val hasAgree: Int
        ) : Agree()

        data class Failure(
            val threadId: Long,
            val postId: Long,
            val hasAgree: Int,
            val error: Throwable
        ) : Agree()
    }
}

data class ForumThreadListUiState(
    val isRefreshing: Boolean = false,
    val isLoadingMore: Boolean = false,
    val goodClassifyId: Int? = null,
    val forumRuleTitle: String? = null,
    val threadList: ImmutableList<ThreadItemData> = persistentListOf(),
    val threadListIds: ImmutableList<Long> = persistentListOf(),
    val goodClassifies: ImmutableList<ImmutableHolder<Classify>> = persistentListOf(),
    val currentPage: Int = 1,
    val hasMore: Boolean = true,
    val manualContinue: Boolean = false,
) : UiState

sealed interface ForumThreadListUiEvent : UiEvent {
    internal data class LoadFailure(
        val error: Throwable,
        val owned: OwnedPagingChange<ForumListQuery, ForumPagingCursor, ThreadItemData, ForumPageMetadata>,
    ) : ForumThreadListUiEvent

    data class AgreeFail(
        val threadId: Long,
        val postId: Long,
        val hasAgree: Int,
        val errorCode: Int,
        val errorMsg: String
    ) : ForumThreadListUiEvent

    data class Refresh(
        val isGood: Boolean,
        val sortType: Int
    ) : ForumThreadListUiEvent

    data class BackToTop(
        val isGood: Boolean
    ) : ForumThreadListUiEvent

    data class AddThread(
        val forumName: String,
    ):ForumThreadListUiEvent
}
