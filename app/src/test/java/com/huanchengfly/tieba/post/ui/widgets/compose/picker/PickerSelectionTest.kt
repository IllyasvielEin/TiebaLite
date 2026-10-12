package com.huanchengfly.tieba.post.ui.widgets.compose.picker

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pure selection/coroutine policy tests; these do not simulate Android layout or touch input. */
class PickerSelectionTest {
    @Test
    fun initialPositionIsSilentAndAlignedChangesEmitOnlyOnce() = runBlocking {
        val policy = PickerSelection(listOf(0, 1, 2), 0)
        val position = FakePosition(offset = 16)
        assertTrue(settlePicker(position, 16))
        assertEquals(0, position.animations)
        assertNull(policy.settle(0))
        assertEquals(1, policy.settle(1))
        assertNull(policy.settle(1))
        assertEquals(2, policy.settle(2))
        assertNull(policy.settle(2))
    }

    @Test
    fun parentEchoKeepsTheExistingCyclicPosition() {
        val policy = PickerSelection(listOf(0, 1, 2), 0)
        assertEquals(1, policy.settle(1))
        assertNull(policy.request(1))
        assertNull(policy.request(1))
        // External selection changes reset, but their resulting position is silent.
        assertEquals(2, policy.request(2))
        assertNull(policy.settle(2))
        assertEquals(0, policy.settle(0))
    }

    @Test
    fun emptyListsUnknownSelectionsAndNewDataAreSafe() {
        val empty = PickerSelection(emptyList<Int>(), 5)
        assertNull(empty.request(6))
        assertNull(empty.settle(0))
        assertEquals(0, selectedIndex(emptyList<Int>(), 5))
        assertEquals(0, initialWheelIndex(0, -1))
        assertEquals(0, nearestWheelIndex(0, 0, -1))
        val newData = PickerSelection(listOf(10, 20), 99)
        assertNull(newData.settle(0))
        assertEquals(20, newData.settle(1))
        val replacedData = PickerSelection(listOf(30, 40), 40)
        assertNull(replacedData.settle(1))
        assertEquals(30, replacedData.settle(0))
    }

    @Test
    fun cyclicIndicesRemainValidAndResetToTheNearestEquivalentItem() {
        val initial = initialWheelIndex(60, 59)
        assertEquals(59, initial % 60)
        assertTrue(initial > 60)
        assertEquals(initial, nearestWheelIndex(initial, 60, 59))
        assertEquals(initial + 1, nearestWheelIndex(initial, 60, 0))
        assertEquals(0, nearestWheelIndex(0, 60, 0))
        val last = nearestWheelIndex(Int.MAX_VALUE - 1, 60, 59)
        assertTrue(last in 0 until Int.MAX_VALUE)
        assertEquals(59, last % 60)
        assertEquals(0, selectedIndex(listOf(10, 20), 99))
    }

    @Test
    fun interruptedSnapCanSettleOnTheNextIdleObservation() = runBlocking {
        var interrupt = true
        val position = FakePosition(offset = 5, animate = {
            if (interrupt) {
                interrupt = false
                throw CancellationException("new user drag")
            }
        })
        assertFalse(settlePicker(position, 16))
        assertTrue(settlePicker(position, 16))
        assertEquals(2, position.animations)
        assertEquals(16, position.offset)
    }

    @Test
    fun ownerDisposalDuringSnapPropagatesCancellationWithoutDelivery() = runBlocking {
        val started = CompletableDeferred<Unit>()
        var delivered = false
        val position = FakePosition(offset = 5, animate = {
            started.complete(Unit)
            awaitCancellation()
        })
        val owner = launch(start = CoroutineStart.UNDISPATCHED) {
            if (settlePicker(position, 16)) delivered = true
        }
        started.await()
        owner.cancelAndJoin()
        assertTrue(owner.isCancelled)
        assertFalse(delivered)
    }

    @Test
    fun aNewDragStillInProgressCannotDeliverASnapResult() = runBlocking {
        val position = FakePosition(offset = 16)
        position.isScrolling = true
        assertFalse(settlePicker(position, 16))
        position.isScrolling = false
        assertTrue(settlePicker(position, 16))
    }

    @Test
    fun finitePeriodColumnRoundsToTheNearestEnd() = runBlocking {
        val policy = PickerSelection(TimesOfDay.entries, TimesOfDay.AM)
        val nearAm = FakePosition(offset = 10, finiteHeight = 32)
        assertTrue(settlePicker(nearAm, 0, finiteItemHeight = 32))
        assertEquals(0, nearAm.index)
        assertNull(policy.settle(nearAm.index))
        val nearPm = FakePosition(offset = 22, finiteHeight = 32)
        assertTrue(settlePicker(nearPm, 0, finiteItemHeight = 32))
        assertEquals(1, nearPm.index)
        assertEquals(TimesOfDay.PM, policy.settle(nearPm.index))
        assertNull(policy.settle(nearPm.index))
    }

    @Test
    fun finiteOnePixelBoundariesAndMidpointNormalizeBeforeDelivery() = runBlocking {
        for (offset in listOf(0, 1, 15, 16, 17, 31)) {
            val position = FakePosition(offset = offset, finiteHeight = 32)
            assertTrue("offset=$offset", settlePicker(position, 0, finiteItemHeight = 32))
            assertEquals("offset=$offset", if (offset <= 16) 0 else 1, position.index)
            assertEquals("offset=$offset", 0, position.offset)
            assertEquals("offset=$offset", if (offset == 0) 0 else 1, position.animations)
        }
    }

    private class FakePosition(
        override var offset: Int,
        private val finiteHeight: Int? = null,
        private val animate: suspend () -> Unit = {}
    ) : PickerScrollPosition {
        override var isScrolling = false
        var animations = 0
        var index = 0
        override suspend fun animateBy(delta: Float) {
            animations++
            animate()
            offset += delta.toInt()
            finiteHeight?.let { height ->
                if (offset >= height) {
                    index++
                    offset -= height
                }
            }
        }
    }
}
