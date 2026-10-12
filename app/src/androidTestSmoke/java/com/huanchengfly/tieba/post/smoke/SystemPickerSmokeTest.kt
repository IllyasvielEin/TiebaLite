package com.huanchengfly.tieba.post.smoke

import android.content.Intent
import android.content.pm.PackageManager
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts.PickVisualMedia
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

/** Actual cross-app system Picker launch + Back. No mocked result dispatch in this test. */
class SystemPickerSmokeTest {
    @Test fun actualSystemPickerCanBeCancelledTwiceWithoutChangingSelection() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val device = UiDevice.getInstance(instrumentation)
        ActivityScenario.launch(SmokeActivity::class.java).use { scenario ->
            var pickerPackage = ""
            var appPackage = ""
            val callbacks = AtomicInteger()
            scenario.onActivity { activity ->
                appPackage = activity.packageName
                assertTrue(PickVisualMedia.isPhotoPickerAvailable(activity))
                val intent = PickVisualMedia().createIntent(activity,
                    PickVisualMediaRequest(PickVisualMedia.ImageOnly))
                assertEquals("android.provider.action.PICK_IMAGES", intent.action)
                val resolved = activity.packageManager.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
                pickerPackage = checkNotNull(resolved).activityInfo.packageName
                assertNotEquals(appPackage, pickerPackage)
            }
            repeat(2) { index ->
                scenario.onActivity { it.launchSystemPicker() }
                assertTrue("System Picker UI did not appear",
                    device.wait(Until.hasObject(By.pkg(pickerPackage).depth(0)), 15_000))
                device.pressBack()
                assertTrue("Host did not return after Back",
                    device.wait(Until.hasObject(By.pkg(appPackage).depth(0)), 15_000))
                instrumentation.waitForIdleSync()
                scenario.onActivity {
                    callbacks.set(it.pickerCallbacks)
                    assertNull(it.selectedImage)
                }
                assertEquals(index + 1, callbacks.get())
            }
        }
    }
}
