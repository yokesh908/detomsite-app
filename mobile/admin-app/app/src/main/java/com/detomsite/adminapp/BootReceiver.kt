package com.detomsite.adminapp

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            val p = context.getSharedPreferences("admin", Context.MODE_PRIVATE)
            if (p.getBoolean("notif_enabled", false) && p.getString("token", null) != null) {
                AdminNotificationService.start(context)
            }
        }
    }
}