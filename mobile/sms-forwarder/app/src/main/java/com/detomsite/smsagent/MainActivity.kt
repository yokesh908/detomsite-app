package com.detomsite.smsagent

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.detomsite.smsagent.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val prefs by lazy { getSharedPreferences("agent", MODE_PRIVATE) }

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
            val ok = grants.values.all { it }
            updatePermissionUI()
            Toast.makeText(
                this,
                if (ok) "SMS access enabled — bank credits will be auto-matched."
                else "SMS permission denied. Please enable it in Settings.",
                Toast.LENGTH_LONG,
            ).show()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // ─── Privacy-first onboarding: explain what data stays / leaves ───
        binding.tvPrivacyBullet1.text = "✓ Bank SMS stays on your phone"
        binding.tvPrivacyBullet2.text = "✓ Only UTR + amount are sent (no balances, no sender, no raw text)"
        binding.tvPrivacyBullet3.text = "✓ Order auto-confirmed → WhatsApp fired to shopkeeper"
        binding.tvPrivacyBullet4.text = "✓ WhatsApp bot sends the order message all by itself"

        binding.etBaseUrl.setText(prefs.getString("base_url", ""))
        binding.etAgentKey.setText(prefs.getString("agent_key", ""))
        binding.etPhone.setText(prefs.getString("phone", ""))
        binding.swEnabled.isChecked = prefs.getBoolean("enabled", true)
        binding.swWABot.isChecked = prefs.getBoolean("wa_bot_enabled", false)

        binding.btnGrantSms.setOnClickListener { requestPerms() }
        binding.btnSave.setOnClickListener { save() }
        binding.swWABot.setOnCheckedChangeListener { _, checked ->
            prefs.edit().putBoolean("wa_bot_enabled", checked).apply()
            if (checked) {
                WhatsAppBotService.start(this)
                Toast.makeText(this, "WhatsApp bot starting…", Toast.LENGTH_SHORT).show()
            } else {
                stopService(Intent(this, WhatsAppBotService::class.java))
                AutoSendState.clear()
                Toast.makeText(this, "WhatsApp bot stopped.", Toast.LENGTH_SHORT).show()
            }
            updatePermissionUI()
        }
        binding.btnGrantAccessibility.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        binding.btnGrantOverlay.setOnClickListener {
            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName"),
                )
            )
        }
        updatePermissionUI()
    }

    override fun onResume() {
        super.onResume()
        updatePermissionUI()
    }

    private fun updatePermissionUI() {
        // SMS section.
        val has = hasPermission(Manifest.permission.RECEIVE_SMS)
                && hasPermission(Manifest.permission.READ_SMS)
        binding.tvPermStatus.text = if (has) "SMS access: ENABLED ✓" else "SMS access: NOT YET GRANTED"
        binding.tvPermStatus.setTextColor(ContextCompat.getColor(this,
            if (has) android.R.color.holo_green_dark else android.R.color.holo_red_dark
        ))
        binding.btnGrantSms.text = if (has) "Re-grant SMS permission" else "Grant SMS permission"

        // WhatsApp bot section.
        val enabled = binding.swWABot.isChecked
        val accOn = isAccessibilityEnabled()
        val overlayOn = Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(this)
        val ready = enabled && accOn && overlayOn
        binding.tvWABotStatus.text = when {
            !enabled -> "Toggle ON to auto-send order WhatsApps"
            !overlayOn -> "Needs “Display over other apps” for auto-open (tap below)"
            !accOn -> "Needs Accessibility enabled for auto-Send (tap below)"
            else -> "READY — order WhatsApps send themselves ✓"
        }
        binding.tvWABotStatus.setTextColor(ContextCompat.getColor(this,
            if (ready) android.R.color.holo_green_dark else android.R.color.holo_orange_dark
        ))
        binding.btnGrantAccessibility.text = if (accOn) "Accessibility: ENABLED ✓" else "Enable Accessibility (auto-Send)"
        binding.btnGrantOverlay.text = if (overlayOn) "Overlay: ENABLED ✓" else "Allow auto-open WhatsApp"
    }

    private fun isAccessibilityEnabled(): Boolean {
        try {
            val expected = componentName.flattenToString()
            val enabled = Settings.Secure.getString(
                contentResolver,
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
            ) ?: return false
            return enabled.split(':').any { it.equals(expected, ignoreCase = true) }
        } catch (e: Exception) {
            return false
        }
    }

    private fun save() {
        val url = binding.etBaseUrl.text.toString().trim().trimEnd('/')
        val key = binding.etAgentKey.text.toString().trim()
        if (url.isEmpty() || key.isEmpty()) {
            Toast.makeText(this, "Backend URL and Agent Key are required.", Toast.LENGTH_LONG).show()
            return
        }
        prefs.edit()
            .putString("base_url", url)
            .putString("agent_key", key)
            .putString("phone", binding.etPhone.text.toString().trim())
            .putBoolean("enabled", binding.swEnabled.isChecked)
            .putBoolean("wa_bot_enabled", binding.swWABot.isChecked)
            .apply()
        if (binding.swWABot.isChecked) WhatsAppBotService.start(this)
        Toast.makeText(this, "Saved. Bank credit SMS will be auto-matched on this device.", Toast.LENGTH_LONG).show()
    }

    private fun requestPerms() {
        val perms = mutableListOf(
            Manifest.permission.RECEIVE_SMS,
            Manifest.permission.READ_SMS,
        )
        if (Build.VERSION.SDK_INT >= 33) perms.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = perms.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) {
            Toast.makeText(this, "All permissions already granted.", Toast.LENGTH_SHORT).show()
        } else {
            permissionLauncher.launch(missing.toTypedArray())
        }
        updatePermissionUI()
    }

    private fun hasPermission(p: String) =
        ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED
}