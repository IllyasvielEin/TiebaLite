package com.huanchengfly.tieba.post.ui.widgets.compose.picker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.util.Locale

class PickerTimeTest {
    @Test
    fun midnightAndNoonUseTheCorrectPeriod() {
        assertEquals("12:00 AM", PickerTime.parse("00:00", false).toString())
        assertEquals("12:00 PM", PickerTime.parse("12:00", false).toString())
        assertEquals("00:00", PickerTime.parse("12:00 AM", true).toString())
        assertEquals("12:00", PickerTime.parse("12:00 PM", true).toString())
        assertEquals("13:00", PickerTime.parse("01:00 PM", true).toString())
    }

    @Test
    fun allHoursRoundTripBetweenBothFormatsAtMinuteBoundaries() {
        for (hour in 0..23) {
            for (minute in listOf(0, 59)) {
                val original = PickerTime(hour, minute)
                val twelveHour = PickerTime.parse(original.toString(), false)
                assertEquals(if (hour < 12) TimesOfDay.AM else TimesOfDay.PM, twelveHour.timesOfDay)
                assertEquals((hour % 12).takeUnless { it == 0 } ?: 12, twelveHour.hours)
                assertEquals(original, PickerTime.parse(twelveHour.toString(), true))
                assertEquals(original, PickerTime.parse(original.toString(), true))
                assertEquals(twelveHour, PickerTime.parse(twelveHour.toString(), false))
            }
        }
    }

    @Test
    fun legacySpacingAndCaseNormalizeConsistently() {
        assertEquals("00:03", PickerTime.parse(" 12:3 am ", true).toString())
        assertEquals("12:59", PickerTime.parse("12:59 pM", true).toString())
        assertEquals("07:03", PickerTime.parse("7:3", true).toString())
        assertEquals("01:59 PM", PickerTime.parse("13:59", false).toString())
    }

    @Test
    fun persistedStringsStayAsciiWhenTheDefaultLocaleChanges() {
        val originalLocale = Locale.getDefault()
        try {
            for (locale in listOf(Locale.US, Locale.forLanguageTag("ar"), Locale.forLanguageTag("fa"), Locale.forLanguageTag("tr"))) {
                Locale.setDefault(locale)
                assertEquals("07:03", PickerTime(7, 3).toString())
                assertEquals("12:59 PM", PickerTime(12, 59, TimesOfDay.PM).toString())
                assertEquals("13:59", PickerTime.parse("01:59 pm", true).toString())
            }
        } finally {
            Locale.setDefault(originalLocale)
        }
    }

    @Test
    fun oldLocalizedDecimalDigitsCanStillBeRead() {
        assertEquals("07:03", PickerTime.parse("٠٧:٠٣", true).toString())
        assertEquals("12:59", PickerTime.parse("۱۲:۵۹ PM", true).toString())
    }

    @Test
    fun invalidInputIsRejectedRatherThanBecomingMidnight() {
        for (input in listOf("", "noon", "12", "12:00:00", "12:00 XM", "-1:00", "24:00", "01:60", "00:00 AM", "13:00 PM", "123:00")) {
            for (is24 in listOf(true, false)) {
                assertThrows("Input: $input", IllegalArgumentException::class.java) {
                    PickerTime.parse(input, is24)
                }
            }
        }
    }

    @Test
    fun immutableCopiesCannotIntroduceInvalidValues() {
        val value = PickerTime(23, 59)
        assertThrows(IllegalArgumentException::class.java) { value.copy(hours = 24) }
        assertThrows(IllegalArgumentException::class.java) { value.copy(minutes = -1) }
        assertThrows(IllegalArgumentException::class.java) { PickerTime(0, 0, TimesOfDay.AM) }
        assertThrows(IllegalArgumentException::class.java) { PickerTime(13, 0, TimesOfDay.PM) }
        assertEquals(PickerTime(23, 0), value.copy(minutes = 0))
    }
}
