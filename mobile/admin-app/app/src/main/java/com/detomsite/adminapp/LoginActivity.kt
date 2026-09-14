package com.detomsite.adminapp

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import com.detomsite.adminapp.databinding.ActivityLoginBinding

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = OkHttpClient.Builder().connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS).readTimeout(20, java.util.concurrent.TimeUnit.SECONDS).build()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val p = getSharedPreferences("admin", Context.MODE_PRIVATE)
        if (p.getString("token", null) != null) {
            goMain()
            return
        }
        binding.etBaseUrl.setText(p.getString("base_url", "https://detomsite-backend.vercel.app"))
        binding.etUsername.setText(p.getString("username", ""))

        binding.btnLogin.setOnClickListener { doLogin() }
    }

    private fun doLogin() {
        val base = binding.etBaseUrl.text.toString().trim().trimEnd('/')
        val username = binding.etUsername.text.toString().trim()
        val password = binding.etPassword.text.toString()
        if (base.isEmpty() || username.isEmpty() || password.isEmpty()) {
            binding.tvStatus.text = "Fill in the URL, username and password."
            return
        }
        binding.tvStatus.text = "Signing in…"
        binding.btnLogin.isEnabled = false
        scope.launch {
            val body = JSONObject().put("username", username).put("password", password).toString()
            val req = Request.Builder()
                .url("$base/api/v1/admin/login")
                .post(body.toRequestBody("application/json".toMediaType()))
                .build()
            try {
                client.newCall(req).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    if (resp.code in 200..299) {
                        val json = JSONObject(text)
                        val token = json.optString("access_token")
                        val user = json.optJSONObject("user")
                        val name = user?.optString("name") ?: username
                        if (token.isBlank()) {
                            withContext(Dispatchers.Main) { err("Login succeeded but no token came back.") }
                            return@use
                        }
                        getSharedPreferences("admin", Context.MODE_PRIVATE).edit()
                            .putString("base_url", base)
                            .putString("token", token)
                            .putString("username", username)
                            .putString("user_name", name)
                            .apply()
                        withContext(Dispatchers.Main) { goMain() }
                    } else {
                        val detail = try { JSONObject(text).optString("detail") } catch (_: Exception) { "" }
                        withContext(Dispatchers.Main) { err(if (detail.isNotBlank()) detail else "Login failed (HTTP ${resp.code}).") }
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { err("Could not reach the server: ${e.message}") }
            } finally {
                withContext(Dispatchers.Main) { binding.btnLogin.isEnabled = true }
            }
        }
    }

    private fun err(msg: String) {
        binding.tvStatus.text = msg
    }

    private fun goMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}