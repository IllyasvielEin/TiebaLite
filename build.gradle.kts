// Top-level build file where you can add configuration options common to all sub-projects/modules.
buildscript {
    dependencies {
        // AGP 9 supplies Kotlin support. Keep its compiler aligned with the
        // Compose, Serialization, and Parcelize plugins instead of its default KGP.
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:${libs.versions.kotlin.get()}")
    }
}

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose.compiler) apply false
    alias(libs.plugins.kotlin.ksp) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.parcelize) apply false
    alias(libs.plugins.hilt.android) apply false
    alias(libs.plugins.wire) apply false

    // This pinned Dependency Analysis plugin predates AGP 9 and remains disabled.
    // alias(libs.plugins.dependency.analysis)
}

tasks.register<Delete>("clean") {
    delete(layout.buildDirectory.asFile.get())
}
