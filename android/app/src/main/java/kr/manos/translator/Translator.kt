package kr.manos.translator

import org.json.JSONArray
import org.json.JSONObject

data class Incoming(val korean: String, val nuance: String)
data class Option(val label: String, val chinese: String, val back: String)
data class Replies(val options: List<Option>, val note: String)

/** 번역·속뜻·답장 후보. 한 번 번역한 글은 저장소에서 바로 꺼내 씀 (AI 사용 안 함). */
object Translator {
    const val FAST = "claude-haiku-5-5"
    const val MAIN = "claude-sonnet-5-5"

    private fun body(
        model: String, userContent: String, schema: JSONObject, thinking: JSONObject?, maxTokens: Int
    ): JSONObject {
        val system = JSONArray().put(
            JSONObject().put("type", "text").put("text", Prompts.SYSTEM)
                .put("cache_control", JSONObject().put("type", "ephemeral"))
        )
        val b = JSONObject()
            .put("model", model)
            .put("max_tokens", maxTokens)
            .put("system", system)
            .put("messages", JSONArray().put(JSONObject().put("role", "user").put("content", userContent)))
            .put(
                "output_config", JSONObject().put("effort", "low")
                    .put("format", JSONObject().put("type", "json_schema").put("schema", schema))
            )
        if (thinking != null) b.put("thinking", thinking)
        return b
    }

    /** 기본 AI 로 보낼 때: 생각 단계 없이 바로 답하게 하고, 안전 분류기가 거절하면 서버가 대신 처리. */
    private fun mainBody(userContent: String, schema: JSONObject, maxTokens: Int): JSONObject =
        body(MAIN, userContent, schema, JSONObject().put("type", "between_tools"), maxTokens)
            .put("fallbacks", "default")

    private fun parse(resp: JSONObject): JSONObject {
        val stop = resp.optString("stop_reason")
        if (stop == "refusal") throw Api.ApiError(0, "이 메시지는 AI가 처리를 거절했어요.")
        if (stop == "max_tokens") throw Api.ApiError(0, "글이 너무 길어요. 나눠서 복사해 주세요.")
        val blocks = resp.optJSONArray("content") ?: throw Api.ApiError(0, "번역 결과를 읽지 못했어요.")
        for (i in 0 until blocks.length()) {
            val blk = blocks.getJSONObject(i)
            if (blk.optString("type") == "text") {
                try {
                    return JSONObject(blk.getString("text"))
                } catch (e: Exception) {
                    throw Api.ApiError(0, "번역 결과를 읽지 못했어요. 다시 눌러 주세요.")
                }
            }
        }
        throw Api.ApiError(0, "번역 결과가 비어 있어요.")
    }

    private fun context(): String =
        if (Store.lastZh.isBlank()) "(이전 대화 없음)" else "[업체] ${Store.lastZh}  (번역: ${Store.lastKo})"

    /** 업체 글 → 한국어. intent=true 면 속뜻 풀이까지. 반환: (결과, 저장소에서 꺼냈는지) */
    fun incoming(text: String, intent: Boolean): Pair<Incoming, Boolean> {
        val saved = Store.recall(if (intent) "intent" else "in", text)
        if (saved != null) return Pair(Incoming(saved.optString("korean"), saved.optString("nuance")), true)
        val task = if (intent) {
            "작업: intent. 대표가 이 메시지의 속뜻을 자세히 알고 싶어 한다. 번역과 속뜻 풀이를 해.\n<message>\n$text\n</message>"
        } else {
            "작업: incoming. 아래 업체 메시지를 한국어로 옮겨. (번역만)\n<message>\n$text\n</message>"
        }
        val content = "거래처: (알 수 없음)\n\n최근 대화:\n${context()}\n\n$task"
        val schema = if (intent) Prompts.INTENT_SCHEMA else Prompts.INCOMING_SCHEMA
        val key = Store.apiKey

        var result: JSONObject? = null
        if (Store.fastIncoming && !intent) {
            try {
                // 받은 글 번역만 빠른 AI 로 (안 되면 아래에서 기본 AI 로 다시)
                result = parse(Api.call(key, body(FAST, content, schema, JSONObject().put("type", "disabled"), 2000), false))
            } catch (e: Api.ApiError) {
                if (e.code == 401 || e.code == -1 || e.code == -2) throw e   // 키·인터넷 문제는 기본 AI 로 해도 같음
            }
        }
        if (result == null) result = parse(Api.call(key, mainBody(content, schema, 2000), true))
        val r: JSONObject = result ?: throw Api.ApiError(0, "번역 결과가 비어 있어요.")
        val inc = Incoming(r.optString("korean"), r.optString("nuance"))
        if (inc.korean.isNotBlank()) {
            Store.remember(
                if (intent) "intent" else "in", text,
                JSONObject().put("korean", inc.korean).put("nuance", inc.nuance)
            )
        }
        return Pair(inc, false)
    }

    /** 대표의 한국어 → 중국어 후보 3개. 반환: (결과, 저장소에서 꺼냈는지) */
    fun replies(korean: String, fresh: Boolean): Pair<Replies, Boolean> {
        if (!fresh) {
            val saved = Store.recall("out", korean)
            if (saved != null) return Pair(fromJson(saved), true)
        }
        val content = "거래처: (알 수 없음)\n\n최근 대화:\n${context()}\n\n" +
            "작업: outgoing. 말투: 정중하고 예의 바른 비즈니스 말투.\n" +
            "아래 대표의 한국어를 업체에 보낼 중국어로 옮겨.\n<message>\n$korean\n</message>"
        val r = parse(Api.call(Store.apiKey, mainBody(content, Prompts.OUTGOING_SCHEMA, 4000), true))
        val rep = fromJson(r)
        if (rep.options.isNotEmpty()) Store.remember("out", korean, r)
        return Pair(rep, false)
    }

    private fun fromJson(r: JSONObject): Replies {
        val arr = r.optJSONArray("options") ?: JSONArray()
        val list = ArrayList<Option>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            if (o.optString("chinese").isNotBlank()) {
                list.add(Option(o.optString("label"), o.optString("chinese"), o.optString("back_translation")))
            }
        }
        return Replies(list, r.optString("note"))
    }
}
