package kr.manos.translator

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Claude API 호출. 오류는 대표님이 읽을 수 있는 한국어 메시지로 바꿔 줌. */
object Api {
    class ApiError(val code: Int, message: String) : Exception(message)

    private const val ENDPOINT = "https://api.anthropic.com/v1/messages"

    fun call(apiKey: String, body: JSONObject, beta: Boolean): JSONObject {
        if (apiKey.isBlank()) throw ApiError(-2, "API 키가 없어요. 발주 번역기 앱을 열어서 API 키를 넣어 주세요.")
        val conn = URL(if (beta) "$ENDPOINT?beta=true" else ENDPOINT).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 15000
            conn.readTimeout = 60000
            conn.doOutput = true
            conn.setRequestProperty("content-type", "application/json")
            conn.setRequestProperty("x-api-key", apiKey)
            conn.setRequestProperty("anthropic-version", "2023-06-01")
            if (beta) conn.setRequestProperty("anthropic-beta", "server-side-fallback-2026-07-01")
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code !in 200..299) throw ApiError(code, friendly(code, text))
            return JSONObject(text)
        } catch (e: ApiError) {
            throw e
        } catch (e: IOException) {
            throw ApiError(-1, "인터넷 연결을 확인해 주세요.")
        } finally {
            conn.disconnect()
        }
    }

    private fun friendly(code: Int, text: String): String {
        val detail = try {
            JSONObject(text).optJSONObject("error")?.optString("message") ?: ""
        } catch (e: Exception) {
            ""
        }
        return when (code) {
            401 -> "API 키가 올바르지 않아요. 발주 번역기 앱에서 키를 다시 넣어 주세요."
            403 -> "API 사용 권한이 없어요. 결제 정보나 사용 한도를 확인해 주세요."
            429 -> "요청이 너무 많아요. 잠시 후 다시 눌러 주세요."
            else -> "요청 오류($code) " + detail.take(160)
        }
    }
}
