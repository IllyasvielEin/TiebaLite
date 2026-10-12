package com.huanchengfly.tieba.post.smoke

import android.app.Activity
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts.PickVisualMedia
import androidx.core.app.ActivityOptionsCompat
import androidx.core.content.FileProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.huanchengfly.tieba.post.utils.getClipDataUris
import com.huanchengfly.tieba.post.utils.isPickerContentUri
import org.junit.Assert.*
import org.junit.Test
import java.io.File

/** Injected results exercise AndroidX parsing + production URI gate, NOT system result selection. */
class PickerContractSmokeTest {
    private class ResultRegistry(val context: Context) : ActivityResultRegistry() {
        var requestCode = 0
        var requestIntent: Intent? = null
        override fun <I, O> onLaunch(code: Int, contract: ActivityResultContract<I, O>, input: I,
                                    options: ActivityOptionsCompat?) {
            requestCode = code
            requestIntent = contract.createIntent(context, input)
        }
        fun result(code: Int, uri: Uri?) = dispatchResult(requestCode, code,
            uri?.let { Intent().setData(it) })
    }

    @Test fun injectedAvatarAndThemeContractsKeepSelectionOnCancelAndRejectNonContentUris() {
        ActivityScenario.launch(SmokeActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val registry = ResultRegistry(activity)
                val original = Uri.parse("content://synthetic.invalid/previous")
                // Avatar and theme register independent single-image launchers with this shared gate.
                for (destination in listOf("avatar", "theme")) {
                    var selected = original
                    var accepted = 0
                    val launcher = registry.register(destination, PickVisualMedia()) { uri ->
                        if (uri != null && uri.isPickerContentUri()) { selected = uri; accepted++ }
                    }
                    try {
                        fun deliver(code: Int, uri: Uri?) {
                            launcher.launch(PickVisualMediaRequest(PickVisualMedia.ImageOnly))
                            assertEquals("image/*", registry.requestIntent?.type)
                            assertTrue(registry.result(code, uri))
                        }
                        deliver(Activity.RESULT_CANCELED, null)
                        deliver(Activity.RESULT_OK, null)
                        deliver(Activity.RESULT_OK, Uri.parse("file:///data/local/tmp/private.png"))
                        deliver(Activity.RESULT_OK, Uri.parse("https://example.invalid/image.png"))
                        deliver(Activity.RESULT_OK, Uri.parse("content:///missing-authority"))
                        assertEquals(original, selected)
                        assertEquals(0, accepted)
                        val folder = File(activity.cacheDir, "smoke-fixtures").apply { mkdirs() }
                        val file = File(folder, "$destination.png")
                        val bitmap = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888)
                        try { file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) } }
                        finally { bitmap.recycle() }
                        val uri = FileProvider.getUriForFile(activity,
                            "${activity.packageName}.smoke-fixtures", file)
                        deliver(Activity.RESULT_OK, uri)
                        assertEquals(uri, selected)
                        assertEquals(1, accepted)
                        activity.contentResolver.openInputStream(selected)!!.use {
                            assertTrue("Returned provider URI must actually be readable", it.read() >= 0)
                        }
                        deliver(Activity.RESULT_CANCELED, uri)
                        assertEquals(uri, selected)
                        assertEquals(1, accepted)
                        file.delete()
                    } finally { launcher.unregister() }
                }
            }
        }
    }

    @Test fun productionClipUriExtractionDeduplicatesAndFiltersUnsafeSchemes() {
        val first = Uri.parse("content://synthetic.invalid/one")
        val second = Uri.parse("content://synthetic.invalid/two")
        val intent = Intent().setData(first).apply {
            clipData = ClipData.newRawUri("synthetic", first).apply {
                addItem(ClipData.Item(Uri.parse("https://example.invalid/image.png")))
                addItem(ClipData.Item(Uri.parse("file:///tmp/private.png")))
                addItem(ClipData.Item(second))
                addItem(ClipData.Item(second))
            }
        }
        assertEquals(listOf(first, second), intent.getClipDataUris())
    }

    @Test fun targetAndInstrumentationPackagesReallyLackInternetPermission() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val manager = instrumentation.targetContext.packageManager
        for (context in listOf(instrumentation.context, instrumentation.targetContext)) {
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,
                manager.checkPermission(android.Manifest.permission.INTERNET, context.packageName))
        }
        assertEquals(android.app.Application::class.java,
            instrumentation.targetContext.applicationContext.javaClass)
    }
}
