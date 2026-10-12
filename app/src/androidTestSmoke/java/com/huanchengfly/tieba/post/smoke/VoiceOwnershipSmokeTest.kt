package com.huanchengfly.tieba.post.smoke

import android.widget.LinearLayout
import androidx.test.core.app.ActivityScenario
import com.huanchengfly.tieba.post.R
import com.huanchengfly.tieba.post.ui.widgets.VoicePlayerView
import org.junit.Assert.*
import org.junit.Test

class VoiceOwnershipSmokeTest {
    @Test fun recyclingUnrelatedRowCannotStopCurrentVoiceAndReleaseIsRepeatable() {
        ActivityScenario.launch(SmokeActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val rows = LinearLayout(activity)
                val first = VoicePlayerView(activity)
                val second = VoicePlayerView(activity)
                rows.addView(first)
                rows.addView(second)
                activity.setContentView(rows)
                val source = "android.resource://${activity.packageName}/${R.raw.smoke_silence_a}"
                try {
                    first.startPlay(source)
                    assertTrue(VoicePlayerView.Manager.isCurrent(first))
                    second.startPlay(source)
                    assertFalse(VoicePlayerView.Manager.isCurrent(first))
                    assertTrue(VoicePlayerView.Manager.isCurrent(second))
                    rows.removeView(first) // Calls the real onDetachedFromWindow/release path.
                    first.release()
                    VoicePlayerView.Manager.pause(first)
                    assertTrue(VoicePlayerView.Manager.isCurrent(second))
                    assertTrue(VoicePlayerView.Manager.isPlaying(second))
                    second.release()
                    second.release()
                    assertFalse(VoicePlayerView.Manager.isCurrent(second))
                    first.startPlay(source)
                    assertTrue(VoicePlayerView.Manager.isCurrent(first))
                    VoicePlayerView.Manager.releaseForContext(activity)
                    assertFalse(VoicePlayerView.Manager.isCurrent(first))
                } finally {
                    VoicePlayerView.Manager.release()
                }
            }
        }
    }
}
