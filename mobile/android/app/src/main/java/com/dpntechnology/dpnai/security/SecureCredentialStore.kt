package com.dpntechnology.dpnai.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.net.URI
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureCredentialStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun saveDesktopCredential(baseUrl: String, deviceId: String, token: String) {
        validateHttpsEndpoint(baseUrl)
        require(deviceId.isNotBlank() && deviceId.length <= 128) { "invalid device id" }
        require(token.length >= 32) { "device credential is too short" }
        prefs.edit()
            .putString(KEY_LOCAL_ENDPOINT, encrypt(baseUrl))
            .putString(KEY_DEVICE_ID, encrypt(deviceId))
            .putString(KEY_LOCAL_TOKEN, encrypt(token))
            .apply()
    }

    fun saveRemoteGateway(baseUrl: String, gatewayToken: String) {
        val uri = validateHttpsEndpoint(baseUrl)
        require(!isLoopbackHost(uri.host)) { "remote gateway must not use a loopback host" }
        require(gatewayToken.length >= 32) { "remote gateway credential is too short" }
        require(loadLocalCredential() != null) { "pair this device locally before enabling remote gateway access" }
        prefs.edit()
            .putString(KEY_REMOTE_ENDPOINT, encrypt(baseUrl.trimEnd('/')))
            .putString(KEY_REMOTE_TOKEN, encrypt(gatewayToken))
            .apply()
    }

    fun hasRemoteGateway(): Boolean = prefs.contains(KEY_REMOTE_ENDPOINT) && prefs.contains(KEY_REMOTE_TOKEN)

    fun setRemoteMode(enabled: Boolean) {
        if (enabled) require(hasRemoteGateway()) { "remote gateway is not configured" }
        prefs.edit().putBoolean(KEY_REMOTE_MODE, enabled).apply()
    }

    fun isRemoteMode(): Boolean = prefs.getBoolean(KEY_REMOTE_MODE, false)

    fun loadDesktopCredential(): DesktopCredential? {
        val local = loadLocalCredential() ?: return null
        if (!isRemoteMode()) return local
        val endpoint = prefs.getString(KEY_REMOTE_ENDPOINT, null) ?: return null
        val token = prefs.getString(KEY_REMOTE_TOKEN, null) ?: return null
        return DesktopCredential(decrypt(endpoint), local.deviceId, decrypt(token), ConnectionMode.REMOTE_GATEWAY)
    }

    fun loadLocalCredential(): DesktopCredential? {
        val endpoint = prefs.getString(KEY_LOCAL_ENDPOINT, null) ?: return null
        val deviceId = prefs.getString(KEY_DEVICE_ID, null) ?: return null
        val token = prefs.getString(KEY_LOCAL_TOKEN, null) ?: return null
        return DesktopCredential(decrypt(endpoint), decrypt(deviceId), decrypt(token), ConnectionMode.LOCAL_DESKTOP)
    }

    fun clearRemoteGateway() {
        prefs.edit()
            .remove(KEY_REMOTE_ENDPOINT)
            .remove(KEY_REMOTE_TOKEN)
            .putBoolean(KEY_REMOTE_MODE, false)
            .apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    private fun validateHttpsEndpoint(baseUrl: String): URI {
        val uri = URI(baseUrl.trim())
        require(uri.scheme.equals("https", ignoreCase = true)) { "endpoint must use HTTPS" }
        require(!uri.host.isNullOrBlank()) { "endpoint host is required" }
        require(uri.userInfo == null) { "endpoint must not contain embedded credentials" }
        require(uri.fragment == null && uri.query == null) { "endpoint must not contain query or fragment data" }
        return uri
    }

    private fun isLoopbackHost(host: String?): Boolean {
        val clean = host?.trim()?.lowercase().orEmpty()
        return clean == "localhost" || clean == "127.0.0.1" || clean == "::1" || clean.endsWith(".localhost")
    }

    private fun encrypt(value: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(cipher.iv + encrypted, Base64.NO_WRAP)
    }

    private fun decrypt(encoded: String): String {
        val payload = Base64.decode(encoded, Base64.NO_WRAP)
        require(payload.size > IV_BYTES) { "invalid encrypted credential" }
        val iv = payload.copyOfRange(0, IV_BYTES)
        val ciphertext = payload.copyOfRange(IV_BYTES, payload.size)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(TAG_BITS, iv))
        return cipher.doFinal(ciphertext).toString(Charsets.UTF_8)
    }

    private fun getOrCreateKey(): SecretKey {
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }

    enum class ConnectionMode { LOCAL_DESKTOP, REMOTE_GATEWAY }

    data class DesktopCredential(
        val baseUrl: String,
        val deviceId: String,
        val token: String,
        val mode: ConnectionMode = ConnectionMode.LOCAL_DESKTOP,
    )

    companion object {
        private const val PREFS = "dpn_ai_secure_device"
        private const val KEY_ALIAS = "dpn_ai_mobile_device_credential_v1"
        private const val KEY_LOCAL_ENDPOINT = "desktop_endpoint"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_LOCAL_TOKEN = "device_token"
        private const val KEY_REMOTE_ENDPOINT = "remote_gateway_endpoint"
        private const val KEY_REMOTE_TOKEN = "remote_gateway_token"
        private const val KEY_REMOTE_MODE = "remote_gateway_enabled"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_BYTES = 12
        private const val TAG_BITS = 128
    }
}
