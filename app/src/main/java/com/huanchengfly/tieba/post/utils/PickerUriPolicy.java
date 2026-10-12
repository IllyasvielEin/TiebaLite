package com.huanchengfly.tieba.post.utils;

/** Only a provider-backed selected item may enter the generic image loaders. */
public final class PickerUriPolicy {
    private PickerUriPolicy() {}

    public static boolean isAllowed(String scheme, String authority) {
        return "content".equals(scheme) && authority != null && !authority.trim().isEmpty();
    }
}
