package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.dpntechnology.dpnai.network.ApprovalApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class ApprovalsActivity : Activity() {
    private lateinit var api: ApprovalApiClient
    private lateinit var list: LinearLayout
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = SecureCredentialStore(this)
        if (store.loadDesktopCredential() == null) {
            finish()
            return
        }
        api = ApprovalApiClient(store)
        setContentView(buildUi())
        refresh()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 48, 36, 36)
            setBackgroundColor(Color.rgb(7, 7, 10))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        root.addView(TextView(this).apply { text = "Approval Inbox"; textSize = 28f; setTextColor(Color.WHITE) })
        root.addView(TextView(this).apply {
            text = "Explicit human control for protected DPN AI actions"
            textSize = 13f; setTextColor(Color.rgb(167, 139, 250)); setPadding(0, 4, 0, 20)
        })
        status = TextView(this).apply { text = "Loading pending approvals…"; setTextColor(Color.LTGRAY); setPadding(0, 0, 0, 16) }
        root.addView(status)
        root.addView(Button(this).apply { text = "Refresh Pending Approvals"; setOnClickListener { refresh() } })
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, 16, 0, 0) }
        root.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun refresh() {
        status.text = "Loading pending approvals…"
        thread(name = "dpn-mobile-approvals") {
            val result = runCatching { api.listApprovals("pending", 100) }
            runOnUiThread {
                result.fold(
                    onSuccess = { approvals ->
                        list.removeAllViews()
                        status.text = if (approvals.isEmpty()) "No pending approvals" else "${approvals.size} pending approval(s)"
                        approvals.forEach { approval -> list.addView(buildApprovalCard(approval)) }
                    },
                    onFailure = { status.text = "Approval inbox unavailable: ${it.message ?: "unknown error"}" },
                )
            }
        }
    }

    private fun buildApprovalCard(approval: ApprovalApiClient.ApprovalSummary): View {
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            setBackgroundColor(Color.rgb(18, 18, 24))
            addView(TextView(this@ApprovalsActivity).apply { text = approval.action; textSize = 18f; setTextColor(Color.WHITE) })
            addView(TextView(this@ApprovalsActivity).apply {
                text = approval.reason.ifBlank { "No additional reason supplied by the runtime." }
                setTextColor(Color.LTGRAY); setPadding(0, 8, 0, 12)
            })
            addView(TextView(this@ApprovalsActivity).apply {
                text = "Status: ${approval.status}${approval.createdAt?.let { " • $it" } ?: ""}"
                textSize = 12f; setTextColor(Color.GRAY)
            })
            addView(LinearLayout(this@ApprovalsActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.END
                setPadding(0, 16, 0, 0)
                addView(Button(this@ApprovalsActivity).apply {
                    text = "Deny"
                    setOnClickListener { submitDecision(approval.id, "denied") }
                })
                addView(Button(this@ApprovalsActivity).apply {
                    text = "Approve"
                    setOnClickListener { submitDecision(approval.id, "approved") }
                })
            })
        }
    }

    private fun submitDecision(approvalId: String, decision: String) {
        status.text = if (decision == "approved") "Approving protected action…" else "Denying protected action…"
        thread(name = "dpn-mobile-approval-decision") {
            val result = runCatching { api.decide(approvalId, decision) }
            runOnUiThread {
                result.fold(
                    onSuccess = {
                        status.text = if (decision == "approved") "Approval recorded" else "Denial recorded"
                        refresh()
                    },
                    onFailure = { status.text = "Decision failed: ${it.message ?: "unknown error"}" },
                )
            }
        }
    }
}
