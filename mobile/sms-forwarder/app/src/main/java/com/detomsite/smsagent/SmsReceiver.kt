package com.detomsite.smsagent

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Telephony
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Detomsite privacy-first SMS Forwarding Agent.
 *
 * Runs on the shopkeeper's phone. When a bank credit SMS arrives:
 *   1. Extracts the UTR and amount **entirely on-device** (the raw SMS text
 *      never leaves the phone).
 *   2. Sends only `{ phone, utr, amount }` to ``POST /api/v1/local/sms/match``.
 *   3. The backend matches amount + shop → order auto-Confirmed → WhatsApp fired.
 *
 * **Privacy:** The server never sees the bank SMS body — no balances, no
 * account details, no sender ID. Only the transaction proof (UTR + amount)
 * crosses the wire.
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val prefs = context.getSharedPreferences("agent", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("enabled", true)) return
        val baseUrl = prefs.getString("base_url", "").orEmpty().trimEnd('/')
        val agentKey = prefs.getString("agent_key", "").orEmpty()
        if (baseUrl.isEmpty() || agentKey.isEmpty()) return

        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val builder = StringBuilder()
        messages.forEach { msg ->
            val body = msg?.displayMessageBody ?: ""
            if (body.isNotEmpty()) {
                if (builder.isNotEmpty()) builder.append(' ')
                builder.append(body)
            }
        }
        val text = builder.toString().trim()
        if (text.isEmpty()) return
        if (!isBankCreditSms(text)) return

        // ── On-device extraction: UTR + amount stay local, raw text never leaves ──
        val utr = extractUtr(text) ?: return
        val amount = extractAmount(text) ?: return

        Log.i(TAG, "On-device: UTR=$utr amount=$amount — sending proof only")
        CoroutineScope(Dispatchers.IO).launch {
            sendProof(context, baseUrl, agentKey, utr, amount)
        }
    }

    private fun isBankCreditSms(text: String): Boolean {
        val lower = text.lowercase()
        // A debit SMS is never a payment proof — never match against it even if
        // it happens to mention "upi"/"utr"/"ref".
        if (listOf("debited", " debit", "deducted", "paid out").any { lower.contains(it) }) return false
        return listOf("credited", " credit ", "deposited", "received", "rcvd", "cr ")
            .any { lower.contains(it) }
    }

    /** Extract UTR on-device. Never sent: sender, balance, account, raw text. */
    private fun extractUtr(text: String): String? {
        val patterns = listOf(
            Regex("(?i)\\butr\\s*:?\\s*([a-z0-9]{6,30})"),
            Regex("(?i)\\bref\\s*(?:erence|\\.|no|#)?\\s*[:.]?\\s*([a-z0-9]{6,30})"),
            Regex("(?<![a-z0-9])([a-z]{0,4}\\d{10,16})(?![a-z0-9])"),
        )
        for (p in patterns) {
            p.find(text)?.let { return it.groupValues[1].uppercase() }
        }
        return null
    }

    /** Extract the credited amount on-device. */
    private fun extractAmount(text: String): Double? {
        val regex = Regex("(?:Rs\\.?|INR|₹|\\bCr\\.?)\\s*([\\d,]+(?:\\.\\d{1,2})?)", RegexOption.IGNORE_CASE)
        val matches = regex.findAll(text).toList()
        if (matches.isEmpty()) return null

        val lower = text.lowercase()
        val creditCues = listOf(
            "credited", "deposited", "received", "rcvd", "successful", "credit", "trns"
        )

        // Prefer the amount whose surroundings mention a credit cue, so a
        // balance mention ("A/c bal: Rs 5,000") is never chosen over the
        // ₹80 credit. Fall back to the last match.
        var best: MatchResult? = null
        var bestDist = Int.MAX_VALUE
        var sawCue = false
        for (m in matches) {
            // A value directly labelled as the balance (within 12 chars) is
            // never the credit.
            val before = lower.substring(maxOf(0, m.range.first - 12), m.range.first)
            if ("bal" in before) continue
            val start = maxOf(0, m.range.first - 30)
            val end = minOf(text.length, m.range.last + 30)
            val window = lower.substring(start, end)
            val cue = creditCues.firstOrNull { it in window } ?: continue
            val dist = minOf(
                m.range.first - start,
                window.indexOf(cue),
                maxOf(0, end - (start + window.indexOf(cue) + cue.length))
            )
            if (dist < bestDist) {
                bestDist = dist
                best = m
                sawCue = true
            }
        }

        val chosen = if (sawCue) best!! else matches.last()
        return try {
            chosen.groupValues[1].replace(",", "").toDouble()
        } catch (e: Exception) { null }
    }

    /** Send only {phone, utr, amount} — never the raw SMS. */
    private suspend fun sendProof(
        context: Context, baseUrl: String, agentKey: String, utr: String, amount: Double
    ) {
        try {
            // Accept both "https://host" and "https://host/api/v1/local" as the
            // saved base URL — never double-append the path.
            val root = baseUrl
                .substringBefore("/api/v1")
                .trimEnd('/')
            val json = JSONObject()
                .put("phone", configuredPhone(context, context.getSharedPreferences("agent", Context.MODE_PRIVATE)))
                .put("utr", utr)
                .put("amount", amount)
            val body = json.toString().toRequestBody(JSON_MEDIA)
            val request = Request.Builder()
                .url("$root/api/v1/local/sms/match")
                .post(body)
                .header("Content-Type", "application/json")
                .header("X-Agent-Key", agentKey)
                .build()
            val client = OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .build()
            client.newCall(request).execute().use { resp ->
                val code = resp.code
                Log.i(TAG, "sms/match → $code: ${resp.body?.string()?.take(120)}")
                if (code in 200..299) notifySent(context, "UTR $utr ✓")
                else Log.w(TAG, "Match rejected ($code)")
            }
        } catch (e: Exception) {
            Log.e(TAG, "sendProof failed: ${e.message}")
        }
    }

    private fun configuredPhone(context: Context, prefs: android.content.SharedPreferences): String {
        val manual = prefs.getString("phone", "").orEmpty().trim().replace(Regex("\\D"), "")
        val digits = manual.ifEmpty { localNumber(context).replace(Regex("\\D"), "") }
        val bare = if (digits.startsWith("91")) digits.substring(2) else digits
        return "+91" + bare.takeLast(10)
    }

    @SuppressLint("MissingPermission")
    private fun localNumber(context: Context): String {
        return try {
            val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as android.telephony.TelephonyManager
            tm.line1Number ?: ""
        } catch (e: Exception) { "" }
    }

    private fun notifySent(context: Context, preview: String) {
        try {
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, "Agent status", NotificationManager.IMPORTANCE_DEFAULT)
                )
            }
            val n = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentTitle("Payment proof sent ✓")
                .setContentText(preview)
                .setAutoCancel(true)
                .build()
            nm.notify(1, n)
        } catch (e: Exception) { Log.d(TAG, "notify skipped: ${e.message}") }
    }

    companion object {
        private const val TAG = "DetomsiteAgent"
        private const val CHANNEL = "detomsite_agent"
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    }
}