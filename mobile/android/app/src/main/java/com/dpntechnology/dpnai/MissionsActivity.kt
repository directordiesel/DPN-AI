package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.network.MissionApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class MissionsActivity : Activity() {
    private lateinit var credentialStore: SecureCredentialStore
    private lateinit var missionClient: MissionApiClient
    private lateinit var desktopClient: DesktopApiClient
    private lateinit var status: TextView
    private lateinit var missionList: LinearLayout
    private lateinit var objectiveInput: EditText
    private lateinit var projectInput: EditText
    private lateinit var launchButton: Button
    private lateinit var refreshButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        credentialStore = SecureCredentialStore(this)
        missionClient = MissionApiClient(credentialStore)
        desktopClient = DesktopApiClient(credentialStore)
        setContentView(buildUi())
        if (credentialStore.loadDesktopCredential() == null) {
            status.text = "Secure desktop pairing is required before missions can be used."
            launchButton.isEnabled = false
            refreshButton.isEnabled = false
        } else {
            refreshMissions()
        }
    }

    private fun buildUi(): ScrollView {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 48, 40, 48)
            setBackgroundColor(Color.rgb(7, 7, 10))
        }
        root.addView(TextView(this).apply { text = "DPN AI MISSIONS"; textSize = 26f; setTextColor(Color.WHITE) })
        root.addView(TextView(this).apply {
            text = "Launch and inspect missions on the same desktop AI runtime"
            textSize = 13f; setPadding(0, 4, 0, 24); setTextColor(Color.rgb(167, 139, 250))
        })

        status = TextView(this).apply { setTextColor(Color.LTGRAY); text = "Loading missions…"; setPadding(0, 0, 0, 18) }
        root.addView(status)

        objectiveInput = EditText(this).apply {
            hint = "Mission objective"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            minLines = 3
            maxLines = 8
        }
        root.addView(objectiveInput, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        projectInput = EditText(this).apply {
            hint = "Optional project ID"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        root.addView(projectInput, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        launchButton = Button(this).apply {
            text = "Launch Verified Mission"
            setOnClickListener { launchMission() }
        }
        root.addView(launchButton)

        refreshButton = Button(this).apply {
            text = "Refresh Missions"
            setOnClickListener { refreshMissions() }
        }
        root.addView(refreshButton)

        root.addView(TextView(this).apply {
            text = "RECENT MISSIONS"
            textSize = 12f
            gravity = Gravity.START
            setPadding(0, 28, 0, 10)
            setTextColor(Color.rgb(167, 139, 250))
        })
        missionList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(missionList, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        return ScrollView(this).apply {
            setBackgroundColor(Color.rgb(7, 7, 10))
            addView(root)
        }
    }

    private fun refreshMissions() {
        setBusy(true, "Refreshing missions…")
        thread(name = "dpn-mobile-missions-list") {
            val result = runCatching { missionClient.listMissions(limit = 100) }
            runOnUiThread {
                result.onSuccess { missions ->
                    missionList.removeAllViews()
                    if (missions.isEmpty()) {
                        missionList.addView(TextView(this).apply { text = "No missions yet."; setTextColor(Color.GRAY) })
                    } else {
                        missions.forEach { mission -> missionList.addView(buildMissionRow(mission)) }
                    }
                    setBusy(false, "${missions.size} mission${if (missions.size == 1) "" else "s"} loaded from the unified runtime")
                }.onFailure { setBusy(false, "Mission refresh failed: ${it.message ?: "unknown error"}") }
            }
        }
    }

    private fun buildMissionRow(mission: MissionApiClient.MissionSummary): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20, 18, 20, 18)
            setBackgroundColor(Color.rgb(18, 18, 24))
        }
        row.addView(TextView(this).apply {
            text = mission.objective.take(240)
            textSize = 15f
            setTextColor(Color.WHITE)
        })
        row.addView(TextView(this).apply {
            text = "${mission.status.uppercase()} • ${mission.id.take(8)}${mission.projectId?.let { " • project ${it.take(8)}" } ?: ""}"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
        })
        row.addView(Button(this).apply {
            text = "View Mission Details"
            setOnClickListener { loadMissionDetail(mission.id) }
        })
        return row
    }

    private fun launchMission() {
        val objective = objectiveInput.text?.toString().orEmpty().trim()
        if (objective.isEmpty()) {
            status.text = "Enter a mission objective first."
            return
        }
        val projectId = projectInput.text?.toString().orEmpty().trim().ifBlank { null }
        setBusy(true, "Launching mission on desktop runtime…")
        thread(name = "dpn-mobile-mission-launch") {
            val result = runCatching {
                if (projectId != null) {
                    val exists = desktopClient.listProjects().any { it.id == projectId }
                    require(exists) { "project ID was not found on the paired desktop" }
                }
                missionClient.launchMission(objective = objective, projectId = projectId, profile = "director")
            }
            runOnUiThread {
                result.onSuccess { detail ->
                    objectiveInput.setText("")
                    status.text = "Mission ${detail.summary.id.take(8)} finished with status ${detail.summary.status}."
                    refreshMissions()
                }.onFailure { setBusy(false, "Mission launch failed: ${it.message ?: "unknown error"}") }
            }
        }
    }

    private fun loadMissionDetail(missionId: String) {
        setBusy(true, "Loading mission details…")
        thread(name = "dpn-mobile-mission-detail") {
            val result = runCatching { missionClient.getMission(missionId) }
            runOnUiThread {
                result.onSuccess { detail ->
                    val steps = detail.raw.optJSONArray("steps")?.length() ?: 0
                    val verification = detail.raw.optJSONObject("verification") ?: detail.raw.optJSONObject("review")
                    val verificationText = verification?.optString("status")?.ifBlank { null } ?: "not reported"
                    setBusy(false, "Mission ${detail.summary.id.take(8)} • ${detail.summary.status} • $steps steps • verification $verificationText")
                }.onFailure { setBusy(false, "Mission detail failed: ${it.message ?: "unknown error"}") }
            }
        }
    }

    private fun setBusy(busy: Boolean, message: String) {
        status.text = message
        launchButton.isEnabled = !busy
        refreshButton.isEnabled = !busy
    }
}
