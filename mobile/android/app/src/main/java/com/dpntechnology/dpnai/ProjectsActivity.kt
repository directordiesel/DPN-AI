package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.TextView
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class ProjectsActivity : Activity() {
    private lateinit var api: DesktopApiClient
    private lateinit var projectSpinner: Spinner
    private lateinit var taskSpinner: Spinner
    private lateinit var status: TextView
    private lateinit var projectName: EditText
    private lateinit var taskTitle: EditText
    private var projects = emptyList<DesktopApiClient.ProjectSummary>()
    private var tasks = emptyList<DesktopApiClient.TaskSummary>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = DesktopApiClient(SecureCredentialStore(this))
        setContentView(buildUi())
        refreshProjects()
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(32, 40, 32, 32)
        setBackgroundColor(Color.rgb(7, 7, 10))
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        addView(TextView(this@ProjectsActivity).apply {
            text = "DPN AI • Projects & Tasks"
            textSize = 25f
            setTextColor(Color.WHITE)
        })
        addView(TextView(this@ProjectsActivity).apply {
            text = "Shared desktop/mobile project state"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 4, 0, 24)
        })

        projectSpinner = Spinner(this@ProjectsActivity)
        addView(projectSpinner)
        addView(Button(this@ProjectsActivity).apply {
            text = "Load Selected Project"
            setOnClickListener { loadSelectedProject() }
        })

        taskSpinner = Spinner(this@ProjectsActivity)
        addView(taskSpinner)
        addView(Button(this@ProjectsActivity).apply {
            text = "Mark Task Ready"
            setOnClickListener { updateSelectedTask("ready") }
        })
        addView(Button(this@ProjectsActivity).apply {
            text = "Mark Task Running"
            setOnClickListener { updateSelectedTask("running") }
        })
        addView(Button(this@ProjectsActivity).apply {
            text = "Mark Task Done"
            setOnClickListener { updateSelectedTask("done") }
        })

        projectName = EditText(this@ProjectsActivity).apply {
            hint = "New project name"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        addView(projectName)
        addView(Button(this@ProjectsActivity).apply {
            text = "Create Project"
            setOnClickListener { createProject() }
        })

        taskTitle = EditText(this@ProjectsActivity).apply {
            hint = "New task title"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        addView(taskTitle)
        addView(Button(this@ProjectsActivity).apply {
            text = "Create Task"
            setOnClickListener { createTask() }
        })

        status = TextView(this@ProjectsActivity).apply {
            text = "Syncing projects…"
            setTextColor(Color.LTGRAY)
            setPadding(0, 22, 0, 0)
        }
        addView(status)
    }

    private fun refreshProjects(selectId: String? = null) {
        status.text = "Syncing projects…"
        thread(name = "dpn-mobile-project-sync") {
            val result = runCatching { api.listProjects() }
            runOnUiThread {
                result.onSuccess { items ->
                    projects = items
                    projectSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
                        if (items.isEmpty()) listOf("No projects") else items.map { "${it.name} • ${it.status}" })
                    val index = selectId?.let { id -> items.indexOfFirst { it.id == id } }?.takeIf { it >= 0 } ?: 0
                    if (items.isNotEmpty()) {
                        projectSpinner.setSelection(index)
                        loadProject(items[index])
                    } else {
                        tasks = emptyList()
                        taskSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, listOf("No tasks"))
                        status.text = "No projects yet. Create one to begin."
                    }
                }.onFailure { status.text = "Project sync failed: ${it.message ?: "unknown error"}" }
            }
        }
    }

    private fun loadSelectedProject() {
        val project = projects.getOrNull(projectSpinner.selectedItemPosition) ?: return
        loadProject(project)
    }

    private fun loadProject(project: DesktopApiClient.ProjectSummary) {
        status.text = "Loading ${project.name} task board…"
        thread(name = "dpn-mobile-task-sync") {
            val result = runCatching { api.getProjectTasks(project.id) }
            runOnUiThread {
                result.onSuccess { items ->
                    tasks = items
                    taskSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
                        if (items.isEmpty()) listOf("No tasks") else items.map { "[${it.status}] ${it.title} • ${it.priority}" })
                    status.text = "${project.name} • ${items.size} tasks synced"
                }.onFailure { status.text = "Task sync failed: ${it.message ?: "unknown error"}" }
            }
        }
    }

    private fun createProject() {
        val name = projectName.text.toString().trim()
        if (name.isEmpty()) return
        status.text = "Creating project…"
        thread(name = "dpn-mobile-project-create") {
            val result = runCatching { api.createProject(name) }
            runOnUiThread {
                result.onSuccess { project -> projectName.setText(""); refreshProjects(project.id) }
                    .onFailure { status.text = "Project creation failed: ${it.message ?: "unknown error"}" }
            }
        }
    }

    private fun createTask() {
        val project = projects.getOrNull(projectSpinner.selectedItemPosition) ?: return
        val title = taskTitle.text.toString().trim()
        if (title.isEmpty()) return
        status.text = "Creating task…"
        thread(name = "dpn-mobile-task-create") {
            val result = runCatching { api.createTask(project.id, title) }
            runOnUiThread {
                result.onSuccess { taskTitle.setText(""); loadProject(project) }
                    .onFailure { status.text = "Task creation failed: ${it.message ?: "unknown error"}" }
            }
        }
    }

    private fun updateSelectedTask(nextStatus: String) {
        val project = projects.getOrNull(projectSpinner.selectedItemPosition) ?: return
        val task = tasks.getOrNull(taskSpinner.selectedItemPosition) ?: return
        status.text = "Updating ${task.title}…"
        thread(name = "dpn-mobile-task-update") {
            val result = runCatching { api.updateTaskStatus(task.id, nextStatus) }
            runOnUiThread {
                result.onSuccess { loadProject(project) }
                    .onFailure { status.text = "Task update failed: ${it.message ?: "unknown error"}" }
            }
        }
    }
}
