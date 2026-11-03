package kr.manos.translator

import android.content.Context
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

object Colors {
    val GREEN = 0xFF07C160.toInt()
    val GREEN_BG = 0xFFF3FBF6.toInt()
    val TEXT = 0xFF191919.toInt()
    val SUB = 0xFF7A7A7A.toInt()
    val LINE = 0xFFE6E6E6.toInt()
    val GRAY_BG = 0xFFF5F5F5.toInt()
    val NOTE_BG = 0xFFFFF8EC.toInt()
    val NOTE_TEXT = 0xFFB36B00.toInt()
    val WHITE = 0xFFFFFFFF.toInt()
}

fun Context.dp(v: Int): Int = (v * resources.displayMetrics.density + 0.5f).toInt()

fun roundBg(color: Int, radiusPx: Float, strokePx: Int = 0, strokeColor: Int = 0): GradientDrawable {
    val d = GradientDrawable()
    d.setColor(color)
    d.cornerRadius = radiusPx
    if (strokePx > 0) d.setStroke(strokePx, strokeColor)
    return d
}

fun Context.label(text: String, sp: Float, color: Int, bold: Boolean = false): TextView {
    val t = TextView(this)
    t.text = text
    t.textSize = sp
    t.setTextColor(color)
    if (bold) t.setTypeface(t.typeface, Typeface.BOLD)
    return t
}

/** 알약 모양 버튼. primary=true 면 초록색. */
fun Context.pill(text: String, primary: Boolean, onClick: () -> Unit): TextView {
    val t = label(text, 15f, if (primary) Colors.WHITE else 0xFF07A050.toInt(), true)
    t.gravity = Gravity.CENTER
    t.setPadding(dp(10), dp(11), dp(10), dp(11))
    t.background = roundBg(
        if (primary) Colors.GREEN else Colors.GREEN_BG, dp(22).toFloat(),
        if (primary) 0 else dp(1), 0xFFCFE9D9.toInt()
    )
    t.setOnClickListener { onClick() }
    return t
}

fun lp(w: Int, h: Int, top: Int = 0, ctx: Context? = null): LinearLayout.LayoutParams {
    val p = LinearLayout.LayoutParams(w, h)
    if (ctx != null) p.topMargin = ctx.dp(top)
    return p
}

val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
val WRAP = ViewGroup.LayoutParams.WRAP_CONTENT
