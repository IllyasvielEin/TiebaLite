package com.huanchengfly.tieba.post.utils;

import java.io.File;
import java.io.IOException;
import java.util.regex.Pattern;

/** Treat remote/cache IDs as opaque basenames, never as filesystem paths. */
public final class EmoticonCachePath {
    private static final Pattern SAFE_ID = Pattern.compile("[A-Za-z0-9_-]{1,128}");

    private EmoticonCachePath() {}

    public static boolean isValidId(String id) {
        return id != null && SAFE_ID.matcher(id).matches();
    }

    /** Also reject existing symlinks that resolve outside the intended cache directory. */
    public static File resolve(File directory, String id) {
        if (!isValidId(id)) return null;
        try {
            File parent = directory.getCanonicalFile();
            File candidate = new File(parent, id + ".png").getCanonicalFile();
            return parent.equals(candidate.getParentFile()) ? candidate : null;
        } catch (IOException | SecurityException ignored) {
            return null;
        }
    }
}
