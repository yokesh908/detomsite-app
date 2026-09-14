package com.detomsite.smsagent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Restart the WhatsApp bot after a reboot, if the user enabled it.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = context.getSharedPreferences("agent", Context.MODE_PRIVATE)
        val url = prefs.getString("base_url", "").orEmpty()
        val key = prefs.getString("agent_key", "").orEmpty()
        if (prefs.getBoolean("wa_bot_enabled", false) && url.isNotEmpty() && key.isNotEmpty()) {
            WhatsAppBotService.start(context)
        }
    }
}