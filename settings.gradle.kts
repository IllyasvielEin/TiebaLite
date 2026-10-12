pluginManagement {
    repositories {
        gradlePluginPortal()
        google()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        exclusiveContent {
            forRepository { maven("https://jitpack.io") }
            filter {
                includeGroup("com.github.stoyan-vuchev")
                includeGroup("com.github.gzu-liyujiang")
                includeGroup("com.github.lwj1994")
                includeGroup("com.github.getActivity")
                includeGroup("com.github.yalantis")
            }
        }
        exclusiveContent {
            forRepository { maven("https://developer.huawei.com/repo/") }
            filter { includeGroupByRegex("com\\.huawei\\..*") }
        }
        exclusiveContent {
            forRepository { maven("https://developer.hihonor.com/repo") }
            filter { includeGroupByRegex("com\\.hihonor\\..*") }
        }
    }
}

plugins {
    id("de.fayard.refreshVersions") version "0.60.6"
}

refreshVersions {
    rejectVersionIf {
          candidate.stabilityLevel.isLessStableThan(current.stabilityLevel)
    }
}

rootProject.name = "TiebaLite"
include(":app")
