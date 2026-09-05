package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
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
        store = SecureCredentialStore(this)
        setContentView(buildUi())
        refreshStatus()
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(36, 48, 36, 36)
        setBackgroundColor(Color.rgb(7, 7, 10))
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        addView(TextView(this@GatewayActivity).apply { text = "DPN AI • Secure Remote Gateway"; textSize = 24f; setTextColor(Color.WHITE) })
        addView(TextView(this@GatewayActivity).apply {
            text = "Remote mode requires an HTTPS gateway and explicit DPN access token. Pair locally first."
            setTextColor(Color.LTGRAY); setPadding(0, 12, 0, 24)
        })
        endpoint = EditText(this@GatewayActivity).apply { hint = "https://gateway.example.com/"; setTextColor(Color.WHITE); setHintTextColor(Color.GRAY) }
        addView(endpoint, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        token = EditText(this@GatewayActivity).apply { hint = "Gateway / DPN access token"; setTextColor(Color.WHITE); setHintTextColor(Color.GRAY) }
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
        status.text = result.fold({ "Remote gateway saved securely. It is not active until you choose Use Remote Gateway." }, { "Gateway rejected: ${it.message}" })
        if (result.isSuccess) token.text.clear()
    }

    private fun switchMode(remote: Boolean) {
        val result = runCatching { store.setRemoteMode(remote) }
        status.text = result.fold({ if (remote) "Remote gateway mode active." else "Local desktop mode active." }, { "Mode switch failed: ${it.message}" })
    }

    private fun testConnection() {
        status.text = "Testing active encrypted connection…"
        thread(name = "dpn-gateway-test") {
            val result = runCatching { DesktopApiClient(store).fetchDesktopSummary() }
            runOnUiThread { status.text = result.fold({ "Active connection authenticated and reachable." }, { "Connection test failed: ${it.message}" }) }
        }
    }

    private fun refreshStatus() {
        status.text = when {
            store.loadLocalCredential() == null -> "Local pairing is required before remote gateway setup."
            store.isRemoteMode() -> "Current mode: REMOTE GATEWAY"
            store.hasRemoteGateway() -> "Current mode: LOCAL DESKTOP • Remote gateway configured"
            else -> "Current mode: LOCAL DESKTOP • Remote gateway not configured"
        }
    }
}
