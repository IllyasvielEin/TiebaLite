package com.huanchengfly.tieba.post.ui.widgets.compose.picker

import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.material.Divider
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.flow.collect

@Composable
fun <T> WheelPicker(
    modifier: Modifier = Modifier,
    items: List<T> = emptyList(),
    selectedItem: T? = null,
    itemHeight: Dp = 32.dp,
    divider: NumberPickerDivider = NumberPickerDivider(),
    itemStyles: ItemStyles = ItemStyles(),
    onItemChanged: (T) -> Unit = {},
    itemToString: (T) -> String = { it.toString() }
) {
    PickerColumn(
        modifier = modifier,
        items = items,
        selectedItem = selectedItem,
        itemHeight = itemHeight,
        divider = divider,
        itemStyles = itemStyles,
        onItemChanged = onItemChanged,
        itemToString = itemToString,
        cyclic = true
    )
}

/** Shared lifecycle owner for cyclic number wheels and the finite period column. */
@Composable
internal fun <T> PickerColumn(
    modifier: Modifier,
    items: List<T>,
    selectedItem: T?,
    itemHeight: Dp,
    divider: NumberPickerDivider,
    itemStyles: ItemStyles,
    onItemChanged: (T) -> Unit,
    itemToString: (T) -> String,
    cyclic: Boolean,
    columnState: PickerColumnState = rememberPickerColumnState(
        if (cyclic) initialWheelIndex(items.size, selectedIndex(items, selectedItem))
        else selectedIndex(items, selectedItem)
    )
) {
    val currentOnItemChanged by rememberUpdatedState(onItemChanged)
    val currentSelectedItem by rememberUpdatedState(selectedItem)
    var listHeightInPixels by remember { mutableStateOf(0) }
    val density = LocalDensity.current
    val itemHeightInPixels = with(density) { itemHeight.roundToPx() }
    val listState = columnState.listState

    LaunchedEffect(listState, items, cyclic, itemHeightInPixels, listHeightInPixels) {
        columnState.positioned = false
        if (items.isEmpty() || itemHeightInPixels <= 0 || listHeightInPixels <= 0) return@LaunchedEffect
        val targetOffset = if (cyclic) itemHeightInPixels / 2 else 0
        val selection = PickerSelection(items, currentSelectedItem)
        val requestedIndex = selectedIndex(items, currentSelectedItem)
        val initialIndex = if (cyclic) {
            if (listState.firstVisibleItemIndex < items.size) initialWheelIndex(items.size, requestedIndex)
            else nearestWheelIndex(listState.firstVisibleItemIndex, items.size, requestedIndex)
        } else requestedIndex
        // Positioning an initial/external selection is silent, including restored list state.
        columnState.positioned = runPickerScroll { listState.scrollToItem(initialIndex, targetOffset) }
        val position = object : PickerScrollPosition {
            override val isScrolling get() = listState.isScrollInProgress
            override val offset get() = listState.firstVisibleItemScrollOffset
            override suspend fun animateBy(delta: Float) { listState.animateScrollBy(delta) }
        }
        suspend fun resetSelection(index: Int) {
            columnState.positioned = false
            val visibleIndex = if (cyclic) {
                nearestWheelIndex(listState.firstVisibleItemIndex, items.size, index)
            } else index
            columnState.positioned = runPickerScroll { listState.scrollToItem(visibleIndex, targetOffset) }
        }
        // Sequential collect deliberately avoids cancelling a snap on its own scrolling=true.
        snapshotFlow {
            PickerObservation(
                listState.isScrollInProgress,
                listState.firstVisibleItemIndex,
                listState.firstVisibleItemScrollOffset,
                currentSelectedItem
            )
        }.collect { observation ->
            val resetIndex = selection.request(observation.selectedItem)
            if (resetIndex != null) {
                resetSelection(resetIndex)
            } else if (!observation.isScrolling && settlePicker(
                    position, targetOffset, finiteItemHeight = itemHeightInPixels.takeUnless { cyclic }
                )) {
                // External changes during an animation supersede its old callback result.
                val pendingReset = selection.request(currentSelectedItem)
                if (pendingReset != null) {
                    resetSelection(pendingReset)
                } else {
                    val index = if (cyclic) listState.firstVisibleItemIndex % items.size
                        else listState.firstVisibleItemIndex
                    selection.settle(index)?.let { currentOnItemChanged(it) }
                    columnState.positioned = true
                }
            }
        }
    }

    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        if (items.isNotEmpty()) {
            LazyColumn(
                contentPadding = if (cyclic) {
                    PaddingValues(top = with(density) { (listHeightInPixels / 2).toDp() })
                } else PaddingValues(top = itemHeight, bottom = itemHeight),
                state = listState,
                modifier = Modifier
                    .fillMaxWidth(1f)
                    .then(if (cyclic) Modifier else Modifier.height(itemHeight * 3))
                    .onGloballyPositioned {
                        listHeightInPixels = it.size.height
                    }
            ) {
                items(if (cyclic) Int.MAX_VALUE else items.size) { i ->
                    val index = if (cyclic) i % items.size else i
                    val selected by remember(listState, i) {
                        derivedStateOf { i == listState.firstVisibleItemIndex }
                    }
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .fillMaxWidth(1f)
                            .height(itemHeight)
                    ) {
                        Text(
                            text = itemToString(items[index]),
                            style = if (selected) itemStyles.selectedTextStyle else itemStyles.defaultTextStyle
                        )
                    }
                }
            }
        }
        if (divider.showed) {
            Divider(
                color = divider.color,
                modifier = Modifier
                    .fillMaxWidth(1f)
                    .offset(y = -itemHeight / 2)
                    .offset(x = -divider.indent),
                thickness = divider.thickness,
                startIndent = divider.indent * 2
            )
            Divider(
                color = divider.color, modifier = Modifier
                    .fillMaxWidth(1f)
                    .offset(y = itemHeight / 2)
                    .offset(x = -divider.indent),
                thickness = divider.thickness,
                startIndent = divider.indent * 2
            )
        }
    }
}

internal class PickerColumnState(val listState: LazyListState) {
    var positioned by mutableStateOf(false)

    fun isSettled(size: Int, selectedIndex: Int, itemHeight: Int, cyclic: Boolean): Boolean =
        itemHeight > 0 && isPickerSettled(
            positioned, listState.isScrollInProgress, listState.firstVisibleItemIndex,
            listState.firstVisibleItemScrollOffset, size, selectedIndex,
            targetOffset = if (cyclic) itemHeight / 2 else 0, cyclic = cyclic
        )
}

@Composable
internal fun rememberPickerColumnState(initialIndex: Int): PickerColumnState {
    val listState = rememberSaveable(saver = LazyListState.Saver) {
        LazyListState(firstVisibleItemIndex = initialIndex)
    }
    return remember(listState) { PickerColumnState(listState) }
}

private data class PickerObservation<T>(
    val isScrolling: Boolean,
    val index: Int,
    val offset: Int,
    val selectedItem: T?
)

@Immutable
class NumberPickerDivider(
    val showed: Boolean = false,
    val color: Color = Color.Transparent,
    val thickness: Dp = 1.dp,
    val indent: Dp = 0.dp
)

@Immutable
class ItemStyles(
    val defaultTextStyle: TextStyle = TextStyle.Default,
    val selectedTextStyle: TextStyle = TextStyle.Default
)
