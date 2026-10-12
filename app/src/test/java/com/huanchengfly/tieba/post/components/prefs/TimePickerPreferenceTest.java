package com.huanchengfly.tieba.post.components.prefs;

import org.junit.Test;

import java.util.Locale;

import static org.junit.Assert.assertEquals;

public class TimePickerPreferenceTest {
    @Test public void persistenceFormattingNeverUsesLocalizedDigits() {
        Locale previous = Locale.getDefault();
        try {
            for (Locale locale : new Locale[]{Locale.US, Locale.forLanguageTag("ar"), Locale.forLanguageTag("fa")}) {
                Locale.setDefault(locale);
                assertEquals("07:03", TimePickerPreference.timeToString(7, 3));
                assertEquals("00:00", TimePickerPreference.timeToString(0, 0));
                assertEquals("23:59", TimePickerPreference.timeToString(23, 59));
            }
        } finally {
            Locale.setDefault(previous);
        }
    }
}
