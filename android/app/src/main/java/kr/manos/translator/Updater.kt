package kr.manos.translator

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.provider.Settings
import org.json.JSONArray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 앱 자동 업데이트.
 * 새 버전(android-숫자)을 깃허브에서 찾아 → 받아 두고 → 설치를 요청해요.
 * 안드로이드 보안 규칙상 구글 장터 밖의 앱은 대부분 설치 확인을 한 번 눌러야 하고, 그땐 알림으로 알려 줘요.
 */
object Updater {
    /** 업데이트 파일을 올려 두는 저장소 (코드 저장소를 비공개로 바꾸면 공개용 업데이트 저장소로 바꿔야 함). */
    const val REPO = "manoskpm/manos-wechat"
    private const val APK_NAME = "ManosTranslator-Android.apk"
    private const val CHANNEL = "update"
    const val ACTION_RESULT = "kr.manos.translator.INSTALL_RESULT"
    private val busy = AtomicBoolean(false)

    private class Remote(val ver: Int, val url: String, val size: Long)

    fun currentVersion(ctx: Context): Int = try {
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName?.toIntOrNull() ?: 0
    } catch (e: Exception) {
        0
    }

    private fun get(url: String): String {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.connectTimeout = 15000
            c.readTimeout = 30000
            c.setRequestProperty("User-Agent", "ManosTranslator-Android")
            c.setRequestProperty("Accept", "application/vnd.github+json")
            if (c.responseCode !in 200..299) throw java.io.IOException("HTTP " + c.responseCode)
            return c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    private fun fetchLatest(): Remote? {
        val arr = JSONArray(get("https://api.github.com/repos/$REPO/releases?per_page=30"))
        var best: Remote? = null
        for (i in 0 until arr.length()) {
            val r = arr.getJSONObject(i)
            val tag = r.optString("tag_name")
            if (!tag.startsWith("android-") || r.optBoolean("draft")) continue
            val n = tag.removePrefix("android-").toIntOrNull() ?: continue
            val assets = r.optJSONArray("assets") ?: continue
            for (j in 0 until assets.length()) {
                val a = assets.getJSONObject(j)
                if (a.optString("name") == APK_NAME && (best == null || n > best.ver)) {
                    best = Remote(n, a.optString("browser_download_url"), a.optLong("size"))
                }
            }
        }
        return best
    }

    private fun download(url: String, dest: File) {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.connectTimeout = 15000
            c.readTimeout = 60000
            c.setRequestProperty("User-Agent", "ManosTranslator-Android")
            if (c.responseCode !in 200..299) throw java.io.IOException("HTTP " + c.responseCode)
            val part = File(dest.path + ".part")
            c.inputStream.use { input -> part.outputStream().use { out -> input.copyTo(out) } }
            if (!part.renameTo(dest)) throw java.io.IOException("파일 이름 바꾸기 실패")
        } finally {
            c.disconnect()
        }
    }

    /** 새 버전 확인 → 받기 → 설치 요청. 반드시 백그라운드 스레드에서 부르세요. */
    fun run(ctx: Context) {
        if (!busy.compareAndSet(false, true)) return
        try {
            Store.init(ctx)
            Store.lastUpdateCheck = System.currentTimeMillis()
            val cur = currentVersion(ctx)
            val remote = fetchLatest()
            if (remote == null || remote.ver <= cur) {
                Store.updateState = "최신 버전이에요 (v$cur)"
                return
            }
            val apk = File(ctx.cacheDir, "update-${remote.ver}.apk")
            if (!apk.exists() || (remote.size > 0 && apk.length() != remote.size)) {
                Store.updateState = "새 버전 v${remote.ver} 받는 중…"
                download(remote.url, apk)
            }
            ctx.cacheDir.listFiles()?.forEach { if (it.name.startsWith("update-") && it != apk) it.delete() }
            if (!ctx.packageManager.canRequestPackageInstalls()) {
                Store.updateState = "새 버전 v${remote.ver} 준비됨 · [설치 허용]을 눌러 주세요"
                notify(ctx, "새 버전 v${remote.ver}이 준비됐어요. 앱을 열어 [설치 허용]을 한 번만 켜 주세요.", null)
                return
            }
            Store.updateState = "새 버전 v${remote.ver} 설치 요청 중…"
            install(ctx, apk)
        } catch (e: Exception) {
            Store.updateState = "업데이트 확인 실패 (인터넷을 확인해 주세요)"
        } finally {
            busy.set(false)
        }
    }

    private fun install(ctx: Context, apk: File) {
        val installer = ctx.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        if (Build.VERSION.SDK_INT >= 31) {
            // 이 앱이 설치한 앱이면 묻지 않고 바꿔 줄 수도 있음 (폰에 따라 다름)
            params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        }
        val id = installer.createSession(params)
        val session = installer.openSession(id)
        apk.inputStream().use { input ->
            session.openWrite("app", 0, apk.length()).use { out ->
                input.copyTo(out)
                session.fsync(out)
            }
        }
        val pi = PendingIntent.getBroadcast(
            ctx, id, Intent(ctx, InstallReceiver::class.java).setAction(ACTION_RESULT),
            PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        session.commit(pi.intentSender)
        session.close()
    }

    fun notify(ctx: Context, text: String, open: PendingIntent?) {
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "앱 업데이트", NotificationManager.IMPORTANCE_DEFAULT))
        val b = Notification.Builder(ctx, CHANNEL)
            .setContentTitle("바로통 업데이트")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setAutoCancel(true)
        if (open != null) b.setContentIntent(open)
        nm.notify(2, b.build())
    }
}

/** 설치 결과를 받는 곳: 확인이 필요하면 알림으로 알려 줌. */
class InstallReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        Store.init(ctx)
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -1)
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm: Intent? = if (Build.VERSION.SDK_INT >= 33) {
                    intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                }
                if (confirm != null) {
                    confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    val pi = PendingIntent.getActivity(
                        ctx, 3, confirm, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
                    )
                    Store.updateState = "새 버전 준비됨 · 알림을 눌러 [설치]를 눌러 주세요"
                    Updater.notify(ctx, "새 버전이 준비됐어요. 눌러서 설치하세요.", pi)
                }
            }
            PackageInstaller.STATUS_SUCCESS -> Store.updateState = "업데이트 완료"
            else -> {
                val msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: ""
                Store.updateState = "설치 실패: " + msg.take(80) +
                    " (예전 방식으로 설치한 앱이면 앱을 지우고 새로 설치해야 해요)"
            }
        }
    }
}

/** 앱이 업데이트로 다시 설치되면 초록 버튼을 자동으로 다시 켬. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        Store.init(ctx)
        if (Store.bubbleEnabled && Settings.canDrawOverlays(ctx)) {
            try {
                ctx.startForegroundService(Intent(ctx, BubbleService::class.java))
            } catch (e: Exception) {
                // 시스템이 막으면 앱을 열 때 다시 켜짐
            }
        }
    }
}
