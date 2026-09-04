package com.dpntechnology.dpnai

import android.app.Activity
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        credentialStore = SecureCredentialStore(this)
        setContentView(buildShell())
        refreshConnectionState()
    }

    private fun buildShell(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(48, 64, 48, 48)
            setBackgroundColor(Color.rgb(7, 7, 10))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        root.addView(TextView(this).apply {
            text = "DPN AI"
            textSize = 30f
            setTextColor(Color.WHITE)
        })
        root.addView(TextView(this).apply {
            text = "MOBILE CONTROL CENTER v1"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
        })
        status = TextView(this).apply {
            textSize = 16f
            setPadding(0, 72, 0, 36)
            setTextColor(Color.LTGRAY)
        }
        root.addView(status)
        root.addView(Button(this).apply {
            text = "Check Desktop Connection"
            setOnClickListener { checkDesktopConnection() }
        })
        root.addView(TextView(this).apply {
            text = "Chat • Voice • Vision • Files • Projects • Missions • Approvals"
            textSize = 13f
            setPadding(0, 48, 0, 0)
            gravity = Gravity.CENTER
            setTextColor(Color.GRAY)
        })
        return root
    }

    private fun refreshConnectionState() {
        val paired = credentialStore.loadDesktopCredential() != null
        status.text = if (paired) "Paired device credential secured by Android Keystore" else "Not paired — secure desktop pairing required"
    }

    private fun checkDesktopConnection() {
        status.text = "Checking encrypted desktop connection…"
        thread(name = "dpn-mobile-health") {
            val result = runCatching { DesktopApiClient(credentialStore).fetchDesktopSummary() }
            runOnUiThread {
                status.text = result.fold(
                    onSuccess = { "Desktop API authenticated and reachable" },
                    onFailure = { "Desktop connection unavailable: ${it.message ?: "unknown error"}" },
                )
            }
        }
    }
}
