package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.dpntechnology.dpnai.diagnostics.MobileDiagnostics
import com.dpntechnology.dpnai.network.PairingApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import java.util.UUID
import kotlin.concurrent.thread

class PairingActivity : Activity() {
    private lateinit var endpoint: EditText
    private lateinit var challengeId: EditText
    private lateinit var secret: EditText
    private lateinit var deviceName: EditText
    private lateinit var status: TextView
    private lateinit var pairButton: Button
    private lateinit var credentialStore: SecureCredentialStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        credentialStore = SecureCredentialStore(this)
        setContentView(buildView())
    }

    private fun buildView(): ScrollView {
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(Color.rgb(7, 7, 10))
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(40, 48, 40, 64)
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        }
        scroll.addView(root)

        root.addView(TextView(this).apply {
            text = "SECURE DESKTOP PAIRING"
            textSize = 24f
            setTextColor(Color.WHITE)
        })
        root.addView(TextView(this).apply {
            text = "Enter the HTTPS desktop endpoint and the short-lived one-time challenge shown by DPN AI Desktop. The desktop-wide API token is never entered on Android."
            textSize = 13f
            setPadding(0, 16, 0, 24)
            setTextColor(Color.LTGRAY)
        })

        endpoint = field(root, "Desktop HTTPS endpoint", "https://desktop.example:8443")
        challengeId = field(root, "Pairing challenge ID", "")
        secret = field(root, "One-time pairing proof", "")
        deviceName = field(root, "Device name", Build.MODEL.take(80).ifBlank { "Android Device" })

        status = TextView(this).apply {
            text = if (credentialStore.loadLocalCredential() == null) "Not paired" else "A local desktop credential is already stored"
            textSize = 13f
            setPadding(0, 20, 0, 16)
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(167, 139, 250))
        }
        root.addView(status)

        pairButton = Button(this).apply {
            text = "Pair This Device"
            setOnClickListener { pair() }
        }
        root.addView(pairButton)

        root.addView(Button(this).apply {
            text = "Remove Local Pairing"
            setOnClickListener {
                credentialStore.clear()
                status.text = "Local pairing removed"
            }
        })
        return scroll
    }

    private fun field(root: LinearLayout, label: String, initial: String): EditText {
        root.addView(TextView(this).apply {
            text = label
            textSize = 12f
            setPadding(0, 14, 0, 6)
            setTextColor(Color.rgb(167, 139, 250))
        })
        return EditText(this).apply {
            setText(initial)
            setSingleLine(true)
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            root.addView(this)
        }
    }

    private fun pair() {
        pairButton.isEnabled = false
        status.text = "Verifying one-time pairing proof…"
        val baseUrl = endpoint.text.toString().trim()
        val challenge = challengeId.text.toString()
        val proof = secret.text.toString()
        val name = deviceName.text.toString()
        val deviceId = "android-${UUID.randomUUID()}"

        thread(name = "dpn-mobile-pair") {
            val result = runCatching {
                PairingApiClient().completePairing(baseUrl, challenge, proof, deviceId, name).also {
                    credentialStore.saveDesktopCredential(baseUrl, it.deviceId, it.token)
                }
            }
            result.exceptionOrNull()?.let { MobileDiagnostics.recordError(this, "pairing", it) }
            runOnUiThread {
                pairButton.isEnabled = true
                if (result.isSuccess) {
                    challengeId.setText("")
                    secret.setText("")
                    status.text = "Paired securely • device credential stored in Android Keystore"
                } else {
                    status.text = "Pairing failed • ${result.exceptionOrNull()?.message?.take(180) ?: "unknown error"}"
                }
            }
        }
    }
}
