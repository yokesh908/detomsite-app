package com.detomsite.adminapp

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import com.detomsite.adminapp.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = OkHttpClient.Builder().connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS).readTimeout(20, java.util.concurrent.TimeUnit.SECONDS).build()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val p = getSharedPreferences("admin", Context.MODE_PRIVATE)
        if (p.getString("token", null) == null) {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
            return
        }
        binding.tvGreeting.text = "Signed in as ${p.getString("user_name", "Admin")}"
        binding.tvStats.text = "Loading…"

        binding.swNotif.isChecked = p.getBoolean("notif_enabled", false)
        binding.btnGrantNotif.visibility = if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) android.view.View.GONE else android.view.View.VISIBLE

        binding.swNotif.setOnCheckedChangeListener { _, checked ->
            p.edit().putBoolean("notif_enabled", checked).apply()
            if (checked) AdminNotificationService.start(this) else AdminNotificationService.stop(this)
        }
        binding.btnGrantNotif.setOnClickListener {
            if (Build.VERSION.SDK_INT >= 33) ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
        }
        binding.btnRefresh.setOnClickListener { load() }
        binding.btnLogout.setOnClickListener {
            p.edit().clear().apply()
            AdminNotificationService.stop(this)
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }

        load()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) binding.btnGrantNotif.visibility = android.view.View.GONE
    }

    private fun load() {
        binding.btnRefresh.isEnabled = false
        binding.tvOrders.text = "Loading orders…"
        scope.launch {
            val base = getSharedPreferences("admin", Context.MODE_PRIVATE).getString("base_url", "").orEmpty()
            val token = getSharedPreferences("admin", Context.MODE_PRIVATE).getString("token", "").orEmpty()
            if (base.isEmpty() || token.isEmpty()) return@launch
            var statsText = ""
            var ordersText = ""
            try {
                client.newCall(Request.Builder().url("$base/api/v1/admin/dashboard").header("Authorization", "Bearer $token").build()).execute().use { resp ->
                    val json = try { JSONObject(resp.body?.string().orEmpty()) } catch (_: Exception) { JSONObject() }
                    val s = json.optJSONObject("stats")
                    if (s != null) {
                        statsText = "Today: ${s.optInt("today_orders", 0)} orders · ₹${s.optInt("total_revenue", 0)} revenue\nPending approvals: ${s.optInt("pending_approvals", 0)} · Total shops: ${s.optInt("total_shops", 0)}"
                    }
                }
                client.newCall(Request.Builder().url("$base/api/v1/admin/orders").header("Authorization", "Bearer $token").build()).execute().use { resp ->
                    val arr = try { JSONArray(resp.body?.string().orEmpty()) } catch (_: Exception) { JSONArray() }
                    val lines = mutableListOf<String>()
                    for (i in 0 until minOf(arr.length(), 7)) {
                        val o = arr.getJSONObject(i)
                        lines += "#${o.opt("token")} · ₹${o.optInt("total", 0)} · ${o.optString("shop_name")} · ${o.optString("student_name")} · ${o.optString("status")}"
                    }
                    ordersText = if (lines.isEmpty()) "No orders yet." else lines.joinToString("\n")
                }
            } catch (e: Exception) {
                statsText = "Error: ${e.message}"
            }
            withContext(Dispatchers.Main) {
                if (statsText.isNotBlank()) binding.tvStats.text = statsText
                binding.tvOrders.text = ordersText.ifBlank { "No orders yet." }
                binding.btnRefresh.isEnabled = true
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
    }
}