package com.huanchengfly.tieba.post.diagnostics;

import com.huanchengfly.tieba.post.security.PublicDownloadPolicyException;

import java.io.IOException;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.function.Consumer;
import javax.net.ssl.SSLException;
import javax.net.ssl.SSLHandshakeException;
import javax.net.ssl.SSLPeerUnverifiedException;

/** Memory-only, finite diagnostic vocabulary. No request, URL, ID, header or Throwable is retained. */
public final class AvatarDiagnosticStore {
    public static final int MAX_EVENTS = 40;
    public enum Source { AVATAR, AVATAR_SNAPSHOT, NETWORK }
    public enum InputKind { EMPTY, PORTRAIT_ID, HTTP_URL, HTTPS_URL, LOCAL, OTHER }
    public enum Host { AVATAR_CDN, HIMG_CDN, OTHER, NONE }
    public enum Stage {
        START, DNS, CONNECT, TLS, TLS_OK, RESPONSE, COMPLETE,
        SUCCESS_NETWORK, SUCCESS_DOWNLOAD_CACHE, SUCCESS_MEMORY_OR_RESULT_CACHE,
        SUCCESS_OTHER, ERROR, CANCELLED, OBSERVATION_ENDED
    }
    public enum Category {
        NONE, EMPTY_INPUT, DNS, TIMEOUT, TLS_CERTIFICATE, TLS_HANDSHAKE, TLS,
        BLOCKED_METHOD, BLOCKED_CREDENTIALS, BLOCKED_HTTP, IO_OR_HTTP, OTHER
    }
    public enum RedirectScheme { NONE, HTTPS, HTTP, OTHER }

    public static final class Lease {
        private final long generation;
        public final Source source;
        public final InputKind inputKind;
        public final Host host;
        private Lease(long generation, Source source, InputKind inputKind, Host host) {
            this.generation = generation;
            this.source = source;
            this.inputKind = inputKind;
            this.host = host;
        }
    }

    public static final class Event {
        public final Source source;
        public final InputKind inputKind;
        public final Host host;
        public final Stage stage;
        public final Category category;
        public final int httpStatus;
        public final RedirectScheme redirectScheme;
        public final Host redirectHost;
        private Event(Lease lease, Stage stage, Category category, int httpStatus,
                      RedirectScheme redirectScheme, Host redirectHost) {
            this.source = lease.source;
            this.inputKind = lease.inputKind;
            this.host = lease.host;
            this.stage = stage;
            this.category = category;
            this.httpStatus = httpStatus >= 100 && httpStatus <= 599 ? httpStatus : 0;
            this.redirectScheme = redirectScheme;
            this.redirectHost = redirectHost;
        }
    }

    public static final class Snapshot {
        public final boolean enabled;
        public final long generation;
        public final long dropped;
        public final List<Event> events;
        private Snapshot(boolean enabled, long generation, long dropped, List<Event> events) {
            this.enabled = enabled;
            this.generation = generation;
            this.dropped = dropped;
            this.events = Collections.unmodifiableList(new ArrayList<>(events));
        }
        public String report() {
            StringBuilder out = new StringBuilder("Avatar diagnostics v1 (local, memory only)\n");
            out.append("enabled=").append(enabled).append(" events=").append(events.size())
                    .append(" dropped=").append(dropped).append('\n');
            out.append("AVATAR = observed display transitions; AVATAR_SNAPSHOT = current state, possibly loaded before enabling.\n");
            out.append("NETWORK = allowlisted legacy/HIMG portrait-route stages; host is the original request host, not a proven contacted/failure host after route migration or redirects.\n");
            out.append("Entries are independent, not correlated by timing. Missing NETWORK entries do not prove a cache hit.\n");
            for (Event event : events) {
                out.append(event.source).append(" input=").append(event.inputKind)
                        .append(" host=").append(hostLabel(event.host))
                        .append(" stage=").append(event.stage)
                        .append(" category=").append(event.category);
                if (event.httpStatus != 0) out.append(" status=").append(event.httpStatus);
                if (event.redirectScheme != RedirectScheme.NONE) {
                    out.append(" redirect=").append(event.redirectScheme)
                            .append("/").append(hostLabel(event.redirectHost));
                }
                out.append('\n');
            }
            return out.toString();
        }
    }

    private boolean enabled;
    private long generation;
    private long dropped;
    private final ArrayList<Event> events = new ArrayList<>();
    private Consumer<Snapshot> observer;

    public synchronized Snapshot snapshot() {
        return new Snapshot(enabled, generation, dropped, events);
    }

    /** A single process-owned observer publishes sanitized state; it is never an Activity. */
    public synchronized void observe(Consumer<Snapshot> observer) {
        this.observer = observer;
        publish();
    }

    public synchronized void setEnabled(boolean enabled) {
        if (this.enabled == enabled) return;
        this.enabled = enabled;
        resetSession();
    }

    public synchronized void clear() { resetSession(); }

    private void resetSession() {
        generation++;
        events.clear();
        dropped = 0;
        publish();
    }

    public synchronized Lease open(Source source, InputKind inputKind, Host host) {
        return enabled ? new Lease(generation, source, inputKind, host) : null;
    }

    /** Atomic generation binding prevents a delayed observation from leasing a later session. */
    public synchronized Lease openForGeneration(long expectedGeneration, Source source, InputKind inputKind, Host host) {
        return enabled && generation == expectedGeneration
                ? new Lease(generation, source, inputKind, host) : null;
    }

    public void record(Lease lease, Stage stage) {
        record(lease, stage, Category.NONE, 0, RedirectScheme.NONE, Host.NONE);
    }

    public void recordError(Lease lease, Throwable failure) {
        if (lease == null) return;
        Category category = lease.inputKind == InputKind.EMPTY ? Category.EMPTY_INPUT : classifyFailure(failure);
        Stage stage = category == Category.NONE && isCancellation(failure) ? Stage.CANCELLED : Stage.ERROR;
        record(lease, stage, category, 0, RedirectScheme.NONE, Host.NONE);
    }

    public synchronized void record(Lease lease, Stage stage, Category category, int httpStatus,
                                    RedirectScheme redirectScheme, Host redirectHost) {
        if (!enabled || lease == null || lease.generation != generation) return;
        if (events.size() == MAX_EVENTS) {
            events.remove(0);
            if (dropped < Long.MAX_VALUE) dropped++;
        }
        events.add(new Event(lease, stage, category, httpStatus, redirectScheme, redirectHost));
        publish();
    }

    private void publish() {
        if (observer != null) observer.accept(snapshot());
    }

    public static InputKind classifyInput(String input) {
        if (input == null || input.isEmpty()) return InputKind.EMPTY;
        try {
            URI uri = new URI(input);
            String scheme = uri.getScheme();
            if ("http".equalsIgnoreCase(scheme)) return InputKind.HTTP_URL;
            if ("https".equalsIgnoreCase(scheme)) return InputKind.HTTPS_URL;
            if ("content".equalsIgnoreCase(scheme) || "file".equalsIgnoreCase(scheme)
                    || "android.resource".equalsIgnoreCase(scheme) || "asset".equalsIgnoreCase(scheme)
                    || "resource".equalsIgnoreCase(scheme)) return InputKind.LOCAL;
            if (scheme != null || input.startsWith("//") || input.trim().isEmpty()) return InputKind.OTHER;
            return InputKind.PORTRAIT_ID;
        } catch (Exception ignored) {
            return InputKind.OTHER;
        }
    }

    public static Host hostFromInput(String input) {
        if (input == null || input.isEmpty()) return Host.NONE;
        try {
            URI uri = new URI(input);
            return uri.getHost() == null ? Host.NONE : classifyHost(uri.getHost());
        } catch (Exception ignored) {
            return Host.OTHER;
        }
    }

    public static Host classifyHost(String host) {
        if (host == null || host.isEmpty()) return Host.NONE;
        if ("tb.himg.baidu.com".equalsIgnoreCase(host)) return Host.AVATAR_CDN;
        return "himg.bdimg.com".equalsIgnoreCase(host) ? Host.HIMG_CDN : Host.OTHER;
    }

    private static String hostLabel(Host host) {
        if (host == Host.AVATAR_CDN) return "tb.himg.baidu.com";
        if (host == Host.HIMG_CDN) return "himg.bdimg.com";
        return host == Host.NONE ? "none" : "other";
    }

    public static Category classifyFailure(Throwable failure) {
        Throwable cursor = failure;
        Category fallback = Category.OTHER;
        // Exception messages and runtime class names can contain URLs or secrets. Never inspect them.
        for (int i = 0; cursor != null && i < 8; i++, cursor = cursor.getCause()) {
            if (cursor instanceof CancellationException) return Category.NONE;
            if (cursor instanceof PublicDownloadPolicyException) {
                switch (((PublicDownloadPolicyException) cursor).getReason()) {
                    case METHOD: return Category.BLOCKED_METHOD;
                    case CREDENTIALS: return Category.BLOCKED_CREDENTIALS;
                    default: return Category.BLOCKED_HTTP;
                }
            }
            if (cursor instanceof UnknownHostException) return Category.DNS;
            if (cursor instanceof SocketTimeoutException) return Category.TIMEOUT;
            if (cursor instanceof SSLPeerUnverifiedException) return Category.TLS_CERTIFICATE;
            if (cursor instanceof SSLHandshakeException) return Category.TLS_HANDSHAKE;
            if (cursor instanceof SSLException) fallback = Category.TLS;
            else if (cursor instanceof IOException && fallback == Category.OTHER) fallback = Category.IO_OR_HTTP;
        }
        return fallback;
    }

    private static boolean isCancellation(Throwable failure) {
        Throwable cursor = failure;
        for (int i = 0; cursor != null && i < 8; i++, cursor = cursor.getCause()) {
            if (cursor instanceof CancellationException) return true;
        }
        return false;
    }
}
