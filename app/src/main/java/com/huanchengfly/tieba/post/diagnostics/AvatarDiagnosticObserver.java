package com.huanchengfly.tieba.post.diagnostics;

import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.*;

/** Observe sanitized Compose load states without changing or restarting the image request. */
public final class AvatarDiagnosticObserver {
    private final AvatarDiagnosticStore store;
    private final InputKind inputKind;
    private final Host host;
    private long generation = -1;
    private boolean enabled;
    private int lastTransition;
    private boolean allowInitialTerminal;
    private Lease lease;

    public AvatarDiagnosticObserver(AvatarDiagnosticStore store, InputKind inputKind, Host host) {
        this.store = store;
        this.inputKind = inputKind;
        this.host = host;
    }

    public void observe(boolean enabled, long generation, int transition, Stage stage, Category category) {
        if (this.generation != generation) {
            boolean first = this.generation == -1;
            boolean justEnabled = enabled && !this.enabled;
            lease = null;
            allowInitialTerminal = first && enabled && stage == null;
            if (justEnabled && stage != null) {
                Lease snapshotLease = recordSnapshot(generation, stage, category);
                // A newly mounted observer may first see Started; keep its result labeled as a snapshot.
                if (first && stage == Stage.START) lease = snapshotLease;
            }
            this.generation = generation;
            this.enabled = enabled;
            lastTransition = transition;
            return;
        }
        if (!enabled || stage == null || transition == lastTransition) return;
        lastTransition = transition;
        if (stage == Stage.START) {
            lease = store.openForGeneration(generation, Source.AVATAR, inputKind, host);
            allowInitialTerminal = false;
        }
        if (lease != null) {
            record(lease, stage, category);
            if (stage != Stage.START) lease = null;
        } else if (allowInitialTerminal) {
            // snapshotFlow can conflate a very fast start/result, especially memory-cache hits.
            recordSnapshot(generation, stage, category);
            allowInitialTerminal = false;
        }
    }

    private Lease recordSnapshot(long generation, Stage stage, Category category) {
        Lease snapshotLease = store.openForGeneration(generation, Source.AVATAR_SNAPSHOT, inputKind, host);
        record(snapshotLease, stage, category);
        return snapshotLease;
    }

    private void record(Lease lease, Stage stage, Category category) {
        if (stage == Stage.ERROR && inputKind == InputKind.EMPTY) category = Category.EMPTY_INPUT;
        store.record(lease, stage, category, 0, RedirectScheme.NONE, Host.NONE);
    }

    public void close() {
        // Disposing this observer is not proof that the underlying request was cancelled.
        if (lease != null) store.record(lease, Stage.OBSERVATION_ENDED);
        lease = null;
    }
}
