package com.huanchengfly.tieba.post.ui.widgets.compose.video

import android.annotation.SuppressLint
import android.content.Context
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.Player.STATE_ENDED
import androidx.media3.common.Player.STATE_IDLE
import androidx.media3.common.Player.STATE_READY
import androidx.media3.common.VideoSize
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.RawResourceDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import com.huanchengfly.tieba.post.ui.widgets.media.PlaybackResource
import com.huanchengfly.tieba.post.ui.widgets.compose.video.util.set
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

interface OnFullScreenModeChangedListener {
    fun onFullScreenModeChanged(isFullScreen: Boolean)
}

internal class DefaultVideoPlayerController(
    private val context: Context,
    private val initialState: VideoPlayerState,
    private val coroutineScope: CoroutineScope,
    private val fullScreenModeChangedListener: OnFullScreenModeChangedListener? = null
) : VideoPlayerController {
    private val released = AtomicBoolean(true)
    private var foreground = true

    private val _state = MutableStateFlow(initialState)
    override val state: StateFlow<VideoPlayerState>
        get() = _state.asStateFlow()

    /**
     * Some properties in initial state are not applicable until player is ready.
     * These are kept in this container. Once the player is ready for the first time,
     * they are applied and removed.
     */
    private var initialStateRunner: (() -> Unit)? = {
        exoPlayer.seekTo(initialState.currentPosition)
    }

    fun <T> currentState(filter: (VideoPlayerState) -> T): T {
        return filter(_state.value)
    }

    @Composable
    fun collect(): State<VideoPlayerState> {
        return _state.collectAsState()
    }

    @SuppressLint("StateFlowValueCalledInComposition")
    @Composable
    fun <T> collect(filter: VideoPlayerState.() -> T): State<T> {
        return remember(this, filter) {
            _state.map { it.filter() }
        }.collectAsState(
            initial = _state.value.filter()
        )
    }

    var videoPlayerBackgroundColor: Int = DefaultVideoPlayerBackgroundColor.value.toInt()
        set(value) {
            field = value
            playerView?.setBackgroundColor(value)
        }

    private lateinit var source: VideoPlayerSource
    private var playerView: PlayerView? = null
    private var previewPlayerView: PlayerView? = null

    private var updateDurationAndPositionJob: Job? = null
    private var autoHideControllerJob: Job? = null
    private var playHideJob: Job? = null
    private var previewSeekJob: Job? = null

    private val playerListener = object : Player.Listener {
        @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
        override fun onPlaybackStateChanged(playbackState: Int) {
            if (released.get()) return
            if (PlaybackState.of(playbackState) == PlaybackState.READY) {
                initialStateRunner = initialStateRunner?.let {
                    it.invoke()
                    null
                }

                updateDurationAndPosition()
            }

            _state.set {
                copy(
                    playbackState = PlaybackState.of(playbackState),
                    startedPlay = playbackState != STATE_IDLE
                )
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (released.get()) return
            updateDurationAndPositionJob?.cancel()
            updateDurationAndPositionJob = null
            if (isPlaying) {
                updateDurationAndPositionJob = coroutineScope.launch {
                    while (isActive && !released.get()) {
                        updateDurationAndPosition()
                        delay(250)
                    }
                }
            } else {
                updateDurationAndPosition()
            }
        }

        override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
            if (released.get()) return
            _state.set {
                copy(isPlaying = playWhenReady)
            }
        }

        override fun onVideoSizeChanged(videoSize: VideoSize) {
            if (released.get()) return
            _state.set {
                copy(videoSize = videoSize.width.toFloat() to videoSize.height.toFloat())
            }
        }
    }

    /**
     * Internal exoPlayer instance
     */
    private val mainPlayer = PlaybackResource<ExoPlayer>(::createExoPlayer) { it.release() }
    private val exoPlayer: ExoPlayer
        get() = checkNotNull(mainPlayer.getOrCreate()) { "Video player owner is inactive" }

    private fun createExoPlayer(): ExoPlayer = ExoPlayer.Builder(context.applicationContext)
        .build()
        .apply {
            playWhenReady = _state.value.isPlaying
            addListener(playerListener)
        }

    /**
     * Not so efficient way of showing preview in video slider.
     */
    private val previewPlayer = PlaybackResource<ExoPlayer>(::createPreviewExoPlayer) { it.release() }
    private val previewExoPlayer: ExoPlayer
        get() = checkNotNull(previewPlayer.getOrCreate()) { "Video player owner is inactive" }

    private fun createPreviewExoPlayer(): ExoPlayer = ExoPlayer.Builder(context.applicationContext)
        .build()
        .apply {
            playWhenReady = false
        }

    fun initialize() {
        if (!released.compareAndSet(true, false)) return
        mainPlayer.activate()
        previewPlayer.activate()
        Log.i("VideoPlayerController", "$this initialize")
        val currentState = _state.value
        exoPlayer.playWhenReady = currentState.isPlaying
        initialStateRunner = {
            exoPlayer.seekTo(currentState.currentPosition)
        }
        waitPlayerViewToPrepare.set(this::source.isInitialized)
        if (playerView != null) {
            playerViewAvailable(playerView!!)
        }
    }

    /**
     * A flag to indicate whether source is already set and waiting for
     * playerView to become available.
     */
    private val waitPlayerViewToPrepare = AtomicBoolean(false)

    override fun play() {
        if (released.get() || !foreground) return
        _state.set { copy(startedPlay = true) }
        if (exoPlayer.playbackState == STATE_ENDED) {
            exoPlayer.seekTo(0)
        }
        exoPlayer.playWhenReady = true
        playHideJob?.cancel()
        playHideJob = coroutineScope.launch {
            delay(200)
            if (!released.get()) hideControls()
        }
    }

    override fun pause() {
        if (released.get()) return
        exoPlayer.playWhenReady = false
        playHideJob?.cancel()
        previewSeekJob?.cancel()
        showControls(false)
    }

    override fun togglePlaying() {
        if (released.get()) return
        if (exoPlayer.isPlaying) pause()
        else play()
    }

    override fun quickSeekForward() {
        if (released.get() || !foreground) return
        if (_state.value.quickSeekAction.direction != QuickSeekDirection.None) {
            // Currently animating
            return
        }
        val target = (exoPlayer.currentPosition + 10_000).coerceAtMost(exoPlayer.duration)
        exoPlayer.seekTo(target)
        updateDurationAndPosition()
        _state.set { copy(quickSeekAction = QuickSeekAction.forward()) }
    }

    override fun quickSeekRewind() {
        if (released.get() || !foreground) return
        if (_state.value.quickSeekAction.direction != QuickSeekDirection.None) {
            // Currently animating
            return
        }
        val target = (exoPlayer.currentPosition - 10_000).coerceAtLeast(0)
        exoPlayer.seekTo(target)
        updateDurationAndPosition()
        _state.set { copy(quickSeekAction = QuickSeekAction.rewind()) }
    }

    override fun seekTo(position: Long) {
        if (released.get() || !foreground) return
        exoPlayer.seekTo(position)
        updateDurationAndPosition()
    }

    override fun setSource(source: VideoPlayerSource) {
        this.source = source
        if (released.get() || playerView == null) {
            waitPlayerViewToPrepare.set(true)
        } else {
            waitPlayerViewToPrepare.set(false)
            prepare()
        }
    }

    fun setForeground(isForeground: Boolean) {
        foreground = isForeground
        if (!isForeground) pause()
    }

    fun setThumbnail(thumbnailUrl: String?) {
        _state.set { copy(thumbnailUrl = thumbnailUrl) }
    }

    fun enableGestures(isEnabled: Boolean) {
        _state.set { copy(gesturesEnabled = isEnabled) }
    }

    fun enableControls(enabled: Boolean) {
        _state.set { copy(controlsEnabled = enabled) }
    }

    fun showControls(autoHide: Boolean = true) {
        _state.set { copy(controlsVisible = true) }
        if (autoHide) {
            autoHideControls()
        } else {
            cancelAutoHideControls()
        }
    }

    private fun cancelAutoHideControls() {
        Log.i("VideoPlayerController", "cancelAutoHideControls")
        autoHideControllerJob?.cancel()
    }

    private fun autoHideControls() {
        if (released.get()) return
        cancelAutoHideControls()
        Log.i("VideoPlayerController", "autoHideControls")
        autoHideControllerJob = coroutineScope.launch {
            delay(3000)
            if (!released.get()) hideControls()
        }
    }

    fun hideControls() {
        _state.set { copy(controlsVisible = false) }
    }

    fun setDraggingProgress(draggingProgress: DraggingProgress?) {
        _state.set { copy(draggingProgress = draggingProgress) }
    }

    fun setQuickSeekAction(quickSeekAction: QuickSeekAction) {
        _state.set { copy(quickSeekAction = quickSeekAction) }
    }

    private fun updateDurationAndPosition() {
        if (released.get()) return
        val exoPlayer = mainPlayer.peek() ?: return
        if (exoPlayer.playbackState == STATE_READY || exoPlayer.playbackState == STATE_ENDED) {
            _state.set {
                copy(
                    duration = exoPlayer.duration.coerceAtLeast(0),
                    currentPosition = exoPlayer.currentPosition.coerceAtLeast(0),
                    secondaryProgress = exoPlayer.bufferedPosition.coerceAtLeast(0),
                    isPlaying = exoPlayer.isPlaying
                )
            }
        }
    }

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    private fun prepare() {
        if (released.get()) return
        fun createVideoSource(): MediaSource {
            val dataSourceFactory: DataSource.Factory = DefaultDataSource.Factory(context)

            return when (val source = source) {
                is VideoPlayerSource.Raw -> {
                    ProgressiveMediaSource.Factory(dataSourceFactory)
                        .createMediaSource(
                            MediaItem.fromUri(
                                RawResourceDataSource.buildRawResourceUri(
                                    source.resId
                                )
                            )
                        )
                }

                is VideoPlayerSource.Network -> {
                    ProgressiveMediaSource.Factory(dataSourceFactory)
                        .createMediaSource(MediaItem.fromUri(source.url))
                }
            }
        }

        exoPlayer.setMediaSource(createVideoSource())
        previewExoPlayer.setMediaSource(createVideoSource())

        exoPlayer.prepare()
        previewExoPlayer.prepare()
    }

    fun playerViewAvailable(playerView: PlayerView) {
        if (this.playerView !== playerView) this.playerView?.player = null
        this.playerView = playerView
        if (released.get()) return
        playerView.player = exoPlayer
        playerView.setBackgroundColor(videoPlayerBackgroundColor)

        if (waitPlayerViewToPrepare.compareAndSet(true, false)) {
            prepare()
        }
    }

    fun previewPlayerViewAvailable(playerView: PlayerView) {
        if (previewPlayerView !== playerView) previewPlayerView?.player = null
        previewPlayerView = playerView
        if (!released.get()) playerView.player = previewExoPlayer
    }

    fun playerViewReleased(view: PlayerView) {
        view.player = null
        if (playerView === view) playerView = null
        if (previewPlayerView === view) previewPlayerView = null
    }

    fun previewSeekTo(position: Long) {
        if (released.get() || !foreground) return
        // A preview only needs two-second precision, and only the latest seek survives.
        val roundedPosition = (position.coerceAtLeast(0) / 2000) * 2000
        previewSeekJob?.cancel()
        previewSeekJob = coroutineScope.launch {
            delay(200)
            if (!released.get() && foreground) previewExoPlayer.seekTo(roundedPosition)
        }
    }

    override fun reset() {
        if (released.get()) return
        exoPlayer.stop()
        previewExoPlayer.stop()
    }

    override fun release() {
        if (!released.compareAndSet(false, true)) return
        updateDurationAndPositionJob?.cancel()
        autoHideControllerJob?.cancel()
        playHideJob?.cancel()
        previewSeekJob?.cancel()
        updateDurationAndPositionJob = null
        autoHideControllerJob = null
        playHideJob = null
        previewSeekJob = null
        initialStateRunner = null
        playerView?.player = null
        previewPlayerView?.player = null
        playerView = null
        previewPlayerView = null
        mainPlayer.peek()?.removeListener(playerListener)
        try {
            mainPlayer.release()
        } finally {
            previewPlayer.release()
        }
    }

    override fun supportFullScreen(): Boolean {
        return fullScreenModeChangedListener != null
    }

    override fun toggleFullScreen() {
        require(fullScreenModeChangedListener != null) { "Full screen mode is not supported" }
        fullScreenModeChangedListener.onFullScreenModeChanged(!currentState { it.isFullScreen })
        _state.set { copy(isFullScreen = !isFullScreen) }
    }
}

val DefaultVideoPlayerBackgroundColor = Color.Black