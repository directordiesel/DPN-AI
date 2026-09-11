package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.dpntechnology.dpnai.diagnostics.MobileDiagnostics
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class GatewayActivity : Activity() {
    private lateinit var store: SecureCredentialStore
    private lateinit var endpoint: EditText
    private lateinit var token: EditText
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        store = SecureCredentialStore(this)
        setContentView(ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(Color.rgb(7, 7, 10))
            addView(
                buildUi(),
                ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            )
        })
        refreshStatus()
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(36, 48, 36, 36)
        setBackgroundColor(Color.rgb(7, 7, 10))
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        addView(TextView(this@GatewayActivity).apply { text = "DPN AI - Secure Remote Gateway"; textSize = 24f; setTextColor(Color.WHITE) })
        addView(TextView(this@GatewayActivity).apply {
            text = "Remote mode requires an HTTPS gateway and explicit DPN access token. Pair locally first."
            setTextColor(Color.LTGRAY); setPadding(0, 12, 0, 24)
        })
        endpoint = EditText(this@GatewayActivity).apply { hint = "https://gateway.example.com/"; setTextColor(Color.WHITE); setHintTextColor(Color.GRAY) }
        addView(endpoint, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        token = EditText(this@GatewayActivity).apply {
            hint = "Gateway / DPN access token"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
            isSaveEnabled = false
            setSingleLine(true)
        }
        addView(token, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        addView(Button(this@GatewayActivity).apply { text = "Save Remote Gateway"; setOnClickListener { saveGateway() } })
        addView(Button(this@GatewayActivity).apply { text = "Use Remote Gateway"; setOnClickListener { switchMode(true) } })
        addView(Button(this@GatewayActivity).apply { text = "Use Local Desktop"; setOnClickListener { switchMode(false) } })
        addView(Button(this@GatewayActivity).apply { text = "Test Active Connection"; setOnClickListener { testConnection() } })
        addView(Button(this@GatewayActivity).apply { text = "Remove Remote Gateway"; setOnClickListener { store.clearRemoteGateway(); refreshStatus() } })
        status = TextView(this@GatewayActivity).apply { setTextColor(Color.LTGRAY); setPadding(0, 24, 0, 0) }
        addView(status)
    }

    private fun saveGateway() {
        val result = runCatching { store.saveRemoteGateway(endpoint.text.toString(), token.text.toString()) }
        result.exceptionOrNull()?.let { MobileDiagnostics.recordError(this, "gateway-save", it) }
        status.text = result.fold(
            { "Remote connection saved securely. It is not active until you choose Use Remote Gateway." },
            { "Remote connection settings were rejected. Check the HTTPS address and access token, then try again. Technical details are available in Diagnostics & Status." },
        )
        if (result.isSuccess) token.text.clear()
    }

    private fun switchMode(remote: Boolean) {
        val result = runCatching { store.setRemoteMode(remote) }
        result.exceptionOrNull()?.let { MobileDiagnostics.recordError(this, "gateway-mode", it) }
        status.text = result.fold(
            { if (remote) "Remote connection mode active." else "Local desktop mode active." },
            { "Could not change connection mode. Confirm pairing and saved remote connection settings, then try again. Technical details are available in Diagnostics & Status." },
        )
    }

    private fun testConnection() {
        status.text = "Testing active encrypted connection..."
        thread(name = "dpn-gateway-test") {
            val result = runCatching { DesktopApiClient(store).fetchDesktopSummary() }
            result.exceptionOrNull()?.let { MobileDiagnostics.recordError(this, "gateway-test", it) }
            runOnUiThread {
                status.text = result.fold(
                    { "Active connection authenticated and reachable." },
                    { "Connection test failed. Confirm DPN AI is running, verify the selected local/remote mode, and try again. Technical details are available in Diagnostics & Status." },
                )
            }
        }
    }

    private fun refreshStatus() {
        status.text = when {
            store.loadLocalCredential() == null -> "Local pairing is required before remote gateway setup."
            store.isRemoteMode() -> "Current mode: REMOTE GATEWAY"
            store.hasRemoteGateway() -> "Current mode: LOCAL DESKTOP - Remote gateway configured"
            else -> "Current mode: LOCAL DESKTOP - Remote gateway not configured"
        }
    }
}
