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
