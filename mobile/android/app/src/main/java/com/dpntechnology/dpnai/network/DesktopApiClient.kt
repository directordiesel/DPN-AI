package com.dpntechnology.dpnai.network

import com.dpntechnology.dpnai.security.SecureCredentialStore
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class DesktopApiClient(private val credentialStore: SecureCredentialStore) {
    fun fetchDesktopSummary(): String {
        val credential = credentialStore.loadDesktopCredential()
            ?: throw IllegalStateException("mobile device is not paired")
        val baseUri = URI(credential.baseUrl)
        require(baseUri.scheme.equals("https", ignoreCase = true)) { "desktop endpoint must use HTTPS" }
        require(baseUri.host?.isNotBlank() == true) { "desktop endpoint host is required" }

        val endpoint = baseUri.resolve("/api/v1/desktop/summary").toURL()
        val connection = (endpoint.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 8_000
            readTimeout = 8_000
            instanceFollowRedirects = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-DPN-Token", credential.token)
            setRequestProperty("X-DPN-Device-ID", credential.deviceId)
        }
        return try {
            val code = connection.responseCode
            if (code !in 200..299) {
                throw DesktopApiException("desktop API rejected request with HTTP $code")
            }
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }
}

class DesktopApiException(message: String) : IllegalStateException(message)
