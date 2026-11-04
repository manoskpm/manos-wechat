package kr.manos.translator

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** 위챗·1688 화면 위로 올라오는 시트: 번역 시트, 답장 시트. */
class SheetActivity : Activity() {
    companion object {
        const val EXTRA_MODE = "mode"
        const val MODE_TRANSLATE = "translate"
        const val MODE_REPLY = "reply"
    }

    private lateinit var content: LinearLayout
    private var mode = MODE_TRANSLATE
    private var loaded = false
    private var original = ""
    private var token = 0   // 늦게 도착한 옛 결과를 버리기 위한 번호

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Store.init(this)
        window.setBackgroundDrawable(ColorDrawable(0x66000000))
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        mode = intent.getStringExtra(EXTRA_MODE) ?: MODE_TRANSLATE

        val root = FrameLayout(this)
        root.setOnClickListener { finish() }
        val card = ScrollView(this)
        card.isClickable = true
        card.background = roundTop(Colors.WHITE, dp(20).toFloat())
        content = LinearLayout(this)
        content.orientation = LinearLayout.VERTICAL
        content.setPadding(dp(16), dp(14), dp(16), dp(18))
        card.addView(content, FrameLayout.LayoutParams(MATCH, WRAP))
        root.addView(card, FrameLayout.LayoutParams(MATCH, WRAP, Gravity.BOTTOM))
        setContentView(root)

        if (mode == MODE_REPLY) showReplyInput() else showMessage("복사한 글을 읽는 중…")
    }

    private fun roundTop(color: Int, r: Float) = roundBg(color, r).also {
        it.cornerRadii = floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
    }

    // 복사한 글은 이 시트가 화면 앞에 나와서 포커스를 받은 뒤에야 읽을 수 있음 (안드로이드 보안 규칙)
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && mode == MODE_TRANSLATE && !loaded) {
            loaded = true
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val text = cm.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(this)?.toString()?.trim() ?: ""
            if (text.isEmpty()) {
                showMessage("복사한 글이 없어요.\n위챗에서 글을 길게 눌러 [복사]한 뒤, 초록 버튼을 다시 눌러 주세요.")
            } else {
                original = text
                translate(false)
            }
        }
    }

    private fun header(title: String) {
        content.removeAllViews()
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        val t = label(title, 12f, Colors.SUB)
        row.addView(t, LinearLayout.LayoutParams(0, WRAP, 1f))
        val x = label("✕", 16f, Colors.SUB)
        x.setPadding(dp(12), 0, 0, 0)
        x.setOnClickListener { finish() }
        row.addView(x, LinearLayout.LayoutParams(WRAP, WRAP))
        content.addView(row, lp(MATCH, WRAP))
    }

    private fun showMessage(msg: String) {
        header("🈯 바로통")
        content.addView(label(msg, 16f, Colors.TEXT), lp(MATCH, WRAP, 12, this))
    }

    // ---------- 번역 시트 ----------
    private fun translate(intent: Boolean) {
        val my = ++token
        showMessage("번역 중…")
        Thread {
            try {
                val (inc, cached) = Translator.incoming(original, intent)
                runOnUiThread { if (my == token) showTranslation(inc, cached, intent) }
            } catch (e: Api.ApiError) {
                runOnUiThread { if (my == token) showError(e.message ?: "번역에 실패했어요.") { translate(intent) } }
            } catch (e: Exception) {
                runOnUiThread { if (my == token) showError("번역에 실패했어요. 잠시 후 다시 눌러 주세요.") { translate(intent) } }
            }
        }.start()
    }

    private fun showTranslation(inc: Incoming, cached: Boolean, intent: Boolean) {
        Store.lastZh = original
        Store.lastKo = inc.korean
        header("🈯 바로통")
        val src = label(original, 13f, Colors.SUB)
        src.maxLines = 4
        content.addView(src, lp(MATCH, WRAP, 10, this))
        val ko = label(inc.korean, 20f, Colors.TEXT)
        ko.setTextIsSelectable(true)
        content.addView(ko, lp(MATCH, WRAP, 6, this))

        val nums = Numbers.extract(original)
        if (nums.isNotEmpty()) {
            val scroll = HorizontalScrollView(this)
            scroll.isHorizontalScrollBarEnabled = false
            val row = LinearLayout(this)
            row.orientation = LinearLayout.HORIZONTAL
            for (n in nums) {
                val chip = label(n, 15f, 0xFF8A5A00.toInt(), true)
                chip.setPadding(dp(11), dp(5), dp(11), dp(5))
                chip.background = roundBg(Colors.NOTE_BG, dp(14).toFloat(), dp(1), 0xFFF3D9A8.toInt())
                val p = LinearLayout.LayoutParams(WRAP, WRAP)
                p.rightMargin = dp(6)
                row.addView(chip, p)
            }
            scroll.addView(row)
            content.addView(scroll, lp(MATCH, WRAP, 10, this))
        }
        val tag = if (cached) "✓ 저장소에서 바로 (무료)" else "✓ 번역 완료"
        content.addView(label(if (nums.isNotEmpty()) "$tag · 숫자는 원문 그대로" else tag, 12f, Colors.GREEN), lp(MATCH, WRAP, 6, this))

        if (intent && inc.nuance.isNotBlank()) {
            val box = label("💡 속뜻\n" + inc.nuance, 14f, Colors.NOTE_TEXT)
            box.setPadding(dp(12), dp(9), dp(12), dp(9))
            box.background = roundBg(Colors.NOTE_BG, dp(10).toFloat())
            box.setTextIsSelectable(true)
            content.addView(box, lp(MATCH, WRAP, 10, this))
        }
        val btns = LinearLayout(this)
        btns.orientation = LinearLayout.HORIZONTAL
        if (!intent) {
            val b1 = pill("🔍 속뜻", false) { translate(true) }
            val p1 = LinearLayout.LayoutParams(0, WRAP, 1f)
            p1.rightMargin = dp(8)
            btns.addView(b1, p1)
        }
        btns.addView(pill("✍️ 답장 쓰기", true) { showReplyInput() }, LinearLayout.LayoutParams(0, WRAP, 1f))
        content.addView(btns, lp(MATCH, WRAP, 12, this))
    }

    private fun showError(msg: String, retry: () -> Unit) {
        header("🈯 바로통")
        val m = label(msg, 15f, 0xFFC0392B.toInt())
        content.addView(m, lp(MATCH, WRAP, 12, this))
        content.addView(pill("다시 해 보기", true) { retry() }, lp(MATCH, WRAP, 12, this))
    }

    // ---------- 답장 시트 ----------
    private lateinit var input: EditText

    private fun showReplyInput(prefill: String = "") {
        ++token
        header("✍️ 답장 쓰기")
        if (Store.lastZh.isNotBlank()) {
            val ctx = label("💬 방금 번역한 글이 맥락으로 반영돼요\n" + Store.lastZh.take(60), 12f, 0xFF07A050.toInt())
            ctx.setPadding(dp(10), dp(7), dp(10), dp(7))
            ctx.background = roundBg(Colors.GREEN_BG, dp(10).toFloat())
            content.addView(ctx, lp(MATCH, WRAP, 10, this))
        }
        input = EditText(this)
        input.hint = "한국어로 쓰세요 (예: 단가 확인 부탁드립니다)"
        input.textSize = 17f
        input.minLines = 2
        input.gravity = Gravity.TOP or Gravity.START
        input.setText(prefill)
        input.setPadding(dp(12), dp(10), dp(12), dp(10))
        input.background = roundBg(Colors.GRAY_BG, dp(10).toFloat())
        content.addView(input, lp(MATCH, WRAP, 10, this))
        content.addView(pill("후보 만들기 (3개)", true) { makeReplies(false) }, lp(MATCH, WRAP, 10, this))
        input.requestFocus()
        window.setSoftInputMode(
            WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE or WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        )
    }

    private fun makeReplies(fresh: Boolean) {
        val ko = input.text.toString().trim()
        if (ko.isEmpty()) {
            Toast.makeText(this, "한국어로 먼저 써 주세요", Toast.LENGTH_SHORT).show()
            return
        }
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        imm.hideSoftInputFromWindow(input.windowToken, 0)
        val my = ++token
        showMessage("후보를 만드는 중…")
        Thread {
            try {
                val (rep, cached) = Translator.replies(ko, fresh)
                runOnUiThread { if (my == token) showReplies(ko, rep, cached) }
            } catch (e: Api.ApiError) {
                runOnUiThread { if (my == token) showError(e.message ?: "후보를 만들지 못했어요.") { makeReplies(fresh) } }
            } catch (e: Exception) {
                runOnUiThread { if (my == token) showError("후보를 만들지 못했어요. 잠시 후 다시 눌러 주세요.") { makeReplies(fresh) } }
            }
        }.start()
    }

    private fun showReplies(ko: String, rep: Replies, cached: Boolean) {
        header("✍️ 답장 후보" + if (cached) "  ·  저장소에서 바로 (무료)" else "")
        content.addView(label(ko, 14f, Colors.SUB), lp(MATCH, WRAP, 8, this))
        val cards = ArrayList<LinearLayout>()
        val marks = ArrayList<TextView>()
        rep.options.forEachIndexed { i, o ->
            val card = LinearLayout(this)
            card.orientation = LinearLayout.VERTICAL
            card.setPadding(dp(12), dp(10), dp(12), dp(10))
            val top = LinearLayout(this)
            top.orientation = LinearLayout.HORIZONTAL
            val chip = label(o.label.ifBlank { "후보 ${i + 1}" }, 12f, Colors.TEXT)
            top.addView(chip, LinearLayout.LayoutParams(0, WRAP, 1f))
            val mark = label("", 12f, Colors.GREEN)
            top.addView(mark, LinearLayout.LayoutParams(WRAP, WRAP))
            card.addView(top, lp(MATCH, WRAP))
            card.addView(label(o.chinese, 20f, Colors.TEXT), lp(MATCH, WRAP, 6, this))
            if (o.back.isNotBlank()) card.addView(label("↩ " + o.back, 12f, Colors.SUB), lp(MATCH, WRAP, 3, this))
            cards.add(card)
            marks.add(mark)
            val pick = {
                copy(o.chinese)
                cards.forEachIndexed { j, c ->
                    val on = j == i
                    c.background = roundBg(if (on) Colors.GREEN_BG else Colors.WHITE, dp(12).toFloat(),
                        if (on) dp(2) else dp(1), if (on) Colors.GREEN else Colors.LINE)
                    marks[j].text = if (on) "✓ 복사됨 · 위챗 입력창에 붙여넣기" else ""
                }
            }
            card.setOnClickListener { pick() }
            content.addView(card, lp(MATCH, WRAP, 8, this))
        }
        if (rep.options.isNotEmpty()) {
            cards[0].performClick()   // 추천 문장은 바로 복사해 둠
        } else {
            content.addView(label("후보가 비어 있어요. 다시 만들어 주세요.", 15f, Colors.NOTE_TEXT), lp(MATCH, WRAP, 10, this))
        }
        if (rep.note.isNotBlank()) {
            val note = label("※ " + rep.note, 14f, Colors.NOTE_TEXT)
            note.setPadding(dp(12), dp(9), dp(12), dp(9))
            note.background = roundBg(Colors.NOTE_BG, dp(10).toFloat())
            note.setTextIsSelectable(true)
            content.addView(note, lp(MATCH, WRAP, 10, this))
        }
        val btns = LinearLayout(this)
        btns.orientation = LinearLayout.HORIZONTAL
        val b1 = pill("다시 만들기", false) { makeReplies(true) }
        val p1 = LinearLayout.LayoutParams(0, WRAP, 1f)
        p1.rightMargin = dp(8)
        btns.addView(b1, p1)
        btns.addView(pill("고쳐 쓰기", false) { showReplyInput(ko) }, LinearLayout.LayoutParams(0, WRAP, 1f))
        content.addView(btns, lp(MATCH, WRAP, 12, this))
    }

    private fun copy(text: String) {
        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newPlainText("답장", text))
    }
}
