package com.huanchengfly.tieba.post.smoke

import android.os.SystemClock
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.Lifecycle
import androidx.media3.ui.PlayerView
import com.huanchengfly.tieba.post.R
import com.huanchengfly.tieba.post.ui.widgets.compose.video.DefaultVideoPlayerController
import com.huanchengfly.tieba.post.ui.widgets.compose.video.PlaybackState
import com.huanchengfly.tieba.post.ui.widgets.compose.video.PlayerSurface
import com.huanchengfly.tieba.post.ui.widgets.compose.video.VideoPlayerSource
import com.huanchengfly.tieba.post.ui.widgets.compose.video.rememberVideoPlayerController
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Real Media3 and production Compose owner/saver, using eight-second bundled silent WAVs. */
class MediaControllerSmokeTest {
    @get:Rule val compose = createAndroidComposeRule<SmokeActivity>()
    private lateinit var controller: DefaultVideoPlayerController
    private lateinit var surface: PlayerView

    private fun install(restoration: StateRestorationTester? = null, source: () -> VideoPlayerSource = {
        VideoPlayerSource.Raw(R.raw.smoke_silence_a)
    }) {
        val content: @androidx.compose.runtime.Composable () -> Unit = {
            val current = rememberVideoPlayerController(source()) as DefaultVideoPlayerController
            controller = current
            PlayerSurface(onPlayerViewReleased = current::playerViewReleased) {
                surface = it
                current.playerViewAvailable(it)
            }
        }
        if (restoration == null) compose.setContent(content) else restoration.setContent(content)
        ready()
    }

    private fun ready() = compose.waitUntil(15_000) {
        ::controller.isInitialized && controller.state.value.playbackState == PlaybackState.READY &&
            controller.state.value.duration >= 7_000
    }

    @Test fun movingSurfaceThenDisposingOldSurfaceKeepsNewOwner() {
        install()
        compose.runOnIdle {
            val first = surface
            val player = checkNotNull(first.player)
            val second = PlayerView(compose.activity)
            controller.playerViewAvailable(second)
            assertNull(first.player)
            assertSame(player, second.player)
            controller.playerViewReleased(first)
            assertSame(player, second.player)
            controller.seekTo(2_000)
            assertTrue(controller.state.value.currentPosition >= 1_900)
            controller.playerViewReleased(second)
            assertNull(second.player)
        }
    }

    @Test fun releaseCancelsPendingPreviewAndLateCallsCannotRecreatePlayers() {
        install()
        lateinit var preview: PlayerView
        lateinit var detached: PlayerView
        compose.runOnIdle {
            preview = PlayerView(compose.activity)
            controller.previewPlayerViewAvailable(preview)
            assertNotNull(preview.player)
            controller.previewSeekTo(4_000) // A real delayed preview job is now pending.
            controller.play()
            controller.release()
            controller.release()
            controller.seekTo(5_000)
            controller.previewSeekTo(6_000)
            controller.play()
            detached = PlayerView(compose.activity)
            controller.playerViewAvailable(detached)
            assertNull(surface.player)
            assertNull(preview.player)
            assertNull(detached.player)
        }
        SystemClock.sleep(400) // Cross the production 200ms delayed-job boundary.
        compose.runOnIdle {
            assertNull(detached.player)
            assertNull(preview.player)
        }
    }

    @Test fun stoppingActivityPausesAndRejectsBackgroundPlaybackUntilResumed() {
        install()
        compose.runOnIdle { controller.play() }
        compose.waitUntil(10_000) { controller.state.value.isPlaying }
        compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
        compose.runOnIdle {
            assertFalse(controller.state.value.isPlaying)
            val position = controller.state.value.currentPosition
            val quickSeekAction = controller.state.value.quickSeekAction
            controller.play()
            controller.seekTo(6_000)
            controller.quickSeekForward()
            controller.quickSeekRewind()
            assertFalse(controller.state.value.isPlaying)
            assertEquals(position, controller.state.value.currentPosition)
            assertEquals(quickSeekAction, controller.state.value.quickSeekAction)
        }
        compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
        compose.runOnIdle { controller.play() }
        compose.waitUntil(10_000) { controller.state.value.isPlaying }
        compose.runOnIdle { controller.pause() }
    }

    @Test fun composeSavedStateRestoresPositionForSameSource() {
        val restoration = StateRestorationTester(compose)
        install(restoration)
        lateinit var previous: DefaultVideoPlayerController
        compose.runOnIdle {
            controller.seekTo(2_500)
            assertTrue(controller.state.value.currentPosition >= 2_400)
            previous = controller
        }
        restoration.emulateSavedInstanceStateRestore()
        ready()
        compose.runOnIdle {
            assertNotSame(previous, controller)
            assertTrue(controller.state.value.currentPosition >= 2_400)
            assertFalse(controller.state.value.isPlaying)
        }
    }

    @Test fun composeSavedStateDoesNotLeakPositionToDifferentSource() {
        // Deliberately not Compose State: old composition saves A; recreated composition reads B.
        var source: VideoPlayerSource = VideoPlayerSource.Raw(R.raw.smoke_silence_a)
        val restoration = StateRestorationTester(compose)
        install(restoration) { source }
        lateinit var previous: DefaultVideoPlayerController
        compose.runOnIdle {
            controller.seekTo(3_500)
            assertTrue(controller.state.value.currentPosition >= 3_400)
            previous = controller
            source = VideoPlayerSource.Raw(R.raw.smoke_silence_b)
        }
        restoration.emulateSavedInstanceStateRestore()
        ready()
        compose.runOnIdle {
            assertNotSame(previous, controller)
            assertTrue("A different source must start near its initial position",
                controller.state.value.currentPosition < 1_000)
        }
    }
}
