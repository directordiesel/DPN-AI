package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.dpntechnology.dpnai.diagnostics.MobileDiagnostics
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class DiagnosticsActivity : Activity() {
    private lateinit var credentialStore: SecureCredentialStore
    private lateinit var body: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        credentialStore = SecureCredentialStore(this)
        setContentView(buildUi())
        renderLocalStatus()
    }

    private fun buildUi(): ScrollView {
        val scroll = ScrollView(this).apply { setBackgroundColor(Color.rgb(7, 7, 10)); isFillViewport = true }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(40, 48, 40, 64)
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        }
        scroll.addView(root)
        root.addView(TextView(this).apply { text = "DPN AI Diagnostics"; textSize = 26f; setTextColor(Color.WHITE) })
        root.addView(TextView(this).apply { text = "BUILD • CONNECTION • SECURITY"; textSize = 12f; setTextColor(Color.rgb(167, 139, 250)); setPadding(0, 4, 0, 24) })
        body = TextView(this).apply { textSize = 14f; setTextColor(Color.LTGRAY); setPadding(0, 0, 0, 24) }
        root.addView(body)
        root.addView(Button(this).apply { text = "Run Connection Diagnostic"; setOnClickListener { runConnectionDiagnostic() } })
        root.addView(Button(this).apply { text = "Clear Last Local Error"; setOnClickListener { MobileDiagnostics.clear(this@DiagnosticsActivity); renderLocalStatus() } })
        return scroll
    }

    private fun renderLocalStatus(extra: String? = null) {
        val local = credentialStore.loadLocalCredential()
        val remoteConfigured = credentialStore.hasRemoteGateway()
        val active = credentialStore.loadDesktopCredential()
        val mode = if (credentialStore.isRemoteMode()) "REMOTE_GATEWAY" else "LOCAL_DESKTOP"
        val lastError = MobileDiagnostics.lastError(this) ?: "None recorded"
        body.text = buildString {
            appendLine("App version: ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
            appendLine("Build type: ${BuildConfig.BUILD_TYPE}")
            appendLine("Debuggable: ${BuildConfig.DEBUG}")
            appendLine("Android API: ${android.os.Build.VERSION.SDK_INT}")
            appendLine()
            appendLine("Local pairing: ${if (local != null) "configured" else "not configured"}")
            appendLine("Remote gateway: ${if (remoteConfigured) "configured" else "not configured"}")
            appendLine("Active mode: $mode")
            appendLine("Active credential: ${if (active != null) "available" else "unavailable"}")
            appendLine("Cleartext traffic: disabled by manifest")
            appendLine("Application backup: disabled")
            appendLine("Credential storage: Android Keystore AES/GCM")
            appendLine()
            appendLine("Last local error:")
            appendLine(lastError)
            extra?.let { appendLine(); appendLine(it) }
        }
    }

    private fun runConnectionDiagnostic() {
        renderLocalStatus("Connection diagnostic running…")
        thread(name = "dpn-mobile-diagnostics") {
            val result = runCatching { DesktopApiClient(credentialStore).fetchDesktopSummary() }
            result.exceptionOrNull()?.let { MobileDiagnostics.recordError(this, "diagnostics", it) }
            runOnUiThread {
                renderLocalStatus(
                    result.fold(
                        onSuccess = { "Connection diagnostic: PASS — authenticated desktop runtime reachable." },
                        onFailure = { "Connection diagnostic: FAIL — ${it.message?.take(240) ?: "unknown error"}" },
                    )
                )
            }
        }
    }
}
