package com.huanchengfly.tieba.post.utils;

import org.junit.Test;
import static org.junit.Assert.assertEquals;

public class MobileInfoUtilTest {
    @Test public void imeiCompatibilityFieldNeverNeedsADeviceOrPermission() {
        assertEquals("000000000000000", MobileInfoUtil.getIMEI(null));
        assertEquals(MobileInfoUtil.DEFAULT_IMEI, MobileInfoUtil.getIMEI(null));
    }
}
