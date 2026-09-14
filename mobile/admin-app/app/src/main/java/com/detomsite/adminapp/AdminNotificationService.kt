package com.detomsite.adminapp

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray

/**
 * Foreground poller for the admin. Every ~25s it asks the server for the
 * newest orders and raises a system notification for any order it has not
 * seen yet — so the admin is pinged the moment a new order is placed, even
 * with the app closed. First poll only records the baseline (no spam).
 */
class AdminNotificationService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var poller: Job? = null
    private val client = OkHttpClient.Builder().connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS).readTimeout(10, java.util.concurrent.TimeUnit.SECONDS).build()

    companion object {
        const val CHANNEL_ORDERS = "admin_orders"
        const val CHANNEL_RUNNING = "admin_running"

        fun start(context: Context) {
            val i = Intent(context, AdminNotificationService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(i) else context.startService(i)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, AdminNotificationService::class.java))
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL_RUNNING, "Order monitor", NotificationManager.IMPORTANCE_LOW))
            val orders = NotificationChannel(CHANNEL_ORDERS, "New orders", NotificationManager.IMPORTANCE_HIGH)
            orders.enableVibration(true)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) orders.setSound(android.provider.Settings.System.DEFAULT_NOTIFICATION_URI, null)
            nm.createNotificationChannel(orders)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat()
        if (poller?.isActive != true) poller = scope.launch { pollLoop() }
        return START_STICKY
    }

    override fun onDestroy() {
        poller?.cancel()
        super.onDestroy()
    }

    private fun startForegroundCompat() {
        val n = NotificationCompat.Builder(this, CHANNEL_RUNNING)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("DETOMSITE Admin is on")
            .setContentText("You'll be notified the moment an order is placed")
            .setOngoing(true)
            .build()
        ServiceCompat.startForeground(this, 42, n, if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
    }

    private suspend fun pollLoop() {
        while (scope.isActive) {
            try {
                if (isEnabled()) poll()
            } catch (e: Exception) {
                // transient network blips are fine — retry next loop
            }
            delay(25_000L)
        }
    }

    private fun isEnabled(): Boolean {
        val p = getSharedPreferences("admin", Context.MODE_PRIVATE)
        val token = p.getString("token", null)
        return p.getBoolean("notif_enabled", false) && token != null
    }

    private suspend fun poll() {
        val p = getSharedPreferences("admin", Context.MODE_PRIVATE)
        val base = p.getString("base_url", "").orEmpty()
        val token = p.getString("token", "").orEmpty()
        if (base.isEmpty() || token.isEmpty()) return
        val items: JSONArray?
        try {
            items = withContext(Dispatchers.IO) {
                val req = Request.Builder().url("$base/api/v1/admin/orders").header("Authorization", "Bearer $token").build()
                client.newCall(req).execute().use { resp ->
                    if (resp.code == 401) { p.edit().putBoolean("notif_enabled", false).apply(); return@use null }
                    if (resp.code !in 200..299) return@use null
                    JSONArray(resp.body?.string().orEmpty())
                }
            }
        } catch (e: Exception) {
            return
        }
        if (items == null || items.length() == 0) return

        val firstId = items.getJSONObject(0).optString("id")
        val prevTop = p.getString("last_top_id", null)
        if (prevTop == null) {
            // First run — just baseline so we don't spam past orders.
            p.edit().putString("last_top_id", firstId).apply()
            return
        }
        val fresh = mutableListOf<org.json.JSONObject>()
        for (i in 0 until items.length()) {
            val o = items.getJSONObject(i)
            if (o.optString("id") == prevTop) break
            fresh.add(o)
            if (fresh.size >= 5) break
        }
        if (fresh.isNotEmpty() && firstId != prevTop) {
            p.edit().putString("last_top_id", firstId).apply()
            fresh.forEach { notifyOrder(it) }
        }
    }

    private fun notifyOrder(o: org.json.JSONObject) {
        val token = o.opt("token")
        val total = o.optInt("total", 0)
        val shop = o.optString("shop_name")
        val student = o.optString("student_name")
        val content = "₹$total · ${shop.ifBlank { "Shop" }} · ${student.ifBlank { "Student" }}"

        val pi = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val n = NotificationCompat.Builder(this, CHANNEL_ORDERS)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("New order #$token")
            .setContentText(content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .build()
        try {
            NotificationManagerCompat.from(this).notify(o.optString("id").hashCode(), n)
        } catch (e: SecurityException) {
            // notification permission not granted — nothing we can do here
        }
    }
}