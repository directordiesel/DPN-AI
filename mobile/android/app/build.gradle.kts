plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val releaseVersionCode = providers.gradleProperty("DPN_MOBILE_VERSION_CODE").orNull?.toIntOrNull() ?: 1
val releaseVersionName = providers.gradleProperty("DPN_MOBILE_VERSION_NAME").orNull ?: "1.0.0-dev"
val signingStoreFile = providers.gradleProperty("DPN_MOBILE_KEYSTORE").orNull
val signingStorePassword = providers.gradleProperty("DPN_MOBILE_STORE_PASSWORD").orNull
val signingKeyAlias = providers.gradleProperty("DPN_MOBILE_KEY_ALIAS").orNull
val signingKeyPassword = providers.gradleProperty("DPN_MOBILE_KEY_PASSWORD").orNull
val hasCompleteSigningConfig = listOf(signingStoreFile, signingStorePassword, signingKeyAlias, signingKeyPassword).all { !it.isNullOrBlank() }

android {
    namespace = "com.dpntechnology.dpnai"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.dpntechnology.dpnai"
        minSdk = 26
        targetSdk = 36
        versionCode = releaseVersionCode
        versionName = releaseVersionName
    }

    signingConfigs {
        if (hasCompleteSigningConfig) {
            create("release") {
                storeFile = file(signingStoreFile!!)
                storePassword = signingStorePassword
                keyAlias = signingKeyAlias
                keyPassword = signingKeyPassword
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }

    buildTypes {
        debug {
            isDebuggable = true
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isDebuggable = false
            isMinifyEnabled = true
            isShrinkResources = true
            signingConfig = if (hasCompleteSigningConfig) signingConfigs.getByName("release") else null
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    buildFeatures {
        buildConfig = true
    }

    lint {
        abortOnError = true
        checkReleaseBuilds = true
        warningsAsErrors = true
        // Mobile v1 is intentionally English-only. Keep every compatibility,
        // security, privacy, API, and correctness lint rule fatal while deferring
        // localization-resource migration to the localization release track.
        disable += "SetTextI18n"
    }

    packaging {
        resources.excludes += setOf(
            "META-INF/DEPENDENCIES",
            "META-INF/LICENSE*",
            "META-INF/NOTICE*",
        )
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

tasks.register("verifyReleaseReadiness") {
    group = "verification"
    description = "Fail closed unless DPN AI Mobile release versioning and signing inputs are explicitly configured."
    doLast {
        require(releaseVersionCode > 0) { "DPN_MOBILE_VERSION_CODE must be a positive integer" }
        require(Regex("^\\d+\\.\\d+\\.\\d+$").matches(releaseVersionName)) {
            "DPN_MOBILE_VERSION_NAME must be a production semantic version such as 1.0.0"
        }
        require(hasCompleteSigningConfig) {
            "Release signing is not configured. Supply DPN_MOBILE_KEYSTORE, DPN_MOBILE_STORE_PASSWORD, DPN_MOBILE_KEY_ALIAS, and DPN_MOBILE_KEY_PASSWORD outside source control."
        }
        require(file(signingStoreFile!!).isFile) { "Configured release keystore does not exist" }
    }
}
