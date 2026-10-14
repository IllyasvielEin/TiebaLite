package com.huanchengfly.tieba.post.ui.page.forum.generaltablist

import androidx.compose.runtime.Stable
import com.huanchengfly.tieba.post.api.TiebaApi
import com.huanchengfly.tieba.post.api.models.AgreeBean
import com.huanchengfly.tieba.post.api.models.protos.FrsTabInfo
import com.huanchengfly.tieba.post.api.models.protos.updateAgreeStatus
import com.huanchengfly.tieba.post.api.retrofit.exception.TiebaUnknownException
import com.huanchengfly.tieba.post.api.retrofit.exception.getErrorCode
import com.huanchengfly.tieba.post.api.retrofit.exception.getErrorMessage
import com.huanchengfly.tieba.post.arch.BaseViewModel
import com.huanchengfly.tieba.post.arch.PartialChange
import com.huanchengfly.tieba.post.arch.PartialChangeProducer
import com.huanchengfly.tieba.post.arch.UiEvent
import com.huanchengfly.tieba.post.arch.UiIntent
import com.huanchengfly.tieba.post.arch.UiState
import com.huanchengfly.tieba.post.arch.wrapImmutable
import com.huanchengfly.tieba.post.repository.GeneralTabListRepository
import com.huanchengfly.tieba.post.ui.models.ThreadItemData
import com.huanchengfly.tieba.post.ui.models.distinctById
import com.huanchengfly.tieba.post.ui.page.forum.paging.GeneralListQuery
import com.huanchengfly.tieba.post.ui.page.forum.paging.GeneralPagingCursor
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

@Stable
@HiltViewModel
class GeneralTabListViewModel @Inject constructor() :
    BaseViewModel<GeneralTabListUiIntent, GeneralTabListPartialChange, GeneralTabListUiState, GeneralTabListUiEvent>() {
    override fun createInitialState(): GeneralTabListUiState = GeneralTabListUiState()

    override fun createPartialChangeProducer(): PartialChangeProducer<GeneralTabListUiIntent, GeneralTabListPartialChange, GeneralTabListUiState> =
        GeneralTabListPartialChangeProducer()

    override fun dispatchEvent(partialChange: GeneralTabListPartialChange): UiEvent? =
        when (partialChange) {
            is GeneralTabListPartialChange.Paging -> partialChange.failureEvent()
            is GeneralTabListPartialChange.Agree.Failure -> {
                GeneralTabListUiEvent.AgreeFail(
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

internal suspend fun fetchGeneralListPage(
    query: GeneralListQuery,
    cursor: GeneralPagingCursor,
): PagingPage<GeneralPagingCursor, ThreadItemData, Unit> {
    val result = GeneralTabListRepository.generalTabListResult(
        query.forumId, query.forumName, query.tabId, query.tabType, query.tabName,
        query.isGeneralTab, cursor.page + 1, query.sortType, cursor.lastThreadId, query.isDefaultNavTab
    ).first()
    val data = result.response.data_ ?: throw TiebaUnknownException
    val next = cursor.nextPage(result.rawLastThreadId)
    return PagingPage(
        next,
        data.general_list.map { ThreadItemData(it.wrapImmutable()) }.filterNot { it.hidden },
        data.has_more == 1, cursor.progressedTo(next),
    )
}

internal class GeneralTabListPartialChangeProducer(
    fetchPage: suspend (GeneralListQuery, GeneralPagingCursor) -> PagingPage<GeneralPagingCursor, ThreadItemData, Unit> = ::fetchGeneralListPage,
    accountSessionVersion: () -> Long = { AccountUtil.sessionGeneration },
) :
    PartialChangeProducer<GeneralTabListUiIntent, GeneralTabListPartialChange, GeneralTabListUiState> {
    private val paging = OwnedPagination<GeneralListQuery, GeneralPagingCursor, ThreadItemData, Unit>(
        initialCursor = { GeneralPagingCursor() },
        fetch = fetchPage,
        itemId = { it.thread.get { id } },
        accountSession = accountSessionVersion,
    )

    private fun query(forumId: Long, forumName: String, tab: FrsTabInfo, sortType: Int) = GeneralListQuery(
        forumId, forumName, tab.tabId, tab.tabType, tab.tabName, tab.isGeneralTab, tab.isDefault, sortType
    )

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun toPartialChangeFlow(intentFlow: Flow<GeneralTabListUiIntent>): Flow<GeneralTabListPartialChange> =
        merge(
            paging.changes(intentFlow.mapNotNull { intent ->
                when (intent) {
                    is GeneralTabListUiIntent.FirstLoad -> PagingAction.Replace(
                        query(intent.forumId, intent.forumName, intent.navTabInfo, intent.sortType)
                    )
                    is GeneralTabListUiIntent.Refresh -> PagingAction.Replace(
                        query(intent.forumId, intent.forumName, intent.navTabInfo, intent.sortType)
                    )
                    GeneralTabListUiIntent.SessionChanged -> PagingAction.SessionChanged
                    is GeneralTabListUiIntent.LoadMore -> PagingAction.More(intent.manual)
                    else -> null
                }
            }).map { GeneralTabListPartialChange.Paging(it) },
            intentFlow.filterIsInstance<GeneralTabListUiIntent.Agree>()
                .flatMapConcat { it.producePartialChange() },
        )

    private fun GeneralTabListUiIntent.Agree.producePartialChange(): Flow<GeneralTabListPartialChange.Agree> =
        TiebaApi.getInstance().opAgreeFlow(
            threadId.toString(),
            postId.toString(),
            hasAgree,
            objType = 3
        ).map<AgreeBean, GeneralTabListPartialChange.Agree> {
            GeneralTabListPartialChange.Agree.Success(
                threadId,
                hasAgree xor 1
            )
        }
            .catch {
                emit(
                    GeneralTabListPartialChange.Agree.Failure(
                        threadId,
                        postId,
                        hasAgree,
                        it
                    )
                )
            }
            .onStart { emit(GeneralTabListPartialChange.Agree.Start(threadId, hasAgree xor 1)) }
}

sealed interface GeneralTabListUiIntent : UiIntent {
    data class FirstLoad(
        val forumId: Long,
        val forumName: String,
        val navTabInfo: FrsTabInfo,
        val sortType: Int = -1,
    ) : GeneralTabListUiIntent

    data class Refresh(
        val forumId: Long,
        val forumName: String,
        val navTabInfo: FrsTabInfo,
        val sortType: Int = -1,
    ) : GeneralTabListUiIntent

    data object SessionChanged : GeneralTabListUiIntent

    data class LoadMore(val manual: Boolean = false) : GeneralTabListUiIntent

    data class Agree(
        val threadId: Long,
        val postId: Long,
        val hasAgree: Int
    ) : GeneralTabListUiIntent
}

// A class permits internal variants without exposing pagination ownership in the public API.
sealed class GeneralTabListPartialChange : PartialChange<GeneralTabListUiState> {
    internal data class Paging(
        val owned: OwnedPagingChange<GeneralListQuery, GeneralPagingCursor, ThreadItemData, Unit>,
    ) : GeneralTabListPartialChange() {
        fun failureEvent(): UiEvent? = owned.ifCurrent<UiEvent?>(null) {
            val change = owned.change
            if (change is PagingChange.Failure) GeneralTabListUiEvent.LoadFailure(change.error, owned)
            else null
        }

        private fun PagingChange.Success<GeneralListQuery, GeneralPagingCursor, ThreadItemData, Unit>.applyTo(
            oldState: GeneralTabListUiState,
        ): GeneralTabListUiState = oldState.copy(
            isRefreshing = false,
            isLoadingMore = false,
            threadList = (if (replacing) items else oldState.threadList + items).distinctById(),
            hasMore = hasMore,
            currentPage = cursor.page,
            lastThreadId = cursor.lastThreadId,
            sortType = query.sortType,
            manualContinue = manualContinue,
        )

        override fun reduce(oldState: GeneralTabListUiState): GeneralTabListUiState = owned.ifCurrent(oldState) {
            val state = when (val change = owned.change) {
                is PagingChange.Start -> (if (change.clearList) GeneralTabListUiState() else oldState).copy(
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

    sealed class Agree private constructor() : GeneralTabListPartialChange() {
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

        override fun reduce(oldState: GeneralTabListUiState): GeneralTabListUiState =
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

data class GeneralTabListUiState(
    val isRefreshing: Boolean = false,
    val isLoadingMore: Boolean = false,
    val threadList: ImmutableList<ThreadItemData> = persistentListOf(),
    val currentPage: Int = 1,
    val hasMore: Boolean = true,
    val lastThreadId: Long = 0,
    val sortType: Int = -1,
    val manualContinue: Boolean = false,
) : UiState

// A class permits internal variants without exposing pagination ownership in the public API.
sealed class GeneralTabListUiEvent : UiEvent {
    internal data class LoadFailure(
        val error: Throwable,
        val owned: OwnedPagingChange<GeneralListQuery, GeneralPagingCursor, ThreadItemData, Unit>,
    ) : GeneralTabListUiEvent()

    data object BackToTop : GeneralTabListUiEvent()
    data class Refresh(val sortType: Int = -1) : GeneralTabListUiEvent()

    data class AgreeFail(
        val threadId: Long,
        val postId: Long,
        val hasAgree: Int,
        val errorCode: Int,
        val errorMsg: String
    ) : GeneralTabListUiEvent()
}
