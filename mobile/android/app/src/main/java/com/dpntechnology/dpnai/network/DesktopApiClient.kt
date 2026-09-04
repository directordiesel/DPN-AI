package com.dpntechnology.dpnai.network

import com.dpntechnology.dpnai.security.SecureCredentialStore
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.UUID

class DesktopApiClient(private val credentialStore: SecureCredentialStore) {
    data class ConversationSummary(
        val id: String,
        val title: String,
        val updatedAt: String?,
    )

    data class ChatMessage(
        val id: Long?,
        val role: String,
        val content: String,
        val createdAt: String?,
    )

    data class ChatResult(
        val conversationId: String,
        val message: String,
        val model: String?,
        val profile: String?,
        val runId: String?,
    )

    data class UploadResult(
        val workspacePath: String,
        val filename: String,
    )

    fun fetchDesktopSummary(): String = request("GET", "/api/v1/desktop/summary")

    fun listConversations(): List<ConversationSummary> {
        val payload = JSONObject(request("GET", "/api/conversations"))
        val items = payload.optJSONArray("conversations") ?: JSONArray()
        return buildList {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                val id = item.optString("id").trim()
                if (id.isEmpty()) continue
                add(
                    ConversationSummary(
                        id = id,
                        title = item.optString("title", "New conversation").ifBlank { "New conversation" },
                        updatedAt = item.optString("updated_at").ifBlank { null },
                    )
                )
            }
        }
    }

    fun createConversation(title: String = "Mobile conversation"): String {
        val cleanTitle = title.trim().take(120).ifBlank { "Mobile conversation" }
        val payload = JSONObject().put("title", cleanTitle)
        val response = JSONObject(request("POST", "/api/conversations", payload.toString()))
        return response.optString("id").takeIf { it.isNotBlank() }
            ?: throw DesktopApiException("desktop API did not return a conversation id")
    }

    fun getConversation(conversationId: String): List<ChatMessage> {
        val safeId = encodePathSegment(conversationId)
        val response = JSONObject(request("GET", "/api/conversations/$safeId"))
        val messages = response.optJSONArray("messages") ?: JSONArray()
        return buildList {
            for (index in 0 until messages.length()) {
                val item = messages.optJSONObject(index) ?: continue
                val content = item.optString("content")
                if (content.isBlank()) continue
                add(
                    ChatMessage(
                        id = if (item.has("id")) item.optLong("id") else null,
                        role = item.optString("role", "assistant"),
                        content = content,
                        createdAt = item.optString("created_at").ifBlank { null },
                    )
                )
            }
        }
    }

    fun uploadImage(bytes: ByteArray, filename: String, mimeType: String): UploadResult {
        require(bytes.isNotEmpty()) { "image is empty" }
        require(bytes.size <= MAX_IMAGE_BYTES) { "image exceeds the 20 MB mobile limit" }
        require(mimeType in ALLOWED_IMAGE_TYPES) { "unsupported image type" }
        val safeFilename = sanitizeFilename(filename, mimeType)
        val boundary = "DPNMobile-${UUID.randomUUID()}"
        val header = (
            "--$boundary\r\n" +
                "Content-Disposition: form-data; name=\"files\"; filename=\"$safeFilename\"\r\n" +
                "Content-Type: $mimeType\r\n\r\n"
            ).toByteArray(Charsets.UTF_8)
        val footer = "\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8)

        val connection = openConnection("POST", "/api/files/upload").apply {
            doOutput = true
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            setFixedLengthStreamingMode(header.size.toLong() + bytes.size.toLong() + footer.size.toLong())
        }
        val response = try {
            connection.outputStream.use { output ->
                output.write(header)
                output.write(bytes)
                output.write(footer)
            }
            readResponse(connection)
        } finally {
            connection.disconnect()
        }

        val payload = JSONObject(response)
        val failed = payload.optJSONArray("failed") ?: JSONArray()
        if (failed.length() > 0) {
            val error = failed.optJSONObject(0)?.optString("error")?.take(400)
            throw DesktopApiException(error?.ifBlank { null } ?: "desktop rejected image upload")
        }
        val uploaded = payload.optJSONArray("uploaded") ?: JSONArray()
        val workspacePath = uploaded.optString(0).trim()
        if (workspacePath.isEmpty()) throw DesktopApiException("desktop API did not return an uploaded image path")
        return UploadResult(workspacePath = workspacePath, filename = safeFilename)
    }

    fun sendChat(
        conversationId: String?,
        message: String,
        profile: String = "auto",
        projectId: String? = null,
        executionMode: String = "auto",
        verify: Boolean = false,
        attachments: List<String> = emptyList(),
    ): ChatResult {
        val cleanMessage = message.trim()
        require(cleanMessage.isNotEmpty()) { "message is required" }
        require(cleanMessage.length <= 100_000) { "message is too long" }
        require(profile in ALLOWED_PROFILES) { "unsupported agent profile" }
        require(executionMode in ALLOWED_EXECUTION_MODES) { "unsupported execution mode" }
        require(attachments.size <= MAX_ATTACHMENTS) { "too many attachments" }

        val safeAttachments = attachments.map { path ->
            val clean = path.trim()
            require(clean.isNotEmpty() && clean.length <= 1000) { "invalid attachment path" }
            require(!clean.startsWith("/") && !clean.contains("..")) { "attachment must be a workspace-relative path" }
            clean
        }

        val body = JSONObject()
            .put("message", cleanMessage)
            .put("profile", profile)
            .put("execution_mode", executionMode)
            .put("verify", verify)
            .put("attachments", JSONArray(safeAttachments))
        conversationId?.takeIf { it.isNotBlank() }?.let { body.put("conversation_id", it) }
        projectId?.takeIf { it.isNotBlank() }?.let { body.put("project_id", it) }

        val response = JSONObject(request("POST", "/api/chat", body.toString()))
        return ChatResult(
            conversationId = response.optString("conversation_id").takeIf { it.isNotBlank() }
                ?: throw DesktopApiException("desktop API did not return a conversation id"),
            message = response.optString("message").takeIf { it.isNotBlank() }
                ?: throw DesktopApiException("desktop API returned an empty assistant response"),
            model = response.optString("model").ifBlank { null },
            profile = response.optString("profile").ifBlank { null },
            runId = response.optString("run_id").ifBlank { null },
        )
    }

    private fun request(method: String, path: String, jsonBody: String? = null): String {
        val connection = openConnection(method, path).apply {
            if (jsonBody != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        return try {
            if (jsonBody != null) {
                connection.outputStream.use { output ->
                    output.write(jsonBody.toByteArray(Charsets.UTF_8))
                }
            }
            readResponse(connection)
        } finally {
            connection.disconnect()
        }
    }

    private fun openConnection(method: String, path: String): HttpURLConnection {
        val credential = credentialStore.loadDesktopCredential()
            ?: throw IllegalStateException("mobile device is not paired")
        val baseUri = URI(credential.baseUrl)
        require(baseUri.scheme.equals("https", ignoreCase = true)) { "desktop endpoint must use HTTPS" }
        require(baseUri.host?.isNotBlank() == true) { "desktop endpoint host is required" }
        require(path.startsWith("/api/")) { "mobile API path must remain inside /api" }

        return (baseUri.resolve(path).toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 60_000
            instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-DPN-Token", credential.token)
            setRequestProperty("X-DPN-Device-ID", credential.deviceId)
        }
    }

    private fun readResponse(connection: HttpURLConnection): String {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader(Charsets.UTF_8)?.use { reader ->
            val text = reader.readText()
            if (text.length > MAX_RESPONSE_CHARS) {
                throw DesktopApiException("desktop API response exceeded mobile safety limit")
            }
            text
        }.orEmpty()
        if (code !in 200..299) {
            val detail = runCatching { JSONObject(response).optString("detail") }.getOrNull()
            throw DesktopApiException(detail?.take(400)?.ifBlank { null } ?: "desktop API rejected request with HTTP $code")
        }
        return response
    }

    private fun encodePathSegment(value: String): String {
        val clean = value.trim()
        require(clean.isNotEmpty() && clean.length <= 128) { "invalid conversation id" }
        return URLEncoder.encode(clean, StandardCharsets.UTF_8.toString()).replace("+", "%20")
    }

    private fun sanitizeFilename(filename: String, mimeType: String): String {
        val fallbackExtension = when (mimeType) {
            "image/png" -> ".png"
            "image/webp" -> ".webp"
            else -> ".jpg"
        }
        val clean = filename.substringAfterLast('/').substringAfterLast('\\')
            .replace(Regex("[^A-Za-z0-9._-]"), "_")
            .take(120)
            .trim('.', '_')
        return if (clean.isBlank()) "mobile-vision$fallbackExtension" else clean
    }

    companion object {
        private const val MAX_RESPONSE_CHARS = 2_000_000
        private const val MAX_IMAGE_BYTES = 20 * 1024 * 1024
        private const val MAX_ATTACHMENTS = 8
        private val ALLOWED_IMAGE_TYPES = setOf("image/jpeg", "image/png", "image/webp")
        private val ALLOWED_EXECUTION_MODES = setOf("auto", "direct", "mission")
        private val ALLOWED_PROFILES = setOf(
            "auto", "director", "software", "fivem", "research", "business", "documents",
            "security", "media", "automation", "computer", "data", "science", "creative",
        )
    }
}

class DesktopApiException(message: String) : IllegalStateException(message)
