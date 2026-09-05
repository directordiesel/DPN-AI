package com.dpntechnology.dpnai.network

import com.dpntechnology.dpnai.security.SecureCredentialStore
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/** Thin authenticated mobile facade over the existing DPN AI approval boundary. */
class ApprovalApiClient(private val credentialStore: SecureCredentialStore) {
    data class ApprovalSummary(
        val id: String,
        val status: String,
        val action: String,
        val reason: String,
        val createdAt: String?,
        val raw: JSONObject,
    )

    fun listApprovals(status: String? = "pending", limit: Int = 100): List<ApprovalSummary> {
        require(limit in 1..200) { "approval limit must be between 1 and 200" }
        status?.let { require(it in ALLOWED_STATUSES) { "unsupported approval status" } }
        val query = buildString {
            append("?limit=").append(limit)
            status?.let { append("&status=").append(encodeQueryValue(it)) }
        }
        val payload = JSONObject(request("GET", "/api/approvals$query"))
        val approvals = payload.optJSONArray("approvals") ?: JSONArray()
        return buildList {
            for (index in 0 until approvals.length()) {
                approvals.optJSONObject(index)?.let { parseSummary(it)?.let(::add) }
            }
        }
    }

    fun decide(approvalId: String, decision: String): ApprovalSummary {
        require(decision in ALLOWED_DECISIONS) { "decision must be approved or denied" }
        val safeId = encodePathSegment(approvalId)
        val payload = JSONObject(
            request(
                "POST",
                "/api/approvals/$safeId/decision",
                JSONObject().put("decision", decision).toString(),
            )
        )
        val approval = payload.optJSONObject("approval") ?: payload
        return parseSummary(approval)
            ?: ApprovalSummary(boundedId(approvalId), decision, "Approval decision", "", null, approval)
    }

    private fun parseSummary(item: JSONObject): ApprovalSummary? {
        val id = item.optString("id").trim()
        if (id.isEmpty()) return null
        val action = listOf("action", "tool", "tool_name", "name", "kind")
            .asSequence().map { item.optString(it).trim() }.firstOrNull { it.isNotEmpty() }
            ?: "Protected action"
        val reason = listOf("reason", "summary", "description", "prompt")
            .asSequence().map { item.optString(it).trim() }.firstOrNull { it.isNotEmpty() }
            ?.take(MAX_REASON_CHARS).orEmpty()
        return ApprovalSummary(
            id = id,
            status = item.optString("status", "unknown").trim().ifBlank { "unknown" },
            action = action.take(MAX_ACTION_CHARS),
            reason = reason,
            createdAt = item.optString("created_at").trim().ifBlank { null },
            raw = item,
        )
    }

    private fun request(method: String, path: String, jsonBody: String? = null): String {
        val credential = credentialStore.loadDesktopCredential()
            ?: throw IllegalStateException("mobile device is not paired")
        val baseUri = URI(credential.baseUrl)
        require(baseUri.scheme.equals("https", true) && baseUri.host?.isNotBlank() == true) {
            "desktop endpoint must use HTTPS"
        }
        require(path.startsWith("/api/approvals")) { "approval API path escaped the approval boundary" }

        val connection = (baseUri.resolve(path).toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 30_000
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
            if (jsonBody != null) connection.outputStream.use { it.write(jsonBody.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader(Charsets.UTF_8)?.use {
                val text = it.readText()
                if (text.length > MAX_RESPONSE_CHARS) throw DesktopApiException("desktop approval response exceeded mobile safety limit")
                text
            }.orEmpty()
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(response).optString("detail") }.getOrNull()?.take(400)?.ifBlank { null }
                throw DesktopApiException(detail ?: "desktop approval API rejected request with HTTP $code")
            }
            response
        } finally {
            connection.disconnect()
        }
    }

    private fun encodePathSegment(value: String): String = URLEncoder.encode(boundedId(value), StandardCharsets.UTF_8.toString()).replace("+", "%20")
    private fun encodeQueryValue(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun boundedId(value: String): String {
        val clean = value.trim()
        require(clean.isNotEmpty() && clean.length <= 128) { "invalid approval id" }
        return clean
    }

    companion object {
        private const val MAX_RESPONSE_CHARS = 1_000_000
        private const val MAX_ACTION_CHARS = 240
        private const val MAX_REASON_CHARS = 4000
        private val ALLOWED_STATUSES = setOf("pending", "approved", "denied")
        private val ALLOWED_DECISIONS = setOf("approved", "denied")
    }
}
