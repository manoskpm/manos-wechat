package kr.manos.translator

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

/** 설정 화면: API 키, 권한, 초록 버튼 켜기/끄기. */
class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var keyState: TextView
    private lateinit var toggle: TextView
    private lateinit var keyInput: EditText
    private lateinit var testResult: TextView
    private lateinit var updateText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Store.init(this)
        val scroll = ScrollView(this)
        val col = LinearLayout(this)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(dp(20), dp(28), dp(20), dp(28))
        scroll.addView(col)
        setContentView(scroll)

        val version = try { packageManager.getPackageInfo(packageName, 0).versionName } catch (e: Exception) { "" }
        col.addView(label("발주 번역기", 26f, Colors.TEXT, true))
        col.addView(label("버전 $version · 위챗·1688 채팅 번역과 답장", 13f, Colors.SUB), lp(MATCH, WRAP, 2, this))
        status = label("", 15f, Colors.TEXT)
        status.setPadding(dp(14), dp(12), dp(14), dp(12))
        status.background = roundBg(Colors.GRAY_BG, dp(12).toFloat())
        col.addView(status, lp(MATCH, WRAP, 16, this))

        col.addView(label("① API 키", 17f, Colors.TEXT, true), lp(MATCH, WRAP, 22, this))
        keyState = label("", 13f, Colors.SUB)
        col.addView(keyState, lp(MATCH, WRAP, 4, this))
        keyInput = EditText(this)
        keyInput.hint = "sk-ant- 로 시작하는 키를 붙여 넣으세요"
        keyInput.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        keyInput.textSize = 14f
        keyInput.setPadding(dp(12), dp(10), dp(12), dp(10))
        keyInput.background = roundBg(Colors.GRAY_BG, dp(10).toFloat())
        col.addView(keyInput, lp(MATCH, WRAP, 8, this))
        col.addView(pill("키 저장", false) { saveKey() }, lp(MATCH, WRAP, 8, this))
        col.addView(pill("연결 확인 (번역 한 번 해 보기)", false) { testKey() }, lp(MATCH, WRAP, 8, this))
        testResult = label("", 14f, Colors.SUB)
        col.addView(testResult, lp(MATCH, WRAP, 6, this))

        col.addView(label("② 다른 앱 위에 표시 허용", 17f, Colors.TEXT, true), lp(MATCH, WRAP, 22, this))
        col.addView(label("초록 버튼이 위챗 위에 떠 있으려면 꼭 필요해요.", 13f, Colors.SUB), lp(MATCH, WRAP, 4, this))
        col.addView(pill("허용하러 가기", false) {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        }, lp(MATCH, WRAP, 8, this))

        col.addView(label("③ 초록 버튼", 17f, Colors.TEXT, true), lp(MATCH, WRAP, 22, this))
        toggle = pill("", true) { toggleBubble() }
        col.addView(toggle, lp(MATCH, WRAP, 8, this))

        col.addView(label("④ 앱 업데이트", 17f, Colors.TEXT, true), lp(MATCH, WRAP, 22, this))
        col.addView(
            label("앱을 켜거나 초록 버튼을 켤 때마다 새 버전을 확인해서 알아서 받고 설치해요. 버튼은 없어요.", 13f, Colors.SUB),
            lp(MATCH, WRAP, 4, this)
        )
        updateText = label("", 14f, Colors.TEXT)
        col.addView(updateText, lp(MATCH, WRAP, 6, this))
        col.addView(pill("설치 허용 (자동 업데이트에 필요)", false) {
            startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
        }, lp(MATCH, WRAP, 8, this))

        val fast = Switch(this)
        fast.text = "빠른 번역 (받은 업체 글을 더 빠른 AI로)"
        fast.textSize = 14f
        fast.isChecked = Store.fastIncoming
        fast.setOnCheckedChangeListener { _, v -> Store.fastIncoming = v }
        col.addView(fast, lp(MATCH, WRAP, 18, this))

        col.addView(label("사용법", 17f, Colors.TEXT, true), lp(MATCH, WRAP, 24, this))
        val help = label(
            "1. 위챗(또는 1688)에서 업체 글을 길게 눌러 [복사]\n" +
                "2. 화면 옆에 떠 있는 초록 [번] 버튼을 한 번 누르면 번역이 올라와요\n" +
                "3. [답장 쓰기]를 누르고 한국어로 쓰면 중국어 후보 3개가 나와요. 추천 문장은 이미 복사돼 있어요\n" +
                "4. 위챗 입력창에 붙여넣고 보내기는 직접 누르세요\n\n" +
                "· [번] 버튼을 길게 누르면 바로 답장 쓰기가 열려요\n" +
                "· [번] 버튼은 손가락으로 끌어서 옮길 수 있어요\n" +
                "· 한 번 번역한 글은 저장소에서 바로 나와요 (AI 사용료 없음)\n" +
                "· API 키는 이 휴대폰 안에만 저장돼요", 14f, Colors.TEXT
        )
        help.setLineSpacing(0f, 1.25f)
        col.addView(help, lp(MATCH, WRAP, 6, this))
    }

    override fun onResume() {
        super.onResume()
        refresh()
        // 앱을 열 때마다 새 버전 확인 → 있으면 바로 받아서 설치 요청
        checkUpdate()
        // 업데이트로 앱이 다시 설치된 뒤 버튼이 꺼져 있으면 다시 켬
        if (Store.bubbleEnabled && !BubbleService.running && Settings.canDrawOverlays(this)) {
            try { startForegroundService(Intent(this, BubbleService::class.java)) } catch (e: Exception) { }
        }
    }

    private fun checkUpdate() {
        updateText.text = "확인 중…"
        Thread {
            Updater.run(applicationContext)
            runOnUiThread { refresh() }
        }.start()
    }

    private fun refresh() {
        val key = Store.apiKey
        keyState.text = if (key.isBlank()) "아직 저장된 키가 없어요" else "저장됨 (끝 4자리 ${key.takeLast(4)})"
        val overlay = Settings.canDrawOverlays(this)
        val on = BubbleService.running
        status.text = "API 키: " + (if (key.isBlank()) "❌ 없음" else "✅ 있음") +
            "\n다른 앱 위에 표시: " + (if (overlay) "✅ 허용됨" else "❌ 허용 필요") +
            "\n초록 버튼: " + (if (on) "✅ 켜져 있음" else "꺼져 있음")
        toggle.text = if (on) "초록 버튼 끄기" else "초록 버튼 켜기"
        val canInstall = packageManager.canRequestPackageInstalls()
        updateText.text = "현재 v" + Updater.currentVersion(this) + " · " +
            (Store.updateState.ifBlank { "아직 확인 전" }) +
            "\n설치 허용: " + (if (canInstall) "✅ 허용됨" else "❌ 필요 (아래 버튼)")
    }

    private fun saveKey() {
        val k = keyInput.text.toString().trim()
        if (k.isEmpty()) {
            Toast.makeText(this, "키를 먼저 붙여 넣어 주세요", Toast.LENGTH_SHORT).show()
            return
        }
        Store.apiKey = k
        keyInput.setText("")
        Toast.makeText(this, "저장했어요", Toast.LENGTH_SHORT).show()
        refresh()
    }

    private fun testKey() {
        testResult.setTextColor(Colors.SUB)
        testResult.text = "확인 중…"
        Thread {
            try {
                val (inc, _) = Translator.incoming("好的，谢谢老板", false)
                runOnUiThread {
                    testResult.setTextColor(Colors.GREEN)
                    testResult.text = "✅ 연결 성공: 好的，谢谢老板 → " + inc.korean
                }
            } catch (e: Api.ApiError) {
                runOnUiThread {
                    testResult.setTextColor(0xFFC0392B.toInt())
                    testResult.text = "❌ " + (e.message ?: "실패")
                }
            } catch (e: Exception) {
                runOnUiThread {
                    testResult.setTextColor(0xFFC0392B.toInt())
                    testResult.text = "❌ 실패: " + e.javaClass.simpleName
                }
            }
        }.start()
    }

    private fun toggleBubble() {
        val i = Intent(this, BubbleService::class.java)
        if (BubbleService.running) {
            stopService(i)
            BubbleService.running = false
            Store.bubbleEnabled = false
        } else {
            if (!Settings.canDrawOverlays(this)) {
                Toast.makeText(this, "먼저 ② 다른 앱 위에 표시를 허용해 주세요", Toast.LENGTH_LONG).show()
                return
            }
            if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
            }
            startForegroundService(i)
            BubbleService.running = true
            Store.bubbleEnabled = true
        }
        window.decorView.postDelayed({ refresh() }, 400)
    }
}
