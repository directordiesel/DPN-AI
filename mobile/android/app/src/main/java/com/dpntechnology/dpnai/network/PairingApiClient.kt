package com.dpntechnology.dpnai.network

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI

class PairingApiClient {
    data class PairingResult(
        val deviceId: String,
        val deviceName: String,
        val token: String,
        val issuedAt: Long,
    )

    fun completePairing(
        baseUrl: String,
        challengeId: String,
        secret: String,
        deviceId: String,
        deviceName: String,
    ): PairingResult {
        val base = validateBaseUrl(baseUrl)
        val cleanChallenge = challengeId.trim()
        val cleanSecret = secret.trim()
        val cleanDeviceId = deviceId.trim()
        val cleanDeviceName = deviceName.trim().replace(Regex("\\s+"), " ")
        require(cleanChallenge.isNotEmpty() && cleanChallenge.length <= 128) { "invalid pairing challenge" }
        require(cleanSecret.isNotEmpty() && cleanSecret.length <= 256) { "invalid pairing proof" }
        require(cleanDeviceId.isNotEmpty() && cleanDeviceId.length <= 128) { "invalid device id" }
        require(cleanDeviceName.isNotEmpty() && cleanDeviceName.length <= 80) { "invalid device name" }

        val payload = JSONObject()
            .put("challenge_id", cleanChallenge)
            .put("secret", cleanSecret)
            .put("device_id", cleanDeviceId)
            .put("device_name", cleanDeviceName)
            .toString()

        val connection = (base.resolve(PAIRING_PATH).toURL().openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            instanceFollowRedirects = false
            doOutput = true
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setFixedLengthStreamingMode(payload.toByteArray(Charsets.UTF_8).size)
        }

        val response = try {
            connection.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            readResponse(connection)
        } finally {
            connection.disconnect()
        }

        val json = JSONObject(response)
        val returnedId = json.optString("device_id").trim()
        val returnedName = json.optString("device_name").trim()
        val token = json.optString("token")
        val issuedAt = json.optLong("issued_at", 0L)
        if (returnedId != cleanDeviceId || returnedName.isEmpty() || token.length < 32 || issuedAt <= 0L) {
            throw DesktopApiException("desktop returned an invalid pairing credential")
        }
        return PairingResult(returnedId, returnedName, token, issuedAt)
    }

    private fun validateBaseUrl(raw: String): URI {
        val normalized = raw.trim().trimEnd('/') + "/"
        val uri = URI(normalized)
        require(uri.scheme.equals("https", ignoreCase = true)) { "desktop endpoint must use HTTPS" }
        require(!uri.host.isNullOrBlank()) { "desktop endpoint host is required" }
        require(uri.userInfo == null) { "desktop endpoint must not contain embedded credentials" }
        require(uri.query == null && uri.fragment == null) { "desktop endpoint must not contain query or fragment data" }
        require(uri.path == "/" || uri.path.isNullOrEmpty()) { "desktop endpoint must not contain a path" }
        return uri
    }

    private fun readResponse(connection: HttpURLConnection): String {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader(Charsets.UTF_8)?.use {
            val text = it.readText()
            if (text.length > MAX_RESPONSE_CHARS) throw DesktopApiException("pairing response exceeded safety limit")
            text
        }.orEmpty()
        if (code !in 200..299) {
            val detail = runCatching { JSONObject(response).optString("detail") }.getOrNull()
                ?.take(300)?.ifBlank { null }
            throw DesktopApiException(detail ?: "desktop rejected pairing with HTTP $code")
        }
        return response
    }

    companion object {
        private const val PAIRING_PATH = "/mobile/v1/pairing/complete"
        private const val CONNECT_TIMEOUT_MS = 8_000
        private const val READ_TIMEOUT_MS = 15_000
        private const val MAX_RESPONSE_CHARS = 32_000
    }
}
