package com.huanchengfly.tieba.post.utils;

import android.content.Context;

public class MobileInfoUtil {
    public static final String DEFAULT_IMEI = "000000000000000";

    /** Keep legacy request fields compatible without collecting a hardware identifier. */
    public static String getIMEI(Context context) {
        return DEFAULT_IMEI;
    }
}
