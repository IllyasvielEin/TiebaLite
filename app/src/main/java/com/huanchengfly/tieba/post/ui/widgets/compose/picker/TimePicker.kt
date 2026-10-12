package com.huanchengfly.tieba.post.ui.widgets.compose.picker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.ContentAlpha
import androidx.compose.material.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun TimePicker(
    currentTime: String,
    onTimeChanged: (String) -> Unit,
    is24TimeFormat: Boolean,
    modifier: Modifier = Modifier,
    itemHeight: Dp = 32.dp,
    divider: NumberPickerDivider = NumberPickerDivider(),
    itemStyles: ItemStyles = ItemStyles(
        defaultTextStyle = MaterialTheme.typography.body1.copy(
            color = MaterialTheme.colors.onBackground.copy(alpha = ContentAlpha.medium),
            fontWeight = FontWeight.Normal
        ),
        selectedTextStyle = MaterialTheme.typography.h5.copy(
            color = MaterialTheme.colors.onBackground.copy(alpha = ContentAlpha.high),
            fontWeight = FontWeight.Medium
        )
    )
) {

    TimePickerContent(
        currentTime = currentTime,
        onTimeChanged = onTimeChanged,
        is24TimeFormat = is24TimeFormat,
        pickerState = rememberTimePickerState(currentTime, is24TimeFormat),
        modifier = modifier,
        itemHeight = itemHeight,
        divider = divider,
        itemStyles = itemStyles
    )
}

@Composable
internal fun TimePickerContent(
    currentTime: String,
    onTimeChanged: (String) -> Unit,
    is24TimeFormat: Boolean,
    pickerState: TimePickerState,
    modifier: Modifier,
    itemHeight: Dp,
    divider: NumberPickerDivider,
    itemStyles: ItemStyles
) {
    var pickerTime by remember(currentTime, is24TimeFormat) {
        mutableStateOf(
            PickerTime.parse(
                currentTime,
                is24TimeFormat = is24TimeFormat
            )
        )
    }

    val currentOnTimeChanged by rememberUpdatedState(onTimeChanged)
    val displayLocale = LocalConfiguration.current.locales[0]
    val hours = (if (is24TimeFormat) (0..23) else (1..12)).toList()
    val minutes = (0..59).toList()

    Row(horizontalArrangement = Arrangement.Center, modifier = modifier.fillMaxWidth(1f)) {
        PickerColumn(
            cyclic = true,
            columnState = pickerState.hours,
            itemHeight = itemHeight,
            divider = divider,
            itemStyles = itemStyles,
            items = hours,
            selectedItem = pickerTime.hours,
            itemToString = { if (is24TimeFormat) String.format(displayLocale, "%02d", it) else String.format(displayLocale, "%d", it) },
            modifier = Modifier
                .fillMaxHeight(1f)
                .fillMaxWidth(.3f),
            onItemChanged = {
                pickerTime = pickerTime.copy(hours = it)
                currentOnTimeChanged(pickerTime.toString())
            }
        )
        PickerColumn(
            cyclic = true,
            columnState = pickerState.minutes,
            items = minutes,
            selectedItem = pickerTime.minutes,
            itemHeight = itemHeight,
            divider = divider,
            itemStyles = itemStyles,
            itemToString = { String.format(displayLocale, "%02d", it) },
            modifier = Modifier
                .fillMaxHeight(1f)
                .fillMaxWidth(.3f),
            onItemChanged = {
                pickerTime = pickerTime.copy(minutes = it)
                currentOnTimeChanged(pickerTime.toString())
            }

        )
        if (is24TimeFormat.not()) {
            PickerColumn(
                cyclic = false,
                columnState = pickerState.period,
                items = TimesOfDay.entries,
                itemToString = { it.string },
                itemHeight = itemHeight,
                divider = divider,
                itemStyles = itemStyles,
                modifier = Modifier
                    .fillMaxHeight(1f)
                    .fillMaxWidth(.3f),
                selectedItem = pickerTime.timesOfDay!!,
                onItemChanged = {
                    pickerTime = pickerTime.copy(timesOfDay = it)
                    currentOnTimeChanged(pickerTime.toString())
                }
            )
        }
    }
}

@Composable
fun AmPmPicker(
    modifier: Modifier = Modifier,
    selectedItem: TimesOfDay,
    itemHeight: Dp = 32.dp,
    divider: NumberPickerDivider = NumberPickerDivider(showed = true, Color.Black),
    itemStyles: ItemStyles = ItemStyles(),
    onItemChanged: (TimesOfDay) -> Unit = {}
) {
    PickerColumn(
        modifier = modifier,
        items = TimesOfDay.entries,
        selectedItem = selectedItem,
        itemHeight = itemHeight,
        divider = divider,
        itemStyles = itemStyles,
        onItemChanged = onItemChanged,
        itemToString = { it.string },
        cyclic = false
    )
}

internal class TimePickerState(
    val hours: PickerColumnState,
    val minutes: PickerColumnState,
    val period: PickerColumnState
) {
    fun isSettled(time: PickerTime, is24TimeFormat: Boolean, itemHeight: Int): Boolean =
        hours.isSettled(
            size = if (is24TimeFormat) 24 else 12,
            selectedIndex = if (is24TimeFormat) time.hours else time.hours - 1,
            itemHeight = itemHeight, cyclic = true
        ) && minutes.isSettled(60, time.minutes, itemHeight, cyclic = true) &&
            (is24TimeFormat || period.isSettled(2, time.timesOfDay!!.ordinal, itemHeight, cyclic = false))
}

@Composable
internal fun rememberTimePickerState(currentTime: String, is24TimeFormat: Boolean): TimePickerState {
    val initialTime = PickerTime.parse(currentTime, is24TimeFormat)
    val hours = rememberPickerColumnState(initialWheelIndex(
        if (is24TimeFormat) 24 else 12,
        if (is24TimeFormat) initialTime.hours else initialTime.hours - 1
    ))
    val minutes = rememberPickerColumnState(initialWheelIndex(60, initialTime.minutes))
    val period = rememberPickerColumnState(initialTime.timesOfDay?.ordinal ?: 0)
    return remember(hours, minutes, period) { TimePickerState(hours, minutes, period) }
}
