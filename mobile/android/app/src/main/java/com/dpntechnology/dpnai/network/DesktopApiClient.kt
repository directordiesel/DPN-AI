package com.dpntechnology.dpnai.network

import com.dpntechnology.dpnai.security.SecureCredentialStore
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

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

    fun sendChat(
        conversationId: String?,
        message: String,
        profile: String = "auto",
        projectId: String? = null,
        executionMode: String = "auto",
        verify: Boolean = false,
    ): ChatResult {
        val cleanMessage = message.trim()
        require(cleanMessage.isNotEmpty()) { "message is required" }
        require(cleanMessage.length <= 100_000) { "message is too long" }
        require(profile in ALLOWED_PROFILES) { "unsupported agent profile" }
        require(executionMode in ALLOWED_EXECUTION_MODES) { "unsupported execution mode" }

        val body = JSONObject()
            .put("message", cleanMessage)
            .put("profile", profile)
            .put("execution_mode", executionMode)
            .put("verify", verify)
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
        val credential = credentialStore.loadDesktopCredential()
            ?: throw IllegalStateException("mobile device is not paired")
        val baseUri = URI(credential.baseUrl)
        require(baseUri.scheme.equals("https", ignoreCase = true)) { "desktop endpoint must use HTTPS" }
        require(baseUri.host?.isNotBlank() == true) { "desktop endpoint host is required" }
        require(path.startsWith("/api/")) { "mobile API path must remain inside /api" }

        val endpoint = baseUri.resolve(path).toURL()
        val connection = (endpoint.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 60_000
            instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-DPN-Token", credential.token)
            setRequestProperty("X-DPN-Device-ID", credential.deviceId)
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
            response
        } finally {
            connection.disconnect()
        }
    }

    private fun encodePathSegment(value: String): String {
        val clean = value.trim()
        require(clean.isNotEmpty() && clean.length <= 128) { "invalid conversation id" }
        return URLEncoder.encode(clean, StandardCharsets.UTF_8.toString()).replace("+", "%20")
    }

    companion object {
        private const val MAX_RESPONSE_CHARS = 2_000_000
        private val ALLOWED_EXECUTION_MODES = setOf("auto", "direct", "mission")
        private val ALLOWED_PROFILES = setOf(
            "auto", "director", "software", "fivem", "research", "business", "documents",
            "security", "media", "automation", "computer", "data", "science", "creative",
        )
    }
}

class DesktopApiException(message: String) : IllegalStateException(message)
