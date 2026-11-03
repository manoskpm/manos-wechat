package kr.manos.translator

/** 단가·수량·운송비 같은 숫자를 원문 그대로 뽑아서 따로 보여 주기 위한 부분. */
object Numbers {
    private val re = Regex(
        """([¥￥]\s*\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?\s*(?:元|块钱|块|件|个|箱|套|只|双|公斤|斤|KG|kg|Kg|%|％|天|米|cm|CM|mm|MM))"""
    )

    fun extract(text: String): List<String> =
        re.findAll(text).map { localize(it.value) }.distinct().take(8).toList()

    private fun localize(raw: String): String {
        val t = raw.replace(Regex("""\s+"""), "")
        if (t.startsWith("¥") || t.startsWith("￥")) return t.substring(1) + "위안"
        return t.replace("块钱", "위안").replace("块", "위안").replace("元", "위안")
            .replace("件", "개").replace("个", "개").replace("只", "개")
            .replace("箱", "박스").replace("套", "세트").replace("双", "켤레")
            .replace("公斤", "kg").replace("KG", "kg").replace("Kg", "kg").replace("斤", "근")
            .replace("％", "%").replace("天", "일").replace("米", "m")
    }
}
