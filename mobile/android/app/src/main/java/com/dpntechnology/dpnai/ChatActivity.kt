package com.dpntechnology.dpnai

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class ChatActivity : Activity() {
    private lateinit var api: DesktopApiClient
    private lateinit var conversationSpinner: Spinner
    private lateinit var transcript: LinearLayout
    private lateinit var status: TextView
    private lateinit var input: EditText
    private lateinit var sendButton: Button
    private var conversations: List<DesktopApiClient.ConversationSummary> = emptyList()
    private var activeConversationId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = DesktopApiClient(SecureCredentialStore(this))
        setContentView(buildUi())
        refreshConversations()
    }

    private fun buildUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(28, 36, 28, 28)
            setBackgroundColor(Color.rgb(7, 7, 10))
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }

        root.addView(TextView(this).apply {
            text = "DPN AI • Unified Chat"
            textSize = 24f
            setTextColor(Color.WHITE)
        })
        root.addView(TextView(this).apply {
            text = "Shared conversations with the desktop AI runtime"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 4, 0, 20)
        })

        conversationSpinner = Spinner(this).apply {
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                    val selected = conversations.getOrNull(position) ?: return
                    if (selected.id != activeConversationId) loadConversation(selected.id)
                }

                override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            }
        }
        root.addView(conversationSpinner, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        val actionRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.END
        }
        actionRow.addView(Button(this).apply {
            text = "Refresh"
            setOnClickListener { refreshConversations() }
        })
        actionRow.addView(Button(this).apply {
            text = "New Chat"
            setOnClickListener { createConversation() }
        })
        root.addView(actionRow)

        status = TextView(this).apply {
            text = "Loading conversations…"
            setTextColor(Color.LTGRAY)
            setPadding(0, 12, 0, 12)
        }
        root.addView(status)

        transcript = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val scroll = ScrollView(this).apply {
            addView(transcript)
            isFillViewport = true
        }
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        input = EditText(this).apply {
            hint = "Message DPN AI…"
            setHintTextColor(Color.GRAY)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(18, 16, 27))
            minLines = 2
            maxLines = 6
            setPadding(20, 16, 20, 16)
        }
        root.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        sendButton = Button(this).apply {
            text = "Send to DPN AI"
            isEnabled = false
            setOnClickListener { sendMessage() }
        }
        root.addView(sendButton)
        return root
    }

    private fun refreshConversations(selectId: String? = activeConversationId) {
        setBusy(true, "Syncing conversations…")
        thread(name = "dpn-mobile-conversation-sync") {
            val result = runCatching { api.listConversations() }
            runOnUiThread {
                result.onSuccess { items ->
                    conversations = items
                    val labels = if (items.isEmpty()) listOf("No conversations yet") else items.map { it.title }
                    conversationSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, labels)
                    val index = selectId?.let { id -> items.indexOfFirst { it.id == id } }?.takeIf { it >= 0 } ?: 0
                    if (items.isNotEmpty()) {
                        activeConversationId = items[index].id
                        conversationSpinner.setSelection(index)
                        loadConversation(items[index].id)
                    } else {
                        activeConversationId = null
                        transcript.removeAllViews()
                        setBusy(false, "No conversations yet — create one to begin.")
                    }
                }.onFailure { error ->
                    setBusy(false, "Conversation sync failed: ${error.message ?: "unknown error"}")
                }
            }
        }
    }

    private fun createConversation() {
        setBusy(true, "Creating conversation…")
        thread(name = "dpn-mobile-new-chat") {
            val result = runCatching { api.createConversation("Mobile conversation") }
            runOnUiThread {
                result.onSuccess { id ->
                    activeConversationId = id
                    refreshConversations(id)
                }.onFailure { error ->
                    setBusy(false, "Could not create conversation: ${error.message ?: "unknown error"}")
                }
            }
        }
    }

    private fun loadConversation(conversationId: String) {
        activeConversationId = conversationId
        setBusy(true, "Loading shared history…")
        thread(name = "dpn-mobile-chat-history") {
            val result = runCatching { api.getConversation(conversationId) }
            runOnUiThread {
                result.onSuccess { messages ->
                    transcript.removeAllViews()
                    messages.forEach { addMessage(it.role, it.content) }
                    setBusy(false, "Synced ${messages.size} messages with desktop history.")
                }.onFailure { error ->
                    setBusy(false, "History sync failed: ${error.message ?: "unknown error"}")
                }
            }
        }
    }

    private fun sendMessage() {
        val message = input.text.toString().trim()
        if (message.isEmpty()) return
        val selected = conversations.getOrNull(conversationSpinner.selectedItemPosition)
        val conversationId = selected?.id ?: activeConversationId
        input.setText("")
        addMessage("user", message)
        setBusy(true, "DPN AI is working…")
        thread(name = "dpn-mobile-chat-send") {
            val result = runCatching {
                api.sendChat(
                    conversationId = conversationId,
                    message = message,
                    profile = "auto",
                    executionMode = "auto",
                    verify = false,
                )
            }
            runOnUiThread {
                result.onSuccess { reply ->
                    activeConversationId = reply.conversationId
                    addMessage("assistant", reply.message)
                    setBusy(false, "Synced • ${reply.model ?: "active model"}${reply.runId?.let { " • run $it" } ?: ""}")
                    if (conversationId == null) refreshConversations(reply.conversationId)
                }.onFailure { error ->
                    addMessage("system", "Send failed: ${error.message ?: "unknown error"}")
                    setBusy(false, "Message failed — nothing was hidden or marked complete.")
                }
            }
        }
    }

    private fun addMessage(role: String, content: String) {
        val normalizedRole = role.lowercase()
        val label = when (normalizedRole) {
            "user" -> "YOU"
            "assistant" -> "DPN AI"
            else -> role.uppercase()
        }
        transcript.addView(TextView(this).apply {
            text = "$label\n$content"
            textSize = 15f
            setTextColor(if (normalizedRole == "assistant") Color.WHITE else Color.LTGRAY)
            setBackgroundColor(if (normalizedRole == "assistant") Color.rgb(24, 18, 39) else Color.rgb(16, 16, 20))
            setPadding(18, 14, 18, 14)
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            setMargins(0, 0, 0, 12)
        })
    }

    private fun setBusy(busy: Boolean, message: String) {
        status.text = message
        sendButton.isEnabled = !busy && apiReady()
        conversationSpinner.isEnabled = !busy
    }

    private fun apiReady(): Boolean = runCatching {
        SecureCredentialStore(this).loadDesktopCredential() != null
    }.getOrDefault(false)
}
