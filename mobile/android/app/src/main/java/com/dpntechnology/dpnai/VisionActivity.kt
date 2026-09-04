package com.dpntechnology.dpnai

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

class VisionActivity : Activity() {
    private lateinit var api: DesktopApiClient
    private lateinit var status: TextView
    private lateinit var preview: ImageView
    private lateinit var prompt: EditText
    private lateinit var analyzeButton: Button
    private lateinit var result: TextView
    private var selectedImage: Uri? = null
    private var pendingCameraImage: Uri? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = DesktopApiClient(SecureCredentialStore(this))
        setContentView(buildUi())
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(28, 36, 28, 28)
        setBackgroundColor(Color.rgb(7, 7, 10))
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        addView(TextView(this@VisionActivity).apply {
            text = "DPN AI • Vision"
            textSize = 25f
            setTextColor(Color.WHITE)
        })
        addView(TextView(this@VisionActivity).apply {
            text = "Camera + gallery routed to the unified multimodal AI"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 4, 0, 20)
        })

        val actions = LinearLayout(this@VisionActivity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        actions.addView(Button(this@VisionActivity).apply {
            text = "Take Photo"
            setOnClickListener { capturePhoto() }
        })
        actions.addView(Button(this@VisionActivity).apply {
            text = "Choose Image"
            setOnClickListener { chooseImage() }
        })
        addView(actions)

        status = TextView(this@VisionActivity).apply {
            text = "Choose or capture an image to begin."
            setTextColor(Color.LTGRAY)
            setPadding(0, 12, 0, 12)
        }
        addView(status)

        preview = ImageView(this@VisionActivity).apply {
            scaleType = ImageView.ScaleType.CENTER_INSIDE
            setBackgroundColor(Color.rgb(16, 16, 20))
            contentDescription = "Selected image preview"
        }
        addView(preview, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        prompt = EditText(this@VisionActivity).apply {
            hint = "What should DPN AI inspect?"
            setHintTextColor(Color.GRAY)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(18, 16, 27))
            setText("Analyze this image in detail. Identify important objects, text, problems, risks, and useful next actions.")
            minLines = 2
            maxLines = 5
            setPadding(18, 14, 18, 14)
        }
        addView(prompt)

        analyzeButton = Button(this@VisionActivity).apply {
            text = "Analyze with DPN AI"
            isEnabled = false
            setOnClickListener { analyzeSelectedImage() }
        }
        addView(analyzeButton)

        result = TextView(this@VisionActivity).apply {
            text = ""
            textSize = 15f
            setTextColor(Color.WHITE)
            setPadding(0, 14, 0, 0)
        }
        addView(result)
    }

    private fun capturePhoto() {
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, "dpn-ai-${System.currentTimeMillis()}.jpg")
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
        }
        val uri = contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
        if (uri == null) {
            status.text = "Could not create a secure camera destination."
            return
        }
        pendingCameraImage = uri
        val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
            putExtra(MediaStore.EXTRA_OUTPUT, uri)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        if (intent.resolveActivity(packageManager) == null) {
            contentResolver.delete(uri, null, null)
            pendingCameraImage = null
            status.text = "No camera application is available."
            return
        }
        startActivityForResult(intent, REQUEST_CAMERA)
    }

    private fun chooseImage() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "image/*"
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }
        startActivityForResult(intent, REQUEST_GALLERY)
    }

    @Deprecated("Activity result compatibility for API 26+")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            REQUEST_CAMERA -> {
                val uri = pendingCameraImage
                pendingCameraImage = null
                if (resultCode == RESULT_OK && uri != null) {
                    selectImage(uri)
                } else if (uri != null) {
                    contentResolver.delete(uri, null, null)
                    status.text = "Camera capture cancelled."
                }
            }
            REQUEST_GALLERY -> {
                val uri = data?.data
                if (resultCode == RESULT_OK && uri != null) {
                    runCatching {
                        contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    selectImage(uri)
                }
            }
        }
    }

    private fun selectImage(uri: Uri) {
        val mime = contentResolver.getType(uri).orEmpty().lowercase()
        if (mime !in ALLOWED_IMAGE_TYPES) {
            status.text = "Unsupported image type. Use JPEG, PNG, or WebP."
            analyzeButton.isEnabled = false
            return
        }
        selectedImage = uri
        preview.setImageURI(uri)
        analyzeButton.isEnabled = true
        status.text = "Image ready • ${displayName(uri)} • ${mime.removePrefix("image/").uppercase()}"
        result.text = ""
    }

    private fun analyzeSelectedImage() {
        val uri = selectedImage ?: return
        val requestText = prompt.text.toString().trim()
        if (requestText.isEmpty()) {
            status.text = "Enter an instruction for DPN AI."
            return
        }
        analyzeButton.isEnabled = false
        status.text = "Uploading image through the encrypted DPN AI connection…"
        result.text = ""
        thread(name = "dpn-mobile-vision") {
            val outcome = runCatching {
                val mime = contentResolver.getType(uri).orEmpty().lowercase()
                require(mime in ALLOWED_IMAGE_TYPES) { "unsupported image type" }
                val bytes = readBounded(uri)
                val upload = api.uploadImage(bytes, displayName(uri), mime)
                api.sendChat(
                    conversationId = null,
                    message = requestText,
                    profile = "auto",
                    executionMode = "auto",
                    verify = false,
                    attachments = listOf(upload.workspacePath),
                )
            }
            runOnUiThread {
                analyzeButton.isEnabled = selectedImage != null
                outcome.onSuccess { reply ->
                    status.text = "Vision analysis synchronized • conversation ${reply.conversationId}"
                    result.text = "DPN AI\n${reply.message}"
                }.onFailure { error ->
                    status.text = "Vision request failed — nothing was marked complete."
                    result.text = "SYSTEM\n${error.message ?: "Unknown vision error"}"
                }
            }
        }
    }

    private fun readBounded(uri: Uri): ByteArray {
        val input = contentResolver.openInputStream(uri)
            ?: throw IllegalStateException("image could not be opened")
        input.use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0
            while (true) {
                val read = stream.read(buffer)
                if (read < 0) break
                total += read
                if (total > MAX_IMAGE_BYTES) throw IllegalArgumentException("image exceeds the 20 MB mobile limit")
                output.write(buffer, 0, read)
            }
            if (total == 0) throw IllegalArgumentException("image is empty")
            return output.toByteArray()
        }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index >= 0) return cursor.getString(index)?.take(120) ?: "mobile-vision.jpg"
            }
        }
        return "mobile-vision.jpg"
    }

    override fun onDestroy() {
        pendingCameraImage?.let { runCatching { contentResolver.delete(it, null, null) } }
        pendingCameraImage = null
        super.onDestroy()
    }

    companion object {
        private const val REQUEST_CAMERA = 4201
        private const val REQUEST_GALLERY = 4202
        private const val MAX_IMAGE_BYTES = 20 * 1024 * 1024
        private val ALLOWED_IMAGE_TYPES = setOf("image/jpeg", "image/png", "image/webp")
    }
}
