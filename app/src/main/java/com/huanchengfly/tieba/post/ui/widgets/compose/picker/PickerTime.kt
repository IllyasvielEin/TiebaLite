package com.huanchengfly.tieba.post.ui.widgets.compose.picker

enum class TimesOfDay(val string: String) {
    AM("AM"), PM("PM")
}

/** An immutable picker value. Invalid input or out-of-range values throw [IllegalArgumentException]. */
data class PickerTime(
    val hours: Int,
    val minutes: Int,
    val timesOfDay: TimesOfDay? = null
) {
    init {
        require(hours in if (timesOfDay == null) 0..23 else 1..12) { "Invalid hour" }
        require(minutes in 0..59) { "Invalid minute" }
    }

    companion object {
        // Unicode decimal digits retain times saved by the old default-locale formatter.
        private val timePattern = Regex(
            "([\\p{Nd}]{1,2}):([\\p{Nd}]{1,2})(?:\\s+(AM|PM))?",
            RegexOption.IGNORE_CASE
        )

        fun parse(string: String, is24TimeFormat: Boolean): PickerTime {
            val match = requireNotNull(timePattern.matchEntire(string.trim())) { "Invalid time" }
            val sourceHour = match.groupValues[1].toInt()
            val minutes = match.groupValues[2].toInt()
            val suffix = match.groupValues[3]
            require(minutes in 0..59) { "Invalid minute" }

            val hourOfDay = if (suffix.isEmpty()) {
                require(sourceHour in 0..23) { "Invalid hour" }
                sourceHour
            } else {
                require(sourceHour in 1..12) { "Invalid hour" }
                sourceHour % 12 + if (suffix.equals(TimesOfDay.PM.string, ignoreCase = true)) 12 else 0
            }

            return if (is24TimeFormat) {
                PickerTime(hourOfDay, minutes)
            } else {
                PickerTime(
                    hours = (hourOfDay % 12).takeUnless { it == 0 } ?: 12,
                    minutes = minutes,
                    timesOfDay = if (hourOfDay < 12) TimesOfDay.AM else TimesOfDay.PM
                )
            }
        }
    }

    /** Stable ASCII persistence/callback shape, independent of the default display locale. */
    override fun toString(): String =
        "${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}" +
            timesOfDay?.let { " ${it.string}" }.orEmpty()
}
