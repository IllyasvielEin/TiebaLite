package com.huanchengfly.tieba.post.ui.widgets.compose.picker

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlin.math.abs

/** Selection bookkeeping shared by cyclic wheels and the finite AM/PM column. */
internal class PickerSelection<T>(private val items: List<T>, selectedItem: T?) {
    private var requestedItem = selectedItem
    private var settledItem = items.getOrNull(selectedIndex(items, selectedItem))

    /** A parent echo of the item just delivered must not recenter the wheel. */
    fun request(selectedItem: T?): Int? {
        if (selectedItem == requestedItem) return null
        requestedItem = selectedItem
        val index = selectedIndex(items, selectedItem)
        val item = items.getOrNull(index)
        if (item == settledItem) return null
        settledItem = item
        return index.takeIf { items.isNotEmpty() }
    }

    /** Called after settling, even when the item was already perfectly aligned. */
    fun settle(index: Int): T? {
        val item = items.getOrNull(index) ?: return null
        if (item == settledItem) return null
        settledItem = item
        return item
    }
}

internal fun <T> selectedIndex(items: List<T>, selectedItem: T?): Int =
    items.indexOf(selectedItem).coerceAtLeast(0)

internal fun initialWheelIndex(size: Int, selectedIndex: Int): Int {
    if (size == 0) return 0
    val center = Int.MAX_VALUE / 2
    return center - center % size + selectedIndex.coerceIn(0, size - 1)
}

internal fun nearestWheelIndex(currentIndex: Int, size: Int, selectedIndex: Int): Int {
    if (size == 0) return 0
    val base = currentIndex.toLong() - currentIndex % size + selectedIndex.coerceIn(0, size - 1)
    return listOf(base - size, base, base + size)
        .filter { it in 0 until Int.MAX_VALUE.toLong() }
        .minBy { abs(it - currentIndex) }
        .toInt()
}

internal fun isPickerSettled(
    positioned: Boolean,
    isScrolling: Boolean,
    index: Int,
    offset: Int,
    size: Int,
    selectedIndex: Int,
    targetOffset: Int,
    cyclic: Boolean
): Boolean = positioned && !isScrolling && size > 0 &&
    selectedIndex in 0 until size &&
    index in 0 until (if (cyclic) Int.MAX_VALUE else size) &&
    (if (cyclic) index % size else index) == selectedIndex &&
    abs(offset - targetOffset) <= if (cyclic) 1 else 0

/** A session closes before its accepted confirmation callback, even across repeated taps. */
internal class PickerEditSession {
    var isOpen = true
        private set

    fun confirm(isReady: Boolean): Boolean {
        if (!isOpen || !isReady) return false
        isOpen = false
        return true
    }

    fun cancel(): Boolean {
        if (!isOpen) return false
        isOpen = false
        return true
    }
}

/** Kept independent of Compose so interrupted and cancelled scrolls can be tested on the JVM. */
internal interface PickerScrollPosition {
    val isScrolling: Boolean
    val offset: Int
    suspend fun animateBy(delta: Float)
}

internal suspend fun runPickerScroll(action: suspend () -> Unit): Boolean {
    try {
        action()
        currentCoroutineContext().ensureActive()
        return true
    } catch (_: CancellationException) {
        // A new user drag cancels only the scroll mutation. Disposal cancels the owner too.
        currentCoroutineContext().ensureActive()
        return false
    }
}

internal suspend fun settlePicker(
    position: PickerScrollPosition,
    targetOffset: Int,
    finiteItemHeight: Int? = null
): Boolean {
    val delta = if (finiteItemHeight != null && position.offset > finiteItemHeight / 2) {
        finiteItemHeight - position.offset
    } else targetOffset - position.offset
    if (!runPickerScroll {
            // Finite columns must cross even a one-pixel next-item boundary before delivery.
            if (delta != 0 && (finiteItemHeight != null || abs(delta) > 1)) {
                position.animateBy(delta.toFloat())
            }
        }) return false
    return !position.isScrolling && abs(position.offset - targetOffset) <= 1
}
