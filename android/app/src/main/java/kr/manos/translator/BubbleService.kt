package kr.manos.translator

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.TextView

/** 다른 앱(위챗·1688) 위에 떠 있는 초록 "번" 버튼. 누르면 번역, 길게 누르면 답장 쓰기, 끌면 이동. */
class BubbleService : Service() {
    companion object {
        @Volatile var running = false
        private const val CHANNEL = "bubble"
    }

    private var wm: WindowManager? = null
    private var bubble: TextView? = null
    private val handler = Handler(Looper.getMainLooper())

    /** 6시간마다 새 버전 확인 (켠 직후에도 한 번) */
    private val updateTick = object : Runnable {
        override fun run() {
            Thread { Updater.run(applicationContext) }.start()
            handler.postDelayed(this, 6L * 3600 * 1000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Store.init(this)
        wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startAsForeground()
        if (Settings.canDrawOverlays(this)) {
            addBubble()
            running = true
            handler.removeCallbacks(updateTick)
            handler.postDelayed(updateTick, 3000)   // 켜자마자 새 버전 확인
        } else {
            stopSelf()
        }
        return START_STICKY
    }

    private fun startAsForeground() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "번역 버튼", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE
        )
        val n = Notification.Builder(this, CHANNEL)
            .setContentTitle("바로통")
            .setContentText("초록 버튼이 켜져 있어요 (누르면 설정 열기)")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(1, n)
        }
    }

    private fun addBubble() {
        if (bubble != null) return
        val size = dp(54)
        val b = TextView(this)
        b.text = "번"
        b.textSize = 20f
        b.setTextColor(Colors.WHITE)
        b.gravity = Gravity.CENTER
        b.setTypeface(b.typeface, android.graphics.Typeface.BOLD)
        val bg = android.graphics.drawable.GradientDrawable()
        bg.shape = android.graphics.drawable.GradientDrawable.OVAL
        bg.setColor(Colors.GREEN)
        bg.setStroke(dp(3), Colors.WHITE)
        b.background = bg

        val lp = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        val dm = resources.displayMetrics
        lp.x = dm.widthPixels - size - dp(6)
        lp.y = (dm.heightPixels * 0.42f).toInt()

        val slop = ViewConfiguration.get(this).scaledTouchSlop
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var moved = false
        var longFired = false
        val longPress = Runnable {
            longFired = true
            open(SheetActivity.MODE_REPLY)
        }
        b.setOnTouchListener { _: View, e: MotionEvent ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX
                    downY = e.rawY
                    startX = lp.x
                    startY = lp.y
                    moved = false
                    longFired = false
                    handler.postDelayed(longPress, 550)
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!moved && (Math.abs(dx) > slop || Math.abs(dy) > slop)) {
                        moved = true
                        handler.removeCallbacks(longPress)
                    }
                    if (moved) {
                        lp.x = startX + dx.toInt()
                        lp.y = startY + dy.toInt()
                        wm?.updateViewLayout(b, lp)
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    handler.removeCallbacks(longPress)
                    if (!moved && !longFired) open(SheetActivity.MODE_TRANSLATE)
                    true
                }
                MotionEvent.ACTION_CANCEL -> {
                    handler.removeCallbacks(longPress)
                    true
                }
                else -> false
            }
        }
        wm?.addView(b, lp)
        bubble = b
    }

    private fun open(mode: String) {
        val i = Intent(this, SheetActivity::class.java)
        i.putExtra(SheetActivity.EXTRA_MODE, mode)
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(i)
    }

    override fun onDestroy() {
        handler.removeCallbacks(updateTick)
        running = false
        bubble?.let { try { wm?.removeView(it) } catch (e: Exception) { } }
        bubble = null
        super.onDestroy()
    }
}
