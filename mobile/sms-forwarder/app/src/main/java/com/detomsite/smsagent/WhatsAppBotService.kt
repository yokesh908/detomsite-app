package com.detomsite.smsagent

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Detomsite WhatsApp bot (phone-side).
 *
 * Guarantee: a WhatsApp message reaches the shopkeeper with **no tap from the
 * human** — the moment the backend says an order is ready to deliver (COD placed
 * or UPI payment verified), this foreground service:
 *
 *   1. Polls ``GET /api/v1/local/whatsapp/pending`` (holding the same agent
 *      key as the SMS forwarding).
 *   2. Opens WhatsApp with the order message pre-filled for the shop's number.
 *   3. [WhatsAppAccessibilityService] verifies the pre-filled text is on screen
 *      and taps Send; this service then confirms delivery via
 *      ``POST /whatsapp/{id}/mark-sent`` so the admin centre reflects it.
 *
 * Messages still labelled "awaiting payment" are skipped by the backend
 * intentionally — the bot waits for the verified "paid ✓" version.
 */
class WhatsAppBotService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var poller: Job? = null

    /** id → when we last launched WhatsApp, so a stuck send retries. */
    private val inFlight = HashMap<String, Long>()

    /** ids already auto-sent on this device — never opened for a second time
     * even if the mark-sent confirmation POST failed (a duplicate WhatsApp to
     * the shop is worse than a Pending row the admin can clear). */
    private val delivered = HashSet<String>()

    /** Last time a guidance notification was shown (throttled to 5 min). */
    private var lastGuidanceAt = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (instance == null) instance = this
        startForegroundCompat()
        if (poller?.isActive != true) {
            poller = scope.launch { pollLoop() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        poller?.cancel()
        if (instance === this) instance = null
        super.onDestroy()
    }

    private fun startForegroundCompat() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "WhatsApp bot", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val n = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("WhatsApp bot is on")
            .setContentText("Orders are auto-sent to shops on WhatsApp")
            .setOngoing(true)
            .build()
        ServiceCompat.startForeground(this, 42, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
    }

    private suspend fun pollLoop() {
        while (scope.isActive) {
            try {
                if (isEnabled()) awaitOutbox()
            } catch (e: Exception) {
                Log.w(TAG, "poll error: ${e.message}")
            }
            delay(20_000L)
        }
    }

    private fun isEnabled(): Boolean {
        val p = getSharedPreferences("agent", Context.MODE_PRIVATE)
        return p.getBoolean("wa_bot_enabled", false) &&
                p.getString("agent_key", null) != null
    }

    private fun baseUrl(): String {
        val p = getSharedPreferences("agent", Context.MODE_PRIVATE)
        return (p.getString("base_url", "").orEmpty()
            .substringBefore("/api/v1").trimEnd('/'))
    }

    private suspend fun awaitOutbox() {
        val root = baseUrl()
        val key = getSharedPreferences("agent", Context.MODE_PRIVATE)
            .getString("agent_key", "").orEmpty()
        if (root.isEmpty() || key.isEmpty()) return
        if (!whatsAppInstalled()) {
            notifyGuidance("WhatsApp is not installed — install it to auto-send.")
            return
        }

        val pending = fetchPending(root, key) ?: return
        // ONE message per poll cycle. The outbox is a single slot shared with
        // the accessibility service — firing several WhatsApp intents back to
        // back overwrote it, so only the LAST shop's message ever reached the
        // screen (multi-shop orders then retried the same last-shop message on
        // every later cycle). Sending one, waiting for Send, then polling again
        // delivers every shop its own message.
        val item = (0 until pending.length())
            .map { pending.getJSONObject(it) }
            .firstOrNull { entry ->
                val id = entry.optString("id")
                id.isNotBlank() && id !in delivered && !isRecentlyLaunched(id) &&
                    normalizePhone(entry.optString("phone")).isNotEmpty()
            } ?: return
        val id = item.optString("id")
        val now = System.currentTimeMillis()
        if (!canStartFromBackground()) {
            notifyGuidance("Allow “Display over other apps” so the bot can auto-open WhatsApp.")
            return
        }
        if (inFlight[id] == null) notifySending(item.optString("sub_order_id"), item.optString("phone"))
        inFlight[id] = now
        openWhatsApp(id, item.optString("phone"), item.optString("message"))
    }

    /** Launched within the retry window and still waiting for accessibility? */
    private fun isRecentlyLaunched(id: String): Boolean {
        val launched = inFlight[id] ?: return false
        return System.currentTimeMillis() - launched < 3 * 60_000L
    }

    private suspend fun fetchPending(root: String, key: String): JSONArray? = withContext(Dispatchers.IO) {
        try {
            val req = Request.Builder()
                .url("$root/api/v1/local/whatsapp/pending")
                .header("X-Agent-Key", key)
                .build()
            val client = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .build()
            client.newCall(req).execute().use { resp ->
                if (resp.code !in 200..299) {
                    Log.w(TAG, "pending → ${resp.code}")
                    return@withContext null
                }
                JSONArray(resp.body?.string().orEmpty())
            }
        } catch (e: Exception) {
            Log.w(TAG, "fetchPending failed: ${e.message}")
            null
        }
    }

    private fun normalizePhone(phone: String): String {
        var digits = phone.filter { it.isDigit() }
        // Strip a domestic trunk prefix ("09876543210" → "9876543210") and an
        // explicit country code ("919876543210") down to the 10-digit mobile
        // before wa.me addressing; otherwise a 12-digit string that is NOT a
        // valid Indian mobile would be sent as-is and open the wrong chat.
        if (digits.length == 11 && digits.startsWith("0")) digits = digits.substring(1)
        return when {
            digits.isEmpty() -> ""
            digits.length == 10 -> "91$digits"
            digits.length == 12 && digits.startsWith("91") -> digits
            else -> ""
        }
    }

    private fun openWhatsApp(id: String, phone: String, message: String) {
        val digits = normalizePhone(phone)
        if (digits.isEmpty()) {
            // Poison entry (no usable shop number): record the attempt so this
            // poll cycle skips it instead of wedging the whole outbox behind it.
            inFlight[id] = System.currentTimeMillis()
            return
        }
        val text = message.let {
            Uri.encode(it)
        }
        val waUri = Uri.parse("https://wa.me/$digits?text=$text")
        AutoSendState.begin(id, digits, message)
        try {
            val intent = Intent(Intent.ACTION_VIEW, waUri)
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            val pkg = if (packageManager.hasApplication("com.whatsapp")) "com.whatsapp" else "com.whatsapp.w4b"
            intent.setPackage(pkg)
            startActivity(intent)
        } catch (e: Exception) {
            Log.w(TAG, "openWhatsApp failed: ${e.message}")
            inFlight.remove(id)
            AutoSendState.clear()
        }
    }

    /** Confirmed by the accessibility service: Send was tapped. */
    fun confirmSent(id: String) {
        notificationManager().cancel(SENDING)
        delivered.add(id)
        scope.launch {
            markSent(id)
            inFlight.remove(id)
            if (AutoSendState.id == id) AutoSendState.clear()
        }
    }

    private suspend fun markSent(id: String) {
        val root = baseUrl()
        val key = getSharedPreferences("agent", Context.MODE_PRIVATE)
            .getString("agent_key", "").orEmpty()
        if (root.isEmpty() || key.isEmpty()) return
        try {
            val req = Request.Builder()
                .url("$root/api/v1/local/whatsapp/${Uri.encode(id)}/mark-sent")
                .post("{}".toRequestBody(JSON_MEDIA))
                .header("Content-Type", "application/json")
                .header("X-Agent-Key", key)
                .build()
            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .build()
                .newCall(req).execute().use { resp ->
                    Log.i(TAG, "mark-sent → ${resp.code}")
                }
        } catch (e: Exception) {
            Log.w(TAG, "markSent failed: ${e.message}")
        }
    }

    private fun whatsAppInstalled(): Boolean =
        try {
            packageManager.getApplicationInfo("com.whatsapp", 0)
            true
        } catch (e: PackageManager.NameNotFoundException) {
            false
        }

    private fun canStartFromBackground(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(this)

    private fun notificationManager(): NotificationManager =
        getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    private fun notifyGuidance(text: String) {
        val now = System.currentTimeMillis()
        if (now - lastGuidanceAt < 5 * 60_000L) return
        lastGuidanceAt = now
        notify(GUIDANCE, text, false)
    }

    private fun notifySending(orderId: String, phone: String) {
        notify(SENDING, "Sending WhatsApp to +${normalizePhone(phone)} (order $orderId)…", true)
    }

    private fun notify(code: Int, text: String, ongoing: Boolean) {
        try {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, "WhatsApp bot", NotificationManager.IMPORTANCE_LOW)
                )
            }
            val n = NotificationCompat.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentTitle("WhatsApp bot")
                .setContentText(text)
                .setAutoCancel(!ongoing)
                .build()
            nm.notify(code, n)
        } catch (e: Exception) {
            Log.d(TAG, "notify skipped: ${e.message}")
        }
    }

    companion object {
        private const val TAG = "DetomsiteWABot"
        private const val CHANNEL = "detomsite_wa_bot"
        private const val SENDING = 70
        private const val GUIDANCE = 71

        @Volatile var instance: WhatsAppBotService? = null

        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        fun start(context: Context) {
            context.startForegroundService(Intent(context, WhatsAppBotService::class.java))
        }
    }
}

private fun android.content.pm.PackageManager.hasApplication(pkg: String): Boolean =
    try {
        getApplicationInfo(pkg, 0)
        true
    } catch (e: android.content.pm.PackageManager.NameNotFoundException) {
        false
    }