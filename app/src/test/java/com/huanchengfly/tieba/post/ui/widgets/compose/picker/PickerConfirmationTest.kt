package com.huanchengfly.tieba.post.ui.widgets.compose.picker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Readiness/session policy tests only; these do not run Compose, touch input or dismissal. */
class PickerConfirmationTest {
    @Test
    fun initializationPendingResetAndScrollingPreventConfirmation() {
        assertFalse(settled(positioned = false))
        assertFalse(settled(isScrolling = true))
        assertFalse(settled(selectedIndex = 4))
        assertFalse(settled(offset = 8))
        assertTrue(settled())
    }

    @Test
    fun actualCyclicPositionMustMatchTheDeliveredSelection() {
        for (turn in listOf(0, 1, 1000)) {
            assertTrue(settled(index = turn * 60 + 3, selectedIndex = 3))
            assertFalse(settled(index = turn * 60 + 4, selectedIndex = 3))
        }
        // One-pixel cyclic tolerance is unchanged; an unsnapped wheel is not ready.
        assertTrue(settled(offset = 15))
        assertTrue(settled(offset = 17))
        assertFalse(settled(offset = 14))
        assertFalse(settled(offset = 18))
    }

    @Test
    fun finitePeriodMustBeExactlyAlignedAtTheSelectedEnd() {
        for (selected in 0..1) {
            assertTrue(settled(size = 2, index = selected, selectedIndex = selected,
                offset = 0, targetOffset = 0, cyclic = false))
            for (offset in listOf(1, 15, 16, 17, 31)) {
                assertFalse(settled(size = 2, index = selected, selectedIndex = selected,
                    offset = offset, targetOffset = 0, cyclic = false))
            }
        }
        assertFalse(settled(size = 2, index = 1, selectedIndex = 0,
            offset = 0, targetOffset = 0, cyclic = false))
    }

    @Test
    fun emptyChangedAndInvalidIndexInputsFailClosed() {
        assertFalse(settled(size = 0))
        assertFalse(settled(index = -1, selectedIndex = -1))
        assertFalse(settled(index = Int.MAX_VALUE, selectedIndex = Int.MAX_VALUE % 60))
        assertFalse(settled(selectedIndex = 60))
        assertFalse(settled(size = 2, index = 2, selectedIndex = 2, cyclic = false))
        assertFalse(settled(size = 2, index = 3, selectedIndex = 1, cyclic = false))
        // A list-size replacement cannot confirm the old selected model.
        assertFalse(settled(size = 2, selectedIndex = 3))
    }

    @Test
    fun staleEnabledClickRechecksTheCurrentReadinessWithoutClosingSession() {
        val session = PickerEditSession()
        assertTrue(settled()) // The earlier UI frame enabled the button.
        assertFalse(session.confirm(settled(isScrolling = true)))
        assertTrue(session.isOpen)
        assertFalse(session.confirm(settled(index = 4)))
        assertTrue(session.isOpen)
        assertTrue(session.confirm(settled(index = 4, selectedIndex = 4)))
        assertFalse(session.isOpen)
    }

    @Test
    fun acceptedConfirmationClosesBeforeCallbacksAndRejectsRepeatedSubmission() {
        val session = PickerEditSession()
        var saves = 0
        var previews = 0
        if (session.isOpen) previews++
        if (session.confirm(settled())) {
            assertFalse(session.isOpen)
            // A reentrant or repeated Confirm cannot invoke the save callback again.
            assertFalse(session.confirm(settled()))
            saves++
        }
        if (session.confirm(settled())) saves++
        if (session.isOpen) previews++
        assertEquals(1, saves)
        assertEquals(1, previews)
        assertFalse(session.cancel())
    }

    @Test
    fun explicitCancelClosesBeforeCallbackAndFreshSessionStartsOpen() {
        val canceled = PickerEditSession()
        var cancels = 0
        if (canceled.cancel()) {
            assertFalse(canceled.isOpen)
            assertFalse(canceled.cancel())
            cancels++
        }
        if (canceled.cancel()) cancels++ // Later dismissal notification is idempotent.
        assertEquals(1, cancels)
        assertFalse(canceled.confirm(settled()))
        val reopened = PickerEditSession()
        assertTrue(reopened.isOpen)
        assertTrue(reopened.confirm(settled()))
    }

    private fun settled(
        positioned: Boolean = true,
        isScrolling: Boolean = false,
        index: Int = 3,
        offset: Int = 16,
        size: Int = 60,
        selectedIndex: Int = 3,
        targetOffset: Int = 16,
        cyclic: Boolean = true
    ): Boolean = isPickerSettled(positioned, isScrolling, index, offset, size,
        selectedIndex, targetOffset, cyclic)
}
