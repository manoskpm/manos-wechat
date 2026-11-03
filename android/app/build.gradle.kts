plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "kr.manos.translator"
    compileSdk = 34

    defaultConfig {
        applicationId = "kr.manos.translator"
        minSdk = 26
        targetSdk = 34
        versionCode = (project.findProperty("vcode") as String? ?: "1").toInt()
        versionName = (project.findProperty("vname") as String? ?: "1")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
