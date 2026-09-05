package com.dpntechnology.dpnai

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.dpntechnology.dpnai.network.ApprovalApiClient
import com.dpntechnology.dpnai.network.MissionApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class NotificationsActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var feed: LinearLayout
    private lateinit var refreshButton: Button
    private lateinit var credentialStore: SecureCredentialStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        credentialStore = SecureCredentialStore(this)
        createNotificationChannel()
        setContentView(buildUi())
        refreshFeed(postSystemNotifications = false)
    }

    private fun buildUi(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(32, 44, 32, 32)
            setBackgroundColor(Color.rgb(7, 7, 10))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        root.addView(TextView(this).apply {
            text = "DPN AI • Notifications"
            textSize = 25f
            setTextColor(Color.WHITE)
        })
        root.addView(TextView(this).apply {
            text = "Missions • Approvals • Explicit refresh only"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 4, 0, 20)
        })
        refreshButton = Button(this).apply {
            text = "Refresh Notification Center"
            setOnClickListener { refreshFeed(postSystemNotifications = true) }
        }
        root.addView(refreshButton)
        status = TextView(this).apply {
            text = "Loading current DPN AI state…"
            setTextColor(Color.LTGRAY)
            setPadding(0, 18, 0, 14)
        }
        root.addView(status)
        feed = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val scroll = ScrollView(this).apply { addView(feed) }
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        return root
    }

    private fun refreshFeed(postSystemNotifications: Boolean) {
        refreshButton.isEnabled = false
        status.text = "Synchronizing missions and approvals…"
        thread(name = "dpn-mobile-notification-refresh") {
            val result = runCatching {
                val missions = MissionApiClient(credentialStore).listMissions(limit = 50)
                val approvals = ApprovalApiClient(credentialStore).listApprovals(status = "pending", limit = 50)
                Pair(missions, approvals)
            }
            runOnUiThread {
                refreshButton.isEnabled = true
                result.onSuccess { (missions, approvals) ->
                    renderFeed(missions, approvals)
                    status.text = "${approvals.size} pending approvals • ${missions.size} recent missions"
                    if (postSystemNotifications) maybePostNotifications(missions, approvals)
                }.onFailure { error ->
                    feed.removeAllViews()
                    status.text = "Notification sync failed: ${error.message ?: "unknown error"}"
                }
            }
        }
    }

    private fun renderFeed(
        missions: List<MissionApiClient.MissionSummary>,
        approvals: List<ApprovalApiClient.ApprovalSummary>,
    ) {
        feed.removeAllViews()
        if (approvals.isEmpty() && missions.isEmpty()) {
            addFeedItem("No current mission or approval notifications.")
            return
        }
        approvals.forEach { approval ->
            addFeedItem("APPROVAL REQUIRED\n${approval.action}\n${approval.reason.take(320)}")
        }
        missions.take(20).forEach { mission ->
            addFeedItem("MISSION • ${mission.status.uppercase()}\n${mission.objective.take(420)}")
        }
    }

    private fun addFeedItem(text: String) {
        feed.addView(TextView(this).apply {
            this.text = text
            textSize = 15f
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(18, 16, 27))
            setPadding(18, 16, 18, 16)
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            setMargins(0, 0, 0, 12)
        })
    }

    private fun maybePostNotifications(
        missions: List<MissionApiClient.MissionSummary>,
        approvals: List<ApprovalApiClient.ApprovalSummary>,
    ) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
            status.text = "Notification permission requested. Refresh again after granting to post system notifications."
            return
        }
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (approvals.isNotEmpty()) {
            manager.notify(
                NOTIFICATION_APPROVALS,
                buildNotification(
                    title = "DPN AI approval required",
                    text = "${approvals.size} protected action${if (approvals.size == 1) "" else "s"} waiting for your decision.",
                    target = ApprovalsActivity::class.java,
                )
            )
        }
        val attentionMission = missions.firstOrNull { it.status in setOf("completed", "failed", "paused") }
        if (attentionMission != null) {
            manager.notify(
                NOTIFICATION_MISSION,
                buildNotification(
                    title = "DPN AI mission ${attentionMission.status}",
                    text = attentionMission.objective.take(180),
                    target = MissionsActivity::class.java,
                )
            )
        }
    }

    private fun buildNotification(title: String, text: String, target: Class<out Activity>): android.app.Notification {
        val intent = Intent(this, target)
        val pending = PendingIntent.getActivity(
            this,
            target.name.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return android.app.Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(android.app.Notification.BigTextStyle().bigText(text))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
    }

    private fun createNotificationChannel() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(CHANNEL_ID, "DPN AI activity", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Mission and approval notifications requested from the DPN AI mobile control center"
        }
        manager.createNotificationChannel(channel)
    }

    companion object {
        private const val CHANNEL_ID = "dpn_ai_activity"
        private const val REQUEST_NOTIFICATIONS = 4401
        private const val NOTIFICATION_APPROVALS = 4402
        private const val NOTIFICATION_MISSION = 4403
    }
}
