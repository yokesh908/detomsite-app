package com.detomsite.smsagent

/**
 * One-slot outbox shared between [WhatsAppBotService] (fetches the pending
 * message and opens WhatsApp) and [WhatsAppAccessibilityService] (verifies the
 * pre-filled text is on screen and taps Send). The slot is cleared the moment
 * Send is tapped so a single message is never double-sent.
 */
object AutoSendState {
    @Volatile var id: String? = null
    @Volatile var message: String? = null
    @Volatile var phone: String? = null

    /** Short token that must appear in WhatsApp's text box for a tap to happen. */
    @Volatile var verifyToken: String? = null

    @Volatile var launchedAt: Long = 0L

    fun begin(id: String, phone: String, message: String) {
        this.id = id
        this.phone = phone
        this.message = message
        // WhatsApp's pre-filled compose box echoes the message; we only trust a
        // tap when it visibly contains our own order text. A bare number would
        // appear in ANY chat, so use the unique "DETOMSITE order #<n>" string.
        this.verifyToken = extractToken(message)
        this.launchedAt = System.currentTimeMillis()
    }

    fun clear() {
        id = null
        message = null
        phone = null
        verifyToken = null
        launchedAt = 0L
    }

    private fun extractToken(message: String): String {
        // Multi-shop (combo) orders share ONE order token across every shop's
        // sub-order — "DETOMSITE order #18" alone could match the WRONG shop's
        // message and tap Send in the wrong chat. Every message now carries a
        // unique "Ref: <sub-order id>" line; prefer it and only fall back to
        // the legacy token for old queued messages.
        val ref = Regex("Ref:\\s*([A-Za-z0-9_-]+)").find(message)
        if (ref != null) return "Ref: ${ref.groupValues[1]}"
        val order = Regex("DETOMSITE order #([0-9]+)").find(message)
        if (order != null) return "DETOMSITE order #${order.groupValues[1]}"
        return "DETOMSITE"
    }
}