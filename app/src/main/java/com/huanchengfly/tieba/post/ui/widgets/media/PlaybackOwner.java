package com.huanchengfly.tieba.post.ui.widgets.media;

import java.lang.ref.WeakReference;

/** Identity-based UI ownership: disposing another row cannot detach the active row. */
public final class PlaybackOwner<T> {
    private WeakReference<T> current = new WeakReference<>(null);

    public T get() { return current.get(); }

    public boolean owns(T owner) { return owner != null && current.get() == owner; }

    public T replace(T owner) {
        T previous = current.get();
        current = new WeakReference<>(owner);
        return previous;
    }

    public boolean detach(T owner) {
        if (!owns(owner)) return false;
        current.clear();
        return true;
    }

    public T clear() {
        T previous = current.get();
        current.clear();
        return previous;
    }
}
