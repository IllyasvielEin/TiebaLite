package com.huanchengfly.tieba.post.ui.widgets.media;

/** A main-thread-owned resource. Closing it never creates it or permits late work to recreate it. */
public final class PlaybackResource<T> {
    public interface Factory<T> { T create(); }
    public interface Releaser<T> { void release(T resource); }

    private final Factory<T> factory;
    private final Releaser<T> releaser;
    private boolean active;
    private T instance;

    public PlaybackResource(Factory<T> factory, Releaser<T> releaser) {
        this.factory = factory;
        this.releaser = releaser;
    }

    public void activate() { active = true; }

    public T getOrCreate() {
        if (!active) return null;
        if (instance == null) instance = factory.create();
        return instance;
    }

    public T peek() { return instance; }

    public void release() {
        active = false;
        T previous = instance;
        instance = null;
        if (previous != null) releaser.release(previous);
    }
}
