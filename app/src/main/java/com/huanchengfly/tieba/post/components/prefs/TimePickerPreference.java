package com.huanchengfly.tieba.post.components.prefs;

import android.content.Context;
import android.content.res.TypedArray;
import android.util.AttributeSet;

import androidx.preference.DialogPreference;

import java.util.Locale;

public class TimePickerPreference extends DialogPreference {
    public int hour = 0;
    public int minute = 0;

    public TimePickerPreference(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public static int parseHour(String value) {
        try {
            String[] time = value.split(":");
            return (Integer.parseInt(time[0]));
        } catch (Exception e) {
            return 0;
        }
    }

    public static int parseMinute(String value) {
        try {
            String[] time = value.split(":");
            return (Integer.parseInt(time[1]));
        } catch (Exception e) {
            return 0;
        }
    }

    public static String timeToString(int h, int m) {
        return String.format(Locale.ROOT, "%02d:%02d", h, m);
    }

    @Override
    protected Object onGetDefaultValue(TypedArray a, int index) {
        return a.getString(index);
    }

    @Override
    protected void onSetInitialValue(boolean restoreValue, Object defaultValue) {
        String value;
        if (restoreValue) {
            if (defaultValue == null) value = getPersistedString("00:00");
            else value = getPersistedString(defaultValue.toString());
        } else {
            value = defaultValue.toString();
        }

        hour = parseHour(value);
        minute = parseMinute(value);
    }

    public void persistStringValue(String value) {
        persistString(value);
    }
}
