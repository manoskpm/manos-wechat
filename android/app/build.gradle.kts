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

    // 서명 열쇠는 공개 저장소에 없고, 빌드할 때 비공개 보관소(초안 릴리스)에서 가져옴. 열쇠가 항상 같아야 업데이트가 됨.
    val ks = file("manos-android.keystore")
    signingConfigs {
        if (ks.exists()) {
            create("fixed") {
                storeFile = ks
                storePassword = "manos-android"
                keyAlias = "manos"
                keyPassword = "manos-android"
            }
        }
    }
    buildTypes {
        getByName("debug") {
            if (ks.exists()) signingConfig = signingConfigs.getByName("fixed")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
