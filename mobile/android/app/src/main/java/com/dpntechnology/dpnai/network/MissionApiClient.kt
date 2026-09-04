package com.dpntechnology.dpnai.network

import com.dpntechnology.dpnai.security.SecureCredentialStore
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * Mission-specific mobile facade over the existing DPN AI desktop runtime.
 *
 * This is not a second AI or mission engine. It only reads and launches missions
 * through the existing authenticated `/api/missions` endpoints.
 */
class MissionApiClient(private val credentialStore: SecureCredentialStore) {
    data class MissionSummary(
        val id: String,
        val objective: String,
        val status: String,
        val projectId: String?,
        val conversationId: String?,
        val createdAt: String?,
        val updatedAt: String?,
    )

    data class MissionDetail(
        val summary: MissionSummary,
        val raw: JSONObject,
    )

    fun listMissions(limit: Int = 100, status: String? = null): List<MissionSummary> {
        require(limit in 1..200) { "mission limit must be between 1 and 200" }
        status?.let { require(it in ALLOWED_STATUSES) { "unsupported mission status" } }
        val suffix = buildString {
            append("?limit=").append(limit)
            status?.let { append("&status=").append(encodeQueryValue(it)) }
        }
        val payload = JSONObject(request("GET", "/api/missions$suffix"))
        val items = payload.optJSONArray("missions") ?: JSONArray()
        return buildList {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                parseSummary(item)?.let(::add)
            }
        }
    }

    fun getMission(missionId: String): MissionDetail {
        val safeId = encodePathSegment(missionId)
        val payload = JSONObject(request("GET", "/api/missions/$safeId"))
        val mission = payload.optJSONObject("mission") ?: payload
        val summary = parseSummary(mission)
            ?: throw DesktopApiException("desktop API returned an invalid mission")
        return MissionDetail(summary, mission)
    }

    fun launchMission(
        objective: String,
        projectId: String? = null,
        conversationId: String? = null,
        profile: String = "auto",
        attachments: List<String> = emptyList(),
    ): MissionDetail {
        val cleanObjective = objective.trim()
        require(cleanObjective.isNotEmpty() && cleanObjective.length <= 100_000) { "invalid mission objective" }
        require(profile in ALLOWED_PROFILES) { "unsupported mission profile" }
        require(attachments.size <= MAX_ATTACHMENTS) { "too many mission attachments" }

        val safeAttachments = JSONArray()
        attachments.forEach { raw ->
            val clean = raw.trim()
            require(clean.isNotEmpty() && clean.length <= 1000) { "invalid mission attachment" }
            require(!clean.startsWith("/") && !clean.contains("..")) { "mission attachment must be workspace-relative" }
            safeAttachments.put(clean)
        }

        val body = JSONObject()
            .put("objective", cleanObjective)
            .put("profile", profile)
            .put("attachments", safeAttachments)
            .put("budget", JSONObject())
        projectId?.trim()?.takeIf { it.isNotEmpty() }?.let { body.put("project_id", boundedId(it)) }
        conversationId?.trim()?.takeIf { it.isNotEmpty() }?.let { body.put("conversation_id", boundedId(it)) }

        val payload = JSONObject(request("POST", "/api/missions", body.toString()))
        val missionObject = payload.optJSONObject("mission") ?: payload
        val summary = parseSummary(missionObject)
            ?: throw DesktopApiException("desktop API did not return mission identity")
        return MissionDetail(summary, missionObject)
    }

    private fun parseSummary(item: JSONObject): MissionSummary? {
        val id = item.optString("id").trim()
        if (id.isEmpty()) return null
        val objective = item.optString("objective", "Mission").trim().ifBlank { "Mission" }.take(MAX_OBJECTIVE_PREVIEW)
        return MissionSummary(
            id = id,
            objective = objective,
            status = item.optString("status", "unknown").trim().ifBlank { "unknown" },
            projectId = item.optString("project_id").trim().ifBlank { null },
            conversationId = item.optString("conversation_id").trim().ifBlank { null },
            createdAt = item.optString("created_at").trim().ifBlank { null },
            updatedAt = item.optString("updated_at").trim().ifBlank { null },
        )
    }

    private fun request(method: String, path: String, jsonBody: String? = null): String {
        val credential = credentialStore.loadDesktopCredential()
            ?: throw IllegalStateException("mobile device is not paired")
        val baseUri = URI(credential.baseUrl)
        require(baseUri.scheme.equals("https", true) && baseUri.host?.isNotBlank() == true) {
            "desktop endpoint must use HTTPS"
        }
        require(path.startsWith("/api/missions")) { "mission API path escaped the mission boundary" }

        val connection = (baseUri.resolve(path).toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 120_000
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
                connection.outputStream.use { it.write(jsonBody.toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader(Charsets.UTF_8)?.use {
                val text = it.readText()
                if (text.length > MAX_RESPONSE_CHARS) {
                    throw DesktopApiException("desktop mission response exceeded mobile safety limit")
                }
                text
            }.orEmpty()
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(response).optString("detail") }.getOrNull()
                    ?.take(400)?.ifBlank { null }
                throw DesktopApiException(detail ?: "desktop mission API rejected request with HTTP $code")
            }
            response
        } finally {
            connection.disconnect()
        }
    }

    private fun encodePathSegment(value: String): String = URLEncoder.encode(
        boundedId(value),
        StandardCharsets.UTF_8.toString(),
    ).replace("+", "%20")

    private fun encodeQueryValue(value: String): String = URLEncoder.encode(
        value,
        StandardCharsets.UTF_8.toString(),
    ).replace("+", "%20")

    private fun boundedId(value: String): String {
        val clean = value.trim()
        require(clean.isNotEmpty() && clean.length <= 128) { "invalid id" }
        return clean
    }

    companion object {
        private const val MAX_RESPONSE_CHARS = 2_000_000
        private const val MAX_OBJECTIVE_PREVIEW = 2000
        private const val MAX_ATTACHMENTS = 8
        private val ALLOWED_STATUSES = setOf("planned", "queued", "running", "completed", "failed", "cancelled", "paused")
        private val ALLOWED_PROFILES = setOf(
            "auto", "director", "software", "fivem", "research", "business", "documents",
            "security", "media", "automation", "computer", "data", "science", "creative",
        )
    }
}
