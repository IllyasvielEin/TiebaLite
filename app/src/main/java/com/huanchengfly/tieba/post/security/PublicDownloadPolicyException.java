package com.huanchengfly.tieba.post.security;

import java.io.IOException;

/** Fixed reasons only: diagnostics must never inspect a request or an exception message. */
public final class PublicDownloadPolicyException extends IOException {
    public enum Reason { METHOD, CREDENTIALS, INSECURE_TRANSPORT }

    private final Reason reason;

    public PublicDownloadPolicyException(Reason reason) {
        super(messageFor(reason));
        this.reason = reason;
    }

    public Reason getReason() { return reason; }

    private static String messageFor(Reason reason) {
        switch (reason) {
            case METHOD: return "Public downloads cannot submit request bodies";
            case CREDENTIALS: return "Credentials are not permitted in public download URLs";
            default: return "Insecure public download blocked";
        }
    }
}
