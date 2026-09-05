package com.dpntechnology.dpnai

import android.app.Activity
import android.content.Intent
import android.database.Cursor
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import kotlin.concurrent.thread

class FileActivity : Activity() {
    private lateinit var api: DesktopApiClient
    private lateinit var status: TextView
    private lateinit var selectedFile: TextView
    private lateinit var instruction: EditText
    private lateinit var analyzeButton: Button
    private var selectedUri: Uri? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = DesktopApiClient(SecureCredentialStore(this))
        setContentView(buildUi())
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(36, 48, 36, 36)
        setBackgroundColor(Color.rgb(7, 7, 10))
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        addView(TextView(this@FileActivity).apply {
            text = "DPN AI • Files"
            textSize = 26f
            setTextColor(Color.WHITE)
        })
        addView(TextView(this@FileActivity).apply {
            text = "Documents • Code • Logs • Data • Archives"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 4, 0, 28)
        })
        addView(Button(this@FileActivity).apply {
            text = "Choose File"
            setOnClickListener { chooseFile() }
        })
        selectedFile = TextView(this@FileActivity).apply {
            text = "No file selected"
            setTextColor(Color.LTGRAY)
            setPadding(0, 20, 0, 20)
        }
        addView(selectedFile)
        instruction = EditText(this@FileActivity).apply {
            hint = "What should DPN AI do with this file?"
            setHintTextColor(Color.GRAY)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(18, 16, 27))
            minLines = 3
            maxLines = 8
            setPadding(20, 16, 20, 16)
        }
        addView(instruction, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        analyzeButton = Button(this@FileActivity).apply {
            text = "Send File to DPN AI"
            isEnabled = false
            setOnClickListener { uploadAndAnalyze() }
        }
        addView(analyzeButton)
        status = TextView(this@FileActivity).apply {
            text = "Choose a file explicitly to begin."
            setTextColor(Color.LTGRAY)
            setPadding(0, 24, 0, 0)
        }
        addView(status)
    }

    private fun chooseFile() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
        }
        startActivityForResult(intent, REQUEST_FILE)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_FILE || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        val name = displayName(uri)
        val size = contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        if (size > MAX_FILE_BYTES) {
            selectedUri = null
            selectedFile.text = "Rejected: $name"
            status.text = "File exceeds the 50 MB mobile upload limit."
            analyzeButton.isEnabled = false
            return
        }
        selectedUri = uri
        selectedFile.text = if (size >= 0) "$name • ${size / 1024} KB" else name
        status.text = "File selected. Add an instruction or use the default analysis request."
        analyzeButton.isEnabled = true
    }

    private fun uploadAndAnalyze() {
        val uri = selectedUri ?: return
        analyzeButton.isEnabled = false
        status.text = "Reading and securely uploading file…"
        val prompt = instruction.text.toString().trim().ifBlank {
            "Analyze this file thoroughly. Explain what it contains, identify important findings or problems, and recommend the next useful actions."
        }
        thread(name = "dpn-mobile-file-upload") {
            val result = runCatching {
                val name = displayName(uri)
                val mime = contentResolver.getType(uri)?.lowercase() ?: "application/octet-stream"
                val bytes = readBounded(uri)
                val upload = api.uploadFile(bytes, name, mime)
                api.sendChat(
                    conversationId = null,
                    message = prompt,
                    profile = "auto",
                    executionMode = "auto",
                    verify = false,
                    attachments = listOf(upload.workspacePath),
                )
            }
            runOnUiThread {
                analyzeButton.isEnabled = true
                result.onSuccess { reply ->
                    status.text = "DPN AI\n${reply.message}\n\nConversation ${reply.conversationId}"
                }.onFailure { error ->
                    status.text = "File analysis failed: ${error.message ?: "unknown error"}"
                }
            }
        }
    }

    private fun readBounded(uri: Uri): ByteArray {
        contentResolver.openInputStream(uri)?.use { input ->
            val out = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            var total = 0
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                total += read
                require(total <= MAX_FILE_BYTES) { "file exceeds the 50 MB mobile upload limit" }
                out.write(buffer, 0, read)
            }
            return out.toByteArray()
        }
        throw IllegalArgumentException("selected file could not be opened")
    }

    private fun displayName(uri: Uri): String {
        var name = "mobile-file.bin"
        val cursor: Cursor? = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
        cursor?.use {
            if (it.moveToFirst()) name = it.getString(0)?.take(160)?.ifBlank { name } ?: name
        }
        return name
    }

    companion object {
        private const val REQUEST_FILE = 4301
        private const val MAX_FILE_BYTES = 50 * 1024 * 1024
    }
}
