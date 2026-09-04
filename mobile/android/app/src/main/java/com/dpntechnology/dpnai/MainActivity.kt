package com.dpntechnology.dpnai

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var credentialStore: SecureCredentialStore
    private lateinit var chatButton: Button
    private lateinit var voiceButton: Button
    private lateinit var visionButton: Button
    private lateinit var fileButton: Button
    private lateinit var projectsButton: Button
    private lateinit var missionsButton: Button
    private lateinit var approvalsButton: Button
    private lateinit var notificationsButton: Button
    private lateinit var gatewayButton: Button

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

    private fun buildShell(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(48, 64, 48, 48)
            setBackgroundColor(Color.rgb(7, 7, 10))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        root.addView(TextView(this).apply { text = "DPN AI"; textSize = 30f; setTextColor(Color.WHITE) })
        root.addView(TextView(this).apply { text = "MOBILE CONTROL CENTER v1"; textSize = 12f; setTextColor(Color.rgb(167, 139, 250)) })
        status = TextView(this).apply { textSize = 16f; setPadding(0, 72, 0, 36); setTextColor(Color.LTGRAY) }
        root.addView(status)
        root.addView(Button(this).apply { text = "Check Active Connection"; setOnClickListener { checkDesktopConnection() } })
        chatButton = capabilityButton("Open Unified Chat", ChatActivity::class.java); root.addView(chatButton)
        voiceButton = capabilityButton("Open Voice Console", VoiceActivity::class.java); root.addView(voiceButton)
        visionButton = capabilityButton("Open Vision Console", VisionActivity::class.java); root.addView(visionButton)
        fileButton = capabilityButton("Open File Console", FileActivity::class.java); root.addView(fileButton)
        projectsButton = capabilityButton("Open Projects & Tasks", ProjectsActivity::class.java); root.addView(projectsButton)
        missionsButton = capabilityButton("Open Missions", MissionsActivity::class.java); root.addView(missionsButton)
        approvalsButton = capabilityButton("Open Approval Inbox", ApprovalsActivity::class.java); root.addView(approvalsButton)
        notificationsButton = capabilityButton("Open Notification Center", NotificationsActivity::class.java); root.addView(notificationsButton)
        gatewayButton = Button(this).apply {
            text = "Secure Remote Gateway"
            isEnabled = false
            setOnClickListener { startActivity(Intent(this@MainActivity, GatewayActivity::class.java)) }
        }
        root.addView(gatewayButton)
        root.addView(TextView(this).apply {
            text = "Chat • Voice • Vision • Files • Projects • Missions • Approvals • Notifications • Remote Gateway"
            textSize = 13f; setPadding(0, 48, 0, 0); gravity = Gravity.CENTER; setTextColor(Color.GRAY)
        })
        return root
    }

    private fun capabilityButton(label: String, target: Class<out Activity>) = Button(this).apply {
        text = label
        isEnabled = false
        setOnClickListener { startActivity(Intent(this@MainActivity, target)) }
    }

    private fun refreshConnectionState() {
        val locallyPaired = credentialStore.loadLocalCredential() != null
        val active = credentialStore.loadDesktopCredential() != null
        setCapabilityButtons(active)
        gatewayButton.isEnabled = locallyPaired
        status.text = when {
            !locallyPaired -> "Not paired — secure local desktop pairing required"
            credentialStore.isRemoteMode() -> "Secure remote gateway mode active — mobile controls ready"
            else -> "Local desktop mode active — mobile controls ready"
        }
    }

    private fun setCapabilityButtons(enabled: Boolean) {
        chatButton.isEnabled = enabled
        voiceButton.isEnabled = enabled
        visionButton.isEnabled = enabled
        fileButton.isEnabled = enabled
        projectsButton.isEnabled = enabled
        missionsButton.isEnabled = enabled
        approvalsButton.isEnabled = enabled
        notificationsButton.isEnabled = enabled
    }

    private fun checkDesktopConnection() {
        status.text = "Checking active encrypted connection…"
        thread(name = "dpn-mobile-health") {
            val result = runCatching { DesktopApiClient(credentialStore).fetchDesktopSummary() }
            runOnUiThread {
                status.text = result.fold(
                    onSuccess = { setCapabilityButtons(true); if (credentialStore.isRemoteMode()) "Remote gateway authenticated and reachable" else "Local desktop authenticated and reachable" },
                    onFailure = { setCapabilityButtons(false); "Active connection unavailable: ${it.message ?: "unknown error"}" },
                )
            }
        }
    }
}
