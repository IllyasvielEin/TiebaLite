"""Offline media ownership assertions and source guards, not Android/Compose runtime validation."""
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'
VIDEO = JAVA / 'ui/widgets/compose/video'
SMOKE_MEDIA = ROOT / 'app/src/androidTestSmoke/java/com/huanchengfly/tieba/post/smoke/MediaControllerSmokeTest.kt'


class MediaWiringTest(unittest.TestCase):
    def test_presentation_does_not_release_video_owner(self):
        source = (JAVA / 'ui/widgets/compose/FeedCard.kt').read_text()
        player = source.split('fun VideoPlayer(', 1)[1].split('@Preview', 1)[0]
        self.assertNotIn('videoPlayerController.release()', player)
        self.assertIn('remember(videoPlayerController)', player)
        owner = (VIDEO / 'VideoPlayer.kt').read_text()
        self.assertIn('DisposableEffect(controller)', owner)
        self.assertIn('onDispose { controller.release() }', owner)
        self.assertNotIn('LaunchedEffect(Unit)', owner)
        self.assertIn('context, coroutineScope, source,', owner)

    def test_release_cancels_jobs_and_never_uses_creating_getters(self):
        source = (VIDEO / 'DefaultVideoPlayerController.kt').read_text()
        release = source.split('override fun release()', 1)[1].split('override fun supportFullScreen', 1)[0]
        for job in ('updateDurationAndPositionJob', 'autoHideControllerJob', 'playHideJob', 'previewSeekJob'):
            self.assertIn(job + '?.cancel()', release)
        self.assertNotIn('exoPlayer.release()', release)
        self.assertNotIn('previewExoPlayer.release()', release)
        self.assertIn('playerView?.player = null', release)
        self.assertIn('previewPlayerView?.player = null', release)
        self.assertIn('mainPlayer.release()', release)
        self.assertIn('previewPlayer.release()', release)
        self.assertIn('remember(this, filter)', source)

    def test_quick_seeks_reject_background_before_accessing_player(self):
        source = (VIDEO / 'DefaultVideoPlayerController.kt').read_text()
        for method in ('quickSeekForward', 'quickSeekRewind'):
            with self.subTest(method=method):
                body = source.split('override fun ' + method + '()', 1)[1].split('override fun ', 1)[0]
                guard = 'if (released.get() || !foreground) return'
                self.assertIn(guard, body)
                self.assertLess(body.index(guard), body.index('exoPlayer.'))

    def test_restore_matches_saved_source_without_persisting_raw_source(self):
        source = (VIDEO / 'VideoPlayer.kt').read_text()
        restore = source.split('override fun restore(value: Any)', 1)[1].split('override fun SaverScope.save', 1)[0]
        self.assertIn('value as? SavedVideoPlayerState', restore)
        self.assertIn('PlaybackSourceIdentity.restoreOrDefault(', restore)
        self.assertIn('saved.sourceIdentity', restore)
        self.assertIn('saved.state', restore)
        self.assertIn('VideoPlayerState()', restore)
        saved = source.split('override fun SaverScope.save', 1)[1].split('init = {', 1)[0]
        self.assertIn('sourceIdentity = sourceIdentity', saved)
        self.assertIn('it.copy(thumbnailUrl = null)', saved)
        self.assertNotIn('source.url', saved)
        self.assertNotIn('source.headers', saved)

    def test_audio_rows_only_detach_their_own_binding(self):
        view = (JAVA / 'ui/widgets/VoicePlayerView.kt').read_text()
        compose = (JAVA / 'ui/widgets/compose/Voices.kt').read_text()
        self.assertNotIn('Timer', view)
        self.assertNotIn('var CURRENT:', view)
        self.assertNotIn('private val mExoPlayer', view)
        self.assertIn('if (!owner.detach(view)) return', view)
        self.assertIn('previous?.removeListener(this)', view)
        self.assertIn('progressJob?.cancel()', view)
        self.assertIn('context.applicationContext', view)
        self.assertNotIn('Manager.release()', compose)
        self.assertIn('onRelease = { it.release() }', compose)

    def test_surface_cleanup_and_background_pause_are_explicit(self):
        surface = (VIDEO / 'PlayerSurface.kt').read_text()
        self.assertIn('update = onPlayerViewAvailable', surface)
        self.assertIn('onRelease = { view ->', surface)
        self.assertIn('view.player = null', surface)
        source = (VIDEO / 'VideoPlayer.kt').read_text()
        self.assertIn('Lifecycle.Event.ON_STOP', source)
        self.assertNotIn('Lifecycle.Event.ON_PAUSE', source)
        self.assertIn('Lifecycle.Event.ON_START', source)
        self.assertIn('Lifecycle.Event.ON_RESUME', source)
        self.assertIn('currentState.isAtLeast(Lifecycle.State.STARTED)', source)
        self.assertIn('controller.setForeground(false)', source)
        self.assertIn('controller.setForeground(true)', source)
        controller = (VIDEO / 'DefaultVideoPlayerController.kt').read_text()
        self.assertIn('if (!isForeground) pause()', controller)
        self.assertIn('if (released.get() || !foreground) return', controller)

    def test_min35_media_branches_preserve_supported_lifecycle(self):
        build = (ROOT / 'app/build.gradle.kts').read_text()
        min_sdk = re.search(r'minSdk\s*=\s*(\d+)', build)
        self.assertIsNotNone(min_sdk)
        self.assertGreaterEqual(int(min_sdk.group(1)), 35)
        base = (JAVA / 'activities/BaseActivity.kt').read_text()
        pause = base.split('override fun onPause()', 1)[1].split('override fun ', 1)[0]
        stop = base.split('override fun onStop()', 1)[1].split('open val ', 1)[0]
        self.assertIn('isActivityRunning = false', pause)
        self.assertNotIn('VoicePlayerView.Manager.releaseForContext', pause)
        self.assertIn('VoicePlayerView.Manager.releaseForContext(this)', stop)
        voice = (JAVA / 'ui/widgets/VoicePlayerView.kt').read_text()
        self.assertIn('foreground = ContextCompat.getDrawable(context, R.drawable.fg_ripple_radius_50dp)', voice)
        video = (VIDEO / 'VideoPlayer.kt').read_text()
        for source in (base, voice, video):
            self.assertNotIn('Build.VERSION.SDK_INT', source)
            self.assertNotIn('import android.os.Build', source)


class MediaSmokeDiagnosticsSourceTest(unittest.TestCase):
    def test_activity_transition_still_checks_exact_stopped_owners_without_idling(self):
        source = SMOKE_MEDIA.read_text()
        stopped = source.split('@Test fun stoppingActivityPausesAndRejectsBackgroundPlaybackUntilResumed()', 1)[1]
        stopped = stopped.split('@Test fun explicitForegroundFalsePausesAndRejectsCommandsUntilReenabled()', 1)[0]
        boundary = stopped.split('scenario.moveToState(Lifecycle.State.CREATED)', 1)[1]
        boundary = boundary.split('scenario.moveToState(Lifecycle.State.RESUMED)', 1)[0]
        self.assertIn('scenario.onActivity { activity ->', boundary)
        self.assertIn('assertPausedAndCommandsRejected(activity, Lifecycle.State.CREATED,', boundary)
        self.assertIn('Lifecycle.Event.ON_STOP in activityEvents', boundary)
        self.assertIn('Lifecycle.Event.ON_STOP in composeOwnerEvents', boundary)
        self.assertNotIn('compose.runOnIdle', boundary)
        self.assertNotIn('waitUntil', boundary)
        self.assertNotIn('SystemClock.sleep', boundary)
        self.assertNotIn('setForeground(false)', stopped)
        self.assertIn('val lifecycleOwner = LocalLifecycleOwner.current', source)
        self.assertIn('DisposableEffect(lifecycleOwner)', source)
        self.assertIn('LifecycleEventObserver { _, event -> composeOwnerEvents.add(event) }', source)
        self.assertIn('onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }', source)
        for capture in ('previousController = controller', 'previousPlayer = checkNotNull(surface.player)',
                        'previousOwner = composeOwner'):
            self.assertLess(stopped.index(capture), stopped.index('scenario.moveToState(Lifecycle.State.CREATED)'))

    def test_each_rejected_command_checks_actual_cached_identity_and_position_immediately(self):
        source = SMOKE_MEDIA.read_text()
        helper = source.split('private fun assertPausedAndCommandsRejected(', 1)[1].split('@Test fun', 1)[0]
        for expected in (
            'assertEquals(evidence, expectedLifecycle, activity.lifecycle.currentState)',
            'assertEquals(evidence, expectedLifecycle, composeOwner.lifecycle.currentState)',
            'assertSame(evidence, expectedOwner, composeOwner)',
            'assertSame(evidence, expectedController, controller)',
            'assertSame(evidence, expectedPlayer, surface.player)',
            'assertFalse(evidence, expectedPlayer.playWhenReady)',
            'assertFalse(evidence, expectedPlayer.isPlaying)',
            'assertFalse(evidence, controller.state.value.isPlaying)',
            'assertEquals(evidence, position, controller.state.value.currentPosition)',
            'assertEquals(evidence, playerPosition, expectedPlayer.currentPosition)',
            'assertSame(evidence, quickSeekAction, controller.state.value.quickSeekAction)',
            'assertEquals(evidence, quickSeekDirection, controller.state.value.quickSeekAction.direction)',
            'assertSame(Looper.getMainLooper(), Looper.myLooper())',
        ):
            self.assertIn(expected, helper)
        for command in ('controller.play()', 'controller.seekTo(6_000)',
                        'controller.quickSeekForward()', 'controller.quickSeekRewind()'):
            self.assertIn(command, helper)
        self.assertIn('assertUnchanged("before-$name")\n            command()\n            assertUnchanged("after-$name")', helper)
        self.assertIn('activityEvents.takeLast(24)', helper)
        self.assertIn('composeOwnerEvents.takeLast(24)', helper)
        self.assertIn('trace.joinToString("; ").takeLast(2700)', helper)
        self.assertNotIn('waitUntil', helper)
        self.assertNotIn('runOnIdle', helper)
        self.assertNotIn('SystemClock.sleep', helper)

    def test_explicit_foreground_guard_is_separate_from_activity_transition_case(self):
        source = SMOKE_MEDIA.read_text()
        direct = source.split('@Test fun explicitForegroundFalsePausesAndRejectsCommandsUntilReenabled()', 1)[1]
        direct = direct.split('@Test fun', 1)[0]
        self.assertIn('controller.setForeground(false)', direct)
        self.assertIn('assertPausedAndCommandsRejected(activity, Lifecycle.State.RESUMED,', direct)
        self.assertIn('controller.setForeground(true)', direct)
        self.assertNotIn('scenario.moveToState', direct)
        self.assertLess(direct.index('controller.setForeground(false)'), direct.index('assertPausedAndCommandsRejected'))
        self.assertLess(direct.index('assertPausedAndCommandsRejected'), direct.index('controller.setForeground(true)'))
        for guard in ('controller.state.value.isPlaying', 'previousPlayer.playWhenReady', 'previousPlayer.isPlaying'):
            self.assertIn(guard, direct.split('controller.setForeground(true)', 1)[1])



@unittest.skipUnless(shutil.which('java'), 'JDK needed for pure playback ownership tests')
class PlaybackOwnershipExecutableTest(unittest.TestCase):
    def test_pure_ownership_scenarios(self):
        with tempfile.TemporaryDirectory() as folder:
            package = 'ui/widgets/media'
            sources = [JAVA / package / 'PlaybackResource.java', JAVA / package / 'PlaybackOwner.java',
                       JAVA / package / 'PlaybackSourceIdentity.java',
                       ROOT / 'app/src/test/java/com/huanchengfly/tieba/post' / package / 'PlaybackOwnershipHarness.java']
            subprocess.run([shutil.which('java'), '-m', 'jdk.compiler/com.sun.tools.javac.Main',
                            '-d', folder, *map(str, sources)], check=True)
            subprocess.run([shutil.which('java'), '-cp', folder,
                            'com.huanchengfly.tieba.post.ui.widgets.media.PlaybackOwnershipHarness'], check=True)


if __name__ == '__main__':
    unittest.main()
