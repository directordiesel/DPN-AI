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
    data class ConversationSummary(val id: String, val title: String, val updatedAt: String?)
    data class ChatMessage(val id: Long?, val role: String, val content: String, val createdAt: String?)
    data class ChatResult(val conversationId: String, val message: String, val model: String?, val profile: String?, val runId: String?)
    data class UploadResult(val workspacePath: String, val filename: String)
    data class ProjectSummary(val id: String, val name: String, val description: String, val status: String)
    data class TaskSummary(val id: String, val title: String, val details: String, val status: String, val priority: String)

    fun fetchDesktopSummary(): String = request("GET", "/api/v1/desktop/summary")

    fun listProjects(): List<ProjectSummary> {
        val items = JSONObject(request("GET", "/api/projects")).optJSONArray("projects") ?: JSONArray()
        return buildList {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                val id = item.optString("id").trim()
                if (id.isEmpty()) continue
                add(ProjectSummary(id, item.optString("name", "Untitled project"), item.optString("description"), item.optString("status", "active")))
            }
        }
    }

    fun getProjectTasks(projectId: String): List<TaskSummary> {
        val safeId = encodePathSegment(projectId)
        val items = JSONObject(request("GET", "/api/projects/$safeId/tasks")).optJSONArray("tasks") ?: JSONArray()
        return buildList {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                val id = item.optString("id").trim()
                if (id.isEmpty()) continue
                add(TaskSummary(id, item.optString("title", "Untitled task"), item.optString("details"), item.optString("status", "backlog"), item.optString("priority", "normal")))
            }
        }
    }

    fun createProject(name: String, description: String = "", rootPath: String = "."): ProjectSummary {
        val cleanName = name.trim().take(120)
        require(cleanName.isNotEmpty()) { "project name is required" }
        require(rootPath == ".") { "mobile project creation is restricted to the DPN AI workspace root" }
        val body = JSONObject().put("name", cleanName).put("description", description.trim().take(10_000)).put("root_path", rootPath)
        return parseProject(JSONObject(request("POST", "/api/projects", body.toString())).getJSONObject("project"))
    }

    fun createTask(projectId: String, title: String, details: String = "", priority: String = "normal"): TaskSummary {
        val cleanTitle = title.trim().take(240)
        require(cleanTitle.isNotEmpty()) { "task title is required" }
        require(priority in ALLOWED_PRIORITIES) { "unsupported task priority" }
        val body = JSONObject().put("title", cleanTitle).put("details", details.trim().take(30_000)).put("priority", priority).put("dependencies", JSONArray())
        val safeProject = encodePathSegment(projectId)
        return parseTask(JSONObject(request("POST", "/api/projects/$safeProject/tasks", body.toString())).getJSONObject("task"))
    }

    fun updateTaskStatus(taskId: String, status: String): TaskSummary {
        require(status in ALLOWED_TASK_STATUSES) { "unsupported task status" }
        val safeTask = encodePathSegment(taskId)
        val body = JSONObject().put("status", status)
        return parseTask(JSONObject(request("PATCH", "/api/tasks/$safeTask", body.toString())).getJSONObject("task"))
    }

    fun listConversations(): List<ConversationSummary> {
        val payload = JSONObject(request("GET", "/api/conversations"))
        val items = payload.optJSONArray("conversations") ?: JSONArray()
        return buildList {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                val id = item.optString("id").trim()
                if (id.isEmpty()) continue
                add(ConversationSummary(id, item.optString("title", "New conversation").ifBlank { "New conversation" }, item.optString("updated_at").ifBlank { null }))
            }
        }
    }

    fun createConversation(title: String = "Mobile conversation"): String {
        val cleanTitle = title.trim().take(120).ifBlank { "Mobile conversation" }
        val response = JSONObject(request("POST", "/api/conversations", JSONObject().put("title", cleanTitle).toString()))
        return response.optString("id").takeIf { it.isNotBlank() } ?: throw DesktopApiException("desktop API did not return a conversation id")
    }

    fun getConversation(conversationId: String): List<ChatMessage> {
        val response = JSONObject(request("GET", "/api/conversations/${encodePathSegment(conversationId)}"))
        val messages = response.optJSONArray("messages") ?: JSONArray()
        return buildList {
            for (index in 0 until messages.length()) {
                val item = messages.optJSONObject(index) ?: continue
                val content = item.optString("content")
                if (content.isBlank()) continue
                add(ChatMessage(if (item.has("id")) item.optLong("id") else null, item.optString("role", "assistant"), content, item.optString("created_at").ifBlank { null }))
            }
        }
    }

    fun uploadImage(bytes: ByteArray, filename: String, mimeType: String): UploadResult {
        require(bytes.isNotEmpty()) { "image is empty" }
        require(bytes.size <= MAX_IMAGE_BYTES) { "image exceeds the 20 MB mobile limit" }
        require(mimeType in ALLOWED_IMAGE_TYPES) { "unsupported image type" }
        return uploadMultipart(bytes, sanitizeImageFilename(filename, mimeType), mimeType, "image")
    }

    fun uploadFile(bytes: ByteArray, filename: String, mimeType: String): UploadResult {
        require(bytes.isNotEmpty()) { "file is empty" }
        require(bytes.size <= MAX_FILE_BYTES) { "file exceeds the 50 MB mobile limit" }
        val cleanMime = mimeType.trim().lowercase().take(120).ifBlank { "application/octet-stream" }
        require(cleanMime !in BLOCKED_FILE_TYPES) { "unsupported executable/mobile package type" }
        return uploadMultipart(bytes, sanitizeGeneralFilename(filename), cleanMime, "file")
    }

    private fun uploadMultipart(bytes: ByteArray, safeFilename: String, mimeType: String, kind: String): UploadResult {
        val boundary = "DPNMobile-${UUID.randomUUID()}"
        val header = ("--$boundary\r\nContent-Disposition: form-data; name=\"files\"; filename=\"$safeFilename\"\r\nContent-Type: $mimeType\r\n\r\n").toByteArray(Charsets.UTF_8)
        val footer = "\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8)
        val connection = openConnection("POST", "/api/files/upload").apply {
            doOutput = true
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            setFixedLengthStreamingMode(header.size.toLong() + bytes.size.toLong() + footer.size.toLong())
        }
        val response = try {
            connection.outputStream.use { it.write(header); it.write(bytes); it.write(footer) }
            readResponse(connection)
        } finally { connection.disconnect() }
        val payload = JSONObject(response)
        val failed = payload.optJSONArray("failed") ?: JSONArray()
        if (failed.length() > 0) throw DesktopApiException(failed.optJSONObject(0)?.optString("error")?.take(400)?.ifBlank { null } ?: "desktop rejected $kind upload")
        val workspacePath = (payload.optJSONArray("uploaded") ?: JSONArray()).optString(0).trim()
        if (workspacePath.isEmpty()) throw DesktopApiException("desktop API did not return an uploaded $kind path")
        require(!workspacePath.startsWith("/") && !workspacePath.contains("..")) { "desktop returned an unsafe attachment path" }
        return UploadResult(workspacePath, safeFilename)
    }

    fun sendChat(conversationId: String?, message: String, profile: String = "auto", projectId: String? = null, executionMode: String = "auto", verify: Boolean = false, attachments: List<String> = emptyList()): ChatResult {
        val cleanMessage = message.trim()
        require(cleanMessage.isNotEmpty() && cleanMessage.length <= 100_000) { "invalid message" }
        require(profile in ALLOWED_PROFILES) { "unsupported agent profile" }
        require(executionMode in ALLOWED_EXECUTION_MODES) { "unsupported execution mode" }
        require(attachments.size <= MAX_ATTACHMENTS) { "too many attachments" }
        val safeAttachments = attachments.map {
            val clean = it.trim()
            require(clean.isNotEmpty() && clean.length <= 1000 && !clean.startsWith("/") && !clean.contains("..")) { "attachment must be a workspace-relative path" }
            clean
        }
        val body = JSONObject().put("message", cleanMessage).put("profile", profile).put("execution_mode", executionMode).put("verify", verify).put("attachments", JSONArray(safeAttachments))
        conversationId?.takeIf { it.isNotBlank() }?.let { body.put("conversation_id", it) }
        projectId?.takeIf { it.isNotBlank() }?.let { body.put("project_id", it) }
        val response = JSONObject(request("POST", "/api/chat", body.toString()))
        return ChatResult(
            response.optString("conversation_id").takeIf { it.isNotBlank() } ?: throw DesktopApiException("desktop API did not return a conversation id"),
            response.optString("message").takeIf { it.isNotBlank() } ?: throw DesktopApiException("desktop API returned an empty assistant response"),
            response.optString("model").ifBlank { null }, response.optString("profile").ifBlank { null }, response.optString("run_id").ifBlank { null }
        )
    }

    private fun request(method: String, path: String, jsonBody: String? = null): String {
        val connection = openConnection(method, path).apply { if (jsonBody != null) { doOutput = true; setRequestProperty("Content-Type", "application/json; charset=utf-8") } }
        return try {
            if (jsonBody != null) connection.outputStream.use { it.write(jsonBody.toByteArray(Charsets.UTF_8)) }
            readResponse(connection)
        } finally { connection.disconnect() }
    }

    private fun openConnection(method: String, path: String): HttpURLConnection {
        val credential = credentialStore.loadDesktopCredential() ?: throw IllegalStateException("mobile device is not paired")
        val baseUri = URI(credential.baseUrl)
        require(baseUri.scheme.equals("https", true) && baseUri.host?.isNotBlank() == true) { "desktop endpoint must use HTTPS" }
        require(path.startsWith("/api/")) { "mobile API path must remain inside /api" }
        return (baseUri.resolve(path).toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = method; connectTimeout = 8_000; readTimeout = 60_000; instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json"); setRequestProperty("X-DPN-Token", credential.token); setRequestProperty("X-DPN-Device-ID", credential.deviceId)
        }
    }

    private fun readResponse(connection: HttpURLConnection): String {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader(Charsets.UTF_8)?.use { val text = it.readText(); if (text.length > MAX_RESPONSE_CHARS) throw DesktopApiException("desktop API response exceeded mobile safety limit"); text }.orEmpty()
        if (code !in 200..299) throw DesktopApiException(runCatching { JSONObject(response).optString("detail") }.getOrNull()?.take(400)?.ifBlank { null } ?: "desktop API rejected request with HTTP $code")
        return response
    }

    private fun parseProject(item: JSONObject) = ProjectSummary(item.optString("id"), item.optString("name", "Untitled project"), item.optString("description"), item.optString("status", "active"))
    private fun parseTask(item: JSONObject) = TaskSummary(item.optString("id"), item.optString("title", "Untitled task"), item.optString("details"), item.optString("status", "backlog"), item.optString("priority", "normal"))
    private fun encodePathSegment(value: String): String { val clean = value.trim(); require(clean.isNotEmpty() && clean.length <= 128) { "invalid id" }; return URLEncoder.encode(clean, StandardCharsets.UTF_8.toString()).replace("+", "%20") }
    private fun sanitizeImageFilename(filename: String, mimeType: String): String { val ext = when (mimeType) { "image/png" -> ".png"; "image/webp" -> ".webp"; else -> ".jpg" }; val clean = sanitizeGeneralFilename(filename); return if (clean == "mobile-file.bin") "mobile-vision$ext" else clean }
    private fun sanitizeGeneralFilename(filename: String): String = filename.substringAfterLast('/').substringAfterLast('\\').replace(Regex("[^A-Za-z0-9._ -]"), "_").replace(Regex("\\s+"), "_").take(160).trim('.', '_', ' ').ifBlank { "mobile-file.bin" }

    companion object {
        private const val MAX_RESPONSE_CHARS = 2_000_000
        private const val MAX_IMAGE_BYTES = 20 * 1024 * 1024
        private const val MAX_FILE_BYTES = 50 * 1024 * 1024
        private const val MAX_ATTACHMENTS = 8
        private val ALLOWED_IMAGE_TYPES = setOf("image/jpeg", "image/png", "image/webp")
        private val BLOCKED_FILE_TYPES = setOf("application/vnd.android.package-archive", "application/x-msdownload", "application/x-dosexec")
        private val ALLOWED_EXECUTION_MODES = setOf("auto", "direct", "mission")
        private val ALLOWED_PROFILES = setOf("auto", "director", "software", "fivem", "research", "business", "documents", "security", "media", "automation", "computer", "data", "science", "creative")
        private val ALLOWED_PRIORITIES = setOf("low", "normal", "high", "critical")
        private val ALLOWED_TASK_STATUSES = setOf("backlog", "ready", "running", "blocked", "done", "failed")
    }
}

class DesktopApiException(message: String) : IllegalStateException(message)
