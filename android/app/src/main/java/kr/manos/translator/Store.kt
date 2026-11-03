package kr.manos.translator

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONObject
import java.io.File

/** 이 휴대폰 안에만 저장되는 설정과 번역 저장소. */
object Store {
    private lateinit var prefs: SharedPreferences
    private lateinit var memFile: File
    private var mem: JSONObject? = null
    private const val MAX_ENTRIES = 3000

    /** 방금 번역한 업체 글(원문, 번역). 답장 후보를 만들 때 맥락으로 쓰이고, 앱을 끄면 사라져요. */
    @Volatile var lastZh: String = ""
    @Volatile var lastKo: String = ""

    fun init(ctx: Context) {
        if (this::prefs.isInitialized) return
        val app = ctx.applicationContext
        prefs = app.getSharedPreferences("manos", Context.MODE_PRIVATE)
        memFile = File(app.filesDir, "memory.json")
    }

    var apiKey: String
        get() = prefs.getString("api_key", "") ?: ""
        set(v) { prefs.edit().putString("api_key", v.trim()).apply() }

    var fastIncoming: Boolean
        get() = prefs.getBoolean("fast_incoming", true)
        set(v) { prefs.edit().putBoolean("fast_incoming", v).apply() }

    /** 문장부호·띄어쓰기 차이는 같은 글로 봄. */
    fun key(text: String): String =
        text.replace(Regex("""[\s，。、,.!！?？~～…:：;；"'“”‘’()（）\[\]【】]+"""), "").lowercase()

    @Synchronized
    private fun memory(): JSONObject {
        mem?.let { return it }
        val m = try {
            if (memFile.exists()) JSONObject(memFile.readText(Charsets.UTF_8)) else JSONObject()
        } catch (e: Exception) {
            JSONObject()
        }
        mem = m
        return m
    }

    @Synchronized
    fun recall(kind: String, text: String): JSONObject? = memory().optJSONObject(kind + "|" + key(text))

    @Synchronized
    fun remember(kind: String, text: String, value: JSONObject) {
        val m = memory()
        val k = kind + "|" + key(text)
        m.remove(k)
        m.put(k, value)
        while (m.length() > MAX_ENTRIES) {
            val first = m.keys().next()
            m.remove(first)
        }
        try {
            memFile.writeText(m.toString(), Charsets.UTF_8)
        } catch (e: Exception) {
            // 저장이 안 돼도 번역은 계속됨
        }
    }
}
