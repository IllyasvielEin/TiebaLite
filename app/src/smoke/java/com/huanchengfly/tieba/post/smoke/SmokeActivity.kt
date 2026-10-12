package com.huanchengfly.tieba.post.smoke

import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.util.TypedValue
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts.PickVisualMedia
import androidx.appcompat.app.AppCompatActivity
import com.huanchengfly.tieba.post.ui.common.theme.interfaces.ThemeSwitcher
import com.huanchengfly.tieba.post.ui.common.theme.utils.ThemeUtils
import com.huanchengfly.tieba.post.utils.isPickerContentUri

/** Isolated host: no App singleton, production screen, account, crop/upload or theme persistence. */
class SmokeActivity : AppCompatActivity() {
    var pickerCallbacks = 0
        private set
    var selectedImage: Uri? = null
        private set

    private val systemPicker = registerForActivityResult(PickVisualMedia()) { uri ->
        pickerCallbacks++
        if (uri != null && uri.isPickerContentUri()) selectedImage = uri
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        // The production voice view needs colors, but not the account-aware App/ThemeDelegate.
        ThemeUtils.init(object : ThemeSwitcher {
            override fun getColorByAttr(context: Context, attrId: Int): Int {
                val value = TypedValue()
                context.theme.resolveAttribute(attrId, value, true)
                return if (value.resourceId != 0) context.getColor(value.resourceId) else value.data
            }
            override fun getColorById(context: Context, colorId: Int) = context.getColor(colorId)
        })
        super.onCreate(savedInstanceState)
    }

    fun launchSystemPicker() = systemPicker.launch(PickVisualMediaRequest(PickVisualMedia.ImageOnly))
}
