package com.huanchengfly.tieba.post.smoke

import android.os.Looper
import android.os.SystemClock
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.Player
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
    private lateinit var composeOwner: LifecycleOwner
    private val composeOwnerEvents = mutableListOf<Lifecycle.Event>()
    private val activityEvents = mutableListOf<Lifecycle.Event>()

    private fun install(restoration: StateRestorationTester? = null, source: () -> VideoPlayerSource = {
        VideoPlayerSource.Raw(R.raw.smoke_silence_a)
    }) {
        val content: @androidx.compose.runtime.Composable () -> Unit = {
            val current = rememberVideoPlayerController(source()) as DefaultVideoPlayerController
            controller = current
            val lifecycleOwner = LocalLifecycleOwner.current
            composeOwner = lifecycleOwner
            DisposableEffect(lifecycleOwner) {
                val observer = LifecycleEventObserver { _, event -> composeOwnerEvents.add(event) }
                lifecycleOwner.lifecycle.addObserver(observer)
                onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
            }
            PlayerSurface(onPlayerViewReleased = current::playerViewReleased) {
                surface = it
                current.playerViewAvailable(it)
            }
        }
        if (restoration == null) compose.setContent(content) else restoration.setContent(content)
        ready()
    }

    private fun ready() = compose.waitUntil(15_000) {
        compose.runOnUiThread {
            ::controller.isInitialized && ::surface.isInitialized &&
                surface.player?.playbackState == Player.STATE_READY &&
                controller.state.value.playbackState == PlaybackState.READY &&
                controller.state.value.duration >= 7_000
        }
    }

    private fun awaitPosition(expected: Long, player: () -> Player? = { surface.player }) {
        val range = (expected - 100)..(expected + 100)
        // A seek can synchronously enter BUFFERING. Let real Media3 settle and publish READY
        // instead of asserting the controller's cached position in the same seekTo call stack.
        compose.waitUntil(15_000) {
            compose.runOnUiThread {
                val activePlayer = player()
                activePlayer != null && activePlayer.playbackState == Player.STATE_READY &&
                    activePlayer.currentPosition in range &&
                    controller.state.value.playbackState == PlaybackState.READY &&
                    controller.state.value.currentPosition in range
            }
        }
        compose.runOnIdle {
            val activePlayer = checkNotNull(player())
            assertTrue("Media3 position ${activePlayer.currentPosition} must be within $range",
                activePlayer.currentPosition in range)
            assertTrue("Controller position ${controller.state.value.currentPosition} must be within $range",
                controller.state.value.currentPosition in range)
        }
    }

    private fun awaitPlaying() = compose.waitUntil(10_000) {
        compose.runOnUiThread {
            controller.state.value.isPlaying && surface.player?.isPlaying == true
        }
    }

    private fun observeActivityLifecycle(): LifecycleEventObserver {
        val observer = LifecycleEventObserver { _, event -> activityEvents.add(event) }
        compose.activityRule.scenario.onActivity { it.lifecycle.addObserver(observer) }
        return observer
    }

    /** UI-thread assertions only: no idling/wait can advance lifecycle or conceal a rejection. */
    private fun assertPausedAndCommandsRejected(
        activity: SmokeActivity,
        expectedLifecycle: Lifecycle.State,
        expectedController: DefaultVideoPlayerController,
        expectedPlayer: Player,
        expectedOwner: LifecycleOwner,
        boundary: String
    ) {
        assertSame(Looper.getMainLooper(), Looper.myLooper())
        val position = expectedController.state.value.currentPosition
        val playerPosition = expectedPlayer.currentPosition
        val quickSeekAction = expectedController.state.value.quickSeekAction
        val quickSeekDirection = quickSeekAction.direction
        val trace = mutableListOf<String>()
        fun assertUnchanged(command: String) {
            trace.add("$boundary/$command activity=${activity.lifecycle.currentState} " +
                "owner=${composeOwner.lifecycle.currentState} " +
                "ownerType=${composeOwner.javaClass.name} ownerId=${System.identityHashCode(composeOwner)} " +
                "controller=${System.identityHashCode(controller)} " +
                "player=${System.identityHashCode(surface.player)} " +
                "playWhenReady=${expectedPlayer.playWhenReady} isPlaying=${expectedPlayer.isPlaying} " +
                "cachedPlaying=${controller.state.value.isPlaying} " +
                "playerPosition=${expectedPlayer.currentPosition} cachedPosition=${controller.state.value.currentPosition} " +
                "quickSeek=${System.identityHashCode(controller.state.value.quickSeekAction)} " +
                "direction=${controller.state.value.quickSeekAction.direction}")
            val evidence = "activityEvents=${activityEvents.takeLast(24)} " +
                "ownerEvents=${composeOwnerEvents.takeLast(24)} " + trace.joinToString("; ").takeLast(2700)
            assertEquals(evidence, expectedLifecycle, activity.lifecycle.currentState)
            assertEquals(evidence, expectedLifecycle, composeOwner.lifecycle.currentState)
            assertSame(evidence, expectedOwner, composeOwner)
            assertSame(evidence, expectedController, controller)
            assertSame(evidence, expectedPlayer, surface.player)
            assertFalse(evidence, expectedPlayer.playWhenReady)
            assertFalse(evidence, expectedPlayer.isPlaying)
            assertFalse(evidence, controller.state.value.isPlaying)
            assertEquals(evidence, position, controller.state.value.currentPosition)
            assertEquals(evidence, playerPosition, expectedPlayer.currentPosition)
            // QuickSeekAction.equals is deliberately non-reflexive. Preserve the instance
            // and separately captured direction; ordinary object equality is unsuitable.
            assertSame(evidence, quickSeekAction, controller.state.value.quickSeekAction)
            assertEquals(evidence, quickSeekDirection, controller.state.value.quickSeekAction.direction)
        }
        assertUnchanged("paused")
        for ((name, command) in listOf<Pair<String, () -> Unit>>(
            "play" to { controller.play() },
            "seekTo(6000)" to { controller.seekTo(6_000) },
            "quickSeekForward" to { controller.quickSeekForward() },
            "quickSeekRewind" to { controller.quickSeekRewind() }
        )) {
            assertUnchanged("before-$name")
            command()
            assertUnchanged("after-$name")
        }
    }

    @Test fun movingSurfaceThenDisposingOldSurfaceKeepsNewOwner() {
        install()
        lateinit var player: Player
        lateinit var second: PlayerView
        compose.runOnIdle {
            val first = surface
            player = checkNotNull(first.player)
            second = PlayerView(compose.activity)
            controller.playerViewAvailable(second)
            assertNull(first.player)
            assertSame(player, second.player)
            controller.playerViewReleased(first)
            assertSame(player, second.player)
            controller.seekTo(2_000)
        }
        awaitPosition(2_000) { second.player }
        compose.runOnIdle {
            assertSame(player, second.player)
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
        val observer = observeActivityLifecycle()
        lateinit var previousController: DefaultVideoPlayerController
        lateinit var previousPlayer: Player
        lateinit var previousOwner: LifecycleOwner
        compose.runOnIdle { controller.play() }
        awaitPlaying()
        compose.activityRule.scenario.onActivity {
            previousController = controller
            previousPlayer = checkNotNull(surface.player)
            previousOwner = composeOwner
        }
        try {
            compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
            // Do not use runOnIdle after STOP: diagnose the actual Activity/Compose owner
            // boundary before any test idling could alter lifecycle dispatch.
            compose.activityRule.scenario.onActivity { activity ->
                val events = "activityEvents=$activityEvents ownerEvents=$composeOwnerEvents"
                assertPausedAndCommandsRejected(activity, Lifecycle.State.CREATED,
                    previousController, previousPlayer, previousOwner, "activity-stop")
                assertTrue(events, Lifecycle.Event.ON_STOP in activityEvents)
                assertTrue(events, Lifecycle.Event.ON_STOP in composeOwnerEvents)
            }
            compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
            compose.activityRule.scenario.onActivity { activity ->
                assertEquals(Lifecycle.State.RESUMED, activity.lifecycle.currentState)
                assertEquals(Lifecycle.State.RESUMED, composeOwner.lifecycle.currentState)
                assertSame(previousOwner, composeOwner)
                assertSame(previousController, controller)
                assertSame(previousPlayer, surface.player)
                assertFalse("Foreground return must not auto-resume", controller.state.value.isPlaying)
                assertFalse(previousPlayer.playWhenReady)
                assertFalse(previousPlayer.isPlaying)
                controller.play()
            }
            awaitPlaying()
            compose.runOnUiThread { controller.pause() }
        } finally {
            compose.activityRule.scenario.onActivity { it.lifecycle.removeObserver(observer) }
        }
    }

    @Test fun explicitForegroundFalsePausesAndRejectsCommandsUntilReenabled() {
        install()
        val observer = observeActivityLifecycle()
        compose.runOnIdle { controller.play() }
        awaitPlaying()
        try {
            compose.activityRule.scenario.onActivity { activity ->
                val previousController = controller
                val previousPlayer = checkNotNull(surface.player)
                val previousOwner = composeOwner
                controller.setForeground(false)
                assertPausedAndCommandsRejected(activity, Lifecycle.State.RESUMED,
                    previousController, previousPlayer, previousOwner, "explicit-background")
                controller.setForeground(true)
                assertSame(previousController, controller)
                assertSame(previousPlayer, surface.player)
                assertFalse("Re-enabling foreground must not auto-resume", controller.state.value.isPlaying)
                assertFalse(previousPlayer.playWhenReady)
                assertFalse(previousPlayer.isPlaying)
                controller.play()
            }
            awaitPlaying()
            compose.runOnUiThread { controller.pause() }
        } finally {
            compose.activityRule.scenario.onActivity { it.lifecycle.removeObserver(observer) }
        }
    }

    @Test fun composeSavedStateRestoresPositionForSameSource() {
        val restoration = StateRestorationTester(compose)
        install(restoration)
        lateinit var previous: DefaultVideoPlayerController
        compose.runOnIdle { controller.seekTo(2_500) }
        awaitPosition(2_500)
        compose.runOnIdle { previous = controller }
        restoration.emulateSavedInstanceStateRestore()
        ready()
        awaitPosition(2_500)
        compose.runOnIdle {
            assertNotSame(previous, controller)
            assertFalse(controller.state.value.isPlaying)
            assertFalse(checkNotNull(surface.player).playWhenReady)
        }
    }

    @Test fun composeSavedStateDoesNotLeakPositionToDifferentSource() {
        // Deliberately not Compose State: old composition saves A; recreated composition reads B.
        var source: VideoPlayerSource = VideoPlayerSource.Raw(R.raw.smoke_silence_a)
        val restoration = StateRestorationTester(compose)
        install(restoration) { source }
        lateinit var previous: DefaultVideoPlayerController
        compose.runOnIdle { controller.seekTo(3_500) }
        awaitPosition(3_500)
        compose.runOnIdle {
            previous = controller
            source = VideoPlayerSource.Raw(R.raw.smoke_silence_b)
        }
        restoration.emulateSavedInstanceStateRestore()
        ready()
        compose.runOnIdle {
            assertNotSame(previous, controller)
            assertTrue("A different source must start near its initial position",
                controller.state.value.currentPosition < 1_000)
            assertTrue("The actual Media3 player must also start at the new source's beginning",
                checkNotNull(surface.player).currentPosition < 1_000)
        }
    }
}
