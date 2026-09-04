package com.dpntechnology.dpnai

import android.app.Activity
import android.content.Intent
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

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var credentialStore: SecureCredentialStore
    private val capabilityButtons = mutableListOf<Button>()
    private lateinit var gatewayButton: Button
    private lateinit var diagnosticsButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        credentialStore = SecureCredentialStore(this)
        setContentView(buildShell())
        refreshConnectionState()
    }

    override fun onResume() {
        super.onResume()
        if (::credentialStore.isInitialized) refreshConnectionState()
    }

    private fun buildShell(): ScrollView {
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(Color.rgb(7, 7, 10))
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(40, 56, 40, 64)
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        }
        scroll.addView(root)

        root.addView(TextView(this).apply { text = "DPN AI"; textSize = 32f; setTextColor(Color.WHITE) })
        root.addView(TextView(this).apply {
            text = "MOBILE CONTROL CENTER • ${BuildConfig.VERSION_NAME}"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
        })
        status = TextView(this).apply {
            textSize = 15f
            setPadding(0, 32, 0, 20)
            gravity = Gravity.CENTER
            setTextColor(Color.LTGRAY)
        }
        root.addView(status)
        root.addView(Button(this).apply { text = "Check Active Connection"; setOnClickListener { checkDesktopConnection() } })

        addSection(root, "ASSIST")
        addCapability(root, "Unified Chat", ChatActivity::class.java)
        addCapability(root, "Voice Console", VoiceActivity::class.java)
        addCapability(root, "Vision Console", VisionActivity::class.java)
        addCapability(root, "File Intelligence", FileActivity::class.java)

        addSection(root, "OPERATE")
        addCapability(root, "Projects & Tasks", ProjectsActivity::class.java)
        addCapability(root, "Missions", MissionsActivity::class.java)
        addCapability(root, "Approval Inbox", ApprovalsActivity::class.java)
        addCapability(root, "Notification Center", NotificationsActivity::class.java)

        addSection(root, "SYSTEM")
        gatewayButton = Button(this).apply {
            text = "Secure Remote Gateway"
            isEnabled = false
            setOnClickListener { startActivity(Intent(this@MainActivity, GatewayActivity::class.java)) }
        }
        root.addView(gatewayButton)
        diagnosticsButton = Button(this).apply {
            text = "Diagnostics & Status"
            setOnClickListener { startActivity(Intent(this@MainActivity, DiagnosticsActivity::class.java)) }
        }
        root.addView(diagnosticsButton)
        root.addView(TextView(this).apply {
            text = "DPN Technology • Secure shared-runtime mobile client"
            textSize = 12f
            setPadding(0, 28, 0, 0)
            gravity = Gravity.CENTER
            setTextColor(Color.GRAY)
        })
        return scroll
    }

    private fun addSection(root: LinearLayout, title: String) {
        root.addView(TextView(this).apply {
            text = title
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 30, 0, 8)
        })
    }

    private fun addCapability(root: LinearLayout, label: String, target: Class<out Activity>) {
        val button = Button(this).apply {
            text = label
            isEnabled = false
            setOnClickListener { startActivity(Intent(this@MainActivity, target)) }
        }
        capabilityButtons += button
        root.addView(button)
    }

    private fun refreshConnectionState() {
        val locallyPaired = credentialStore.loadLocalCredential() != null
        val active = credentialStore.loadDesktopCredential() != null
        setCapabilityButtons(active)
        gatewayButton.isEnabled = locallyPaired
        status.text = when {
            !locallyPaired -> "Not paired • secure local desktop pairing required"
            credentialStore.isRemoteMode() -> "REMOTE GATEWAY • encrypted credential active"
            else -> "LOCAL DESKTOP • encrypted credential active"
        }
    }

    private fun setCapabilityButtons(enabled: Boolean) = capabilityButtons.forEach { it.isEnabled = enabled }

    private fun checkDesktopConnection() {
        status.text = "Checking active encrypted connection…"
        thread(name = "dpn-mobile-health") {
            val result = runCatching { DesktopApiClient(credentialStore).fetchDesktopSummary() }
            result.exceptionOrNull()?.let { MobileDiagnostics.recordError(this, "connection-check", it) }
            runOnUiThread {
                status.text = result.fold(
                    onSuccess = {
                        setCapabilityButtons(true)
                        if (credentialStore.isRemoteMode()) "REMOTE GATEWAY • authenticated and reachable" else "LOCAL DESKTOP • authenticated and reachable"
                    },
                    onFailure = {
                        setCapabilityButtons(false)
                        "Connection unavailable • ${it.message?.take(180) ?: "unknown error"}"
                    },
                )
            }
        }
    }
}
