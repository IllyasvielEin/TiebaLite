package com.huanchengfly.tieba.post.ui.widgets

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.ColorFilter
import android.net.Uri
import android.os.Build
import android.util.AttributeSet
import android.util.Log
import android.view.MenuItem
import android.view.View
import android.view.View.OnLongClickListener
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.RelativeLayout
import android.widget.TextView
import androidx.annotation.IntDef
import androidx.annotation.OptIn
import androidx.appcompat.widget.PopupMenu
import androidx.core.content.ContextCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.PlaybackException
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import com.airbnb.lottie.LottieAnimationView
import com.airbnb.lottie.LottieProperty
import com.airbnb.lottie.SimpleColorFilter
import com.airbnb.lottie.model.KeyPath
import com.airbnb.lottie.value.LottieValueCallback
import com.huanchengfly.tieba.post.R
import com.huanchengfly.tieba.post.findActivity
import com.huanchengfly.tieba.post.ui.widgets.media.PlaybackOwner
import com.huanchengfly.tieba.post.ui.common.theme.utils.ColorStateListUtils
import com.huanchengfly.tieba.post.ui.common.theme.utils.ThemeUtils
import com.huanchengfly.tieba.post.utils.DisplayUtil
import com.huanchengfly.tieba.post.utils.FileUtil
import com.huanchengfly.tieba.post.utils.PopupUtil
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class VoicePlayerView @JvmOverloads constructor(
    context: Context?,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : RelativeLayout(context, attrs, defStyleAttr), View.OnClickListener,
    OnLongClickListener, PopupMenu.OnMenuItemClickListener {
    private lateinit var time: TextView
    private lateinit var icon: ImageView
    private lateinit var animationView: LottieAnimationView
    private lateinit var progressBar: ProgressBar

    var url: String? = null

    var completed = false

    var isMini = false
        set(value) {
            field = value
            reloadView()
        }
    var duration = 0
        set(value) {
            field = value
            if (!Manager.isCurrent(this)) setText(calculateTime(duration / 1000))
        }

    init {
        initView()
    }

    private fun reloadView() {
        val layoutParams = animationView.layoutParams
        if (isMini) {
            layoutParams.width = DisplayUtil.dp2px(context, 64f)
            layoutParams.height = DisplayUtil.dp2px(context, 12f)
            setPadding(
                DisplayUtil.dp2px(context, 4f), DisplayUtil.dp2px(
                    context, 2f
                ), DisplayUtil.dp2px(context, 4f), DisplayUtil.dp2px(
                    context, 2f
                )
            )
        } else {
            layoutParams.width = DisplayUtil.dp2px(context, 96f)
            layoutParams.height = DisplayUtil.dp2px(context, 18f)
            setPadding(
                DisplayUtil.dp2px(context, 8f), DisplayUtil.dp2px(
                    context, 4f
                ), DisplayUtil.dp2px(context, 8f), DisplayUtil.dp2px(
                    context, 4f
                )
            )
        }
        animationView.layoutParams = layoutParams
    }

    private fun initView() {
        backgroundTintList = ColorStateList.valueOf(
            ThemeUtils.getColorByAttr(
                context,
                R.attr.colorAccent
            )
        )
        setBackgroundResource(R.drawable.bg_audio)
        setOnClickListener(this)
        setOnLongClickListener(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            foreground = ContextCompat.getDrawable(context, R.drawable.fg_ripple_radius_50dp)
        }
        inflate(context, R.layout.layout_audio, this)
        time = findViewById(R.id.audio_text)
        icon = findViewById(R.id.audio_play_icon)
        animationView = findViewById<LottieAnimationView>(R.id.audio_wave_anim).apply {
            val colorRes: Int = R.color.default_color_primary
            val csl = ColorStateListUtils.createColorStateList(context, colorRes)
            val filter = SimpleColorFilter(csl.defaultColor)
            val keyPath = KeyPath("**")
            val callback = LottieValueCallback<ColorFilter>(filter)
            addValueCallback(keyPath, LottieProperty.COLOR_FILTER, callback)
        }
        progressBar = findViewById(R.id.audio_play_progress)
        reloadView()
    }

    fun calculateTime(sec: Int): String {
        val min = sec / 60
        return if (min > 0) {
            min.toString() + "'" + sec % 60 + "''"
        } else {
            "$sec''"
        }
    }

    fun setText(text: String?) {
        time.text = text
    }

    override fun onLongClick(v: View): Boolean {
        if (url == null) return false
        val popupMenu = PopupUtil.create(this)
        popupMenu.inflate(R.menu.menu_audio_long_click)
        popupMenu.setOnMenuItemClickListener(this)
        popupMenu.show()
        return true
    }

    override fun onMenuItemClick(item: MenuItem): Boolean {
        if (item.itemId == R.id.menu_download) {
            if (url != null) {
                val uri = Uri.parse(url)
                val md5 = uri.getQueryParameter("voice_md5")
                FileUtil.downloadBySystem(
                    context,
                    FileUtil.FILE_TYPE_AUDIO,
                    url,
                    (md5 ?: System.currentTimeMillis().toString()) + ".mp3"
                )
            }
            return true
        }
        return false
    }

    fun reset() {
        Manager.detach(this)
        resetUi()
    }

    private fun resetUi() {
        completed = false
        setState(STATE_PAUSING)
        animationView.visibility = GONE
        setText(calculateTime(duration / 1000))
    }

    fun startPlay() = startPlay(checkNotNull(url) { "Url is null." })

    private fun setState(@IconState state: Int) {
        when (state) {
            STATE_LOADING -> {
                icon.visibility = GONE
                progressBar.visibility = VISIBLE
                animationView.pauseAnimation()
            }

            STATE_PLAYING -> {
                icon.visibility = VISIBLE
                icon.setImageResource(R.drawable.ic_round_pause_circle_filled_18dp)
                progressBar.visibility = GONE
                animationView.playAnimation()
            }

            STATE_PAUSING -> {
                icon.visibility = VISIBLE
                icon.setImageResource(R.drawable.ic_round_play_circle_filled_18dp)
                progressBar.visibility = GONE
                animationView.pauseAnimation()
            }
        }
    }

    fun startPlay(url: String?) {
        val source = checkNotNull(url) { "Url is null." }
        this.url = source
        resetUi()
        Manager.start(this, source)
    }

    fun release() {
        Manager.detach(this)
        resetUi()
    }

    override fun onDetachedFromWindow() {
        release()
        super.onDetachedFromWindow()
    }

    override fun onClick(v: View) = toggleStatus()

    fun toggleStatus() {
        when {
            !Manager.isCurrent(this) || completed -> startPlay()
            Manager.isPlaying(this) -> Manager.pause(this)
            else -> play()
        }
    }

    fun play() {
        if (Manager.isCurrent(this)) Manager.resume(this) else startPlay()
    }

    @IntDef(STATE_LOADING, STATE_PLAYING, STATE_PAUSING)
    @Retention(AnnotationRetention.SOURCE)
    private annotation class IconState

    /** One engine for speech playback; rows only own their binding, never another row's engine. */
    object Manager : Player.Listener {
        private val owner = PlaybackOwner<VoicePlayerView>()
        private var exoPlayer: ExoPlayer? = null
        private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        private var progressJob: Job? = null

        fun isCurrent(view: VoicePlayerView): Boolean = owner.owns(view)

        fun isPlaying(view: VoicePlayerView): Boolean =
            owner.owns(view) && exoPlayer?.playWhenReady == true

        @OptIn(UnstableApi::class)
        private fun getPlayer(context: Context): ExoPlayer {
            return exoPlayer ?: ExoPlayer.Builder(context.applicationContext)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(C.USAGE_MEDIA)
                        .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
                        .build(), true
                )
                .setHandleAudioBecomingNoisy(true)
                .setRenderersFactory(
                    DefaultRenderersFactory(context.applicationContext)
                        .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_PREFER)
                )
                .build()
                .also {
                    exoPlayer = it
                    it.addListener(this)
                }
        }

        fun start(view: VoicePlayerView, url: String) {
            stopProgress()
            // Detach the old UI before stop() can dispatch state changes for the new media.
            owner.clear()?.resetUi()
            val player = getPlayer(view.context)
            player.stop()
            owner.replace(view)
            view.completed = false
            view.setState(STATE_LOADING)
            player.setMediaItem(MediaItem.fromUri(url))
            player.playWhenReady = true
            player.prepare()
        }

        fun pause(view: VoicePlayerView) {
            if (!owner.owns(view)) return
            exoPlayer?.pause()
            stopProgress()
            view.setState(STATE_PAUSING)
        }

        fun resume(view: VoicePlayerView) {
            if (!owner.owns(view)) return
            if (view.completed) {
                start(view, checkNotNull(view.url))
            } else {
                exoPlayer?.play()
            }
        }

        fun detach(view: VoicePlayerView) {
            if (!owner.detach(view)) return
            releasePlayer()
        }

        /** A stopping Activity cannot release playback started by a different Activity. */
        fun releaseForContext(context: Context) {
            val view = owner.get()
            if (view == null || view.context.findActivity() === context.findActivity()) release()
        }

        fun release() {
            val previous = owner.clear()
            releasePlayer()
            previous?.resetUi()
        }

        private fun releasePlayer() {
            stopProgress()
            val previous = exoPlayer
            exoPlayer = null
            previous?.removeListener(this)
            previous?.release()
        }

        private fun stopProgress() {
            progressJob?.cancel()
            progressJob = null
        }

        private fun updateProgress() {
            val view = owner.get() ?: return
            val player = exoPlayer ?: return
            view.setText(view.calculateTime((player.currentPosition / 1000).toInt()))
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            val view = owner.get() ?: return
            when (playbackState) {
                Player.STATE_BUFFERING -> {
                    view.setState(if (exoPlayer?.playWhenReady == true) STATE_LOADING else STATE_PAUSING)
                }
                Player.STATE_READY -> {
                    view.animationView.visibility = VISIBLE
                    view.setState(if (exoPlayer?.isPlaying == true) STATE_PLAYING else STATE_PAUSING)
                    updateProgress()
                }
                Player.STATE_ENDED -> {
                    stopProgress()
                    view.completed = true
                    view.setState(STATE_PAUSING)
                    view.setText(view.calculateTime(view.duration / 1000))
                }
                Player.STATE_IDLE -> {
                    stopProgress()
                    view.setState(STATE_PAUSING)
                }
            }
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            stopProgress()
            val view = owner.get() ?: return
            if (isPlaying) {
                view.setState(STATE_PLAYING)
                progressJob = scope.launch {
                    while (isActive && exoPlayer?.isPlaying == true) {
                        updateProgress()
                        delay(1000)
                    }
                }
            } else if (exoPlayer?.playbackState != Player.STATE_BUFFERING ||
                exoPlayer?.playWhenReady != true
            ) {
                view.setState(STATE_PAUSING)
                updateProgress()
            }
        }

        override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
            if (!playWhenReady) {
                stopProgress()
                owner.get()?.setState(STATE_PAUSING)
            } else if (exoPlayer?.playbackState == Player.STATE_BUFFERING) {
                owner.get()?.setState(STATE_LOADING)
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            stopProgress()
            owner.get()?.let {
                it.completed = true // The next click retries preparation rather than a released/error state.
                it.setState(STATE_PAUSING)
            }
            Log.w(TAG, "Voice playback failed: ${error.errorCodeName}")
        }
    }

    companion object {
        const val TAG = "AudioView"
        const val STATE_LOADING = 0
        const val STATE_PLAYING = 1
        const val STATE_PAUSING = 2
    }
}
