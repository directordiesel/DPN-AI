package com.dpntechnology.dpnai.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureCredentialStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun saveDesktopCredential(baseUrl: String, deviceId: String, token: String) {
        require(baseUrl.startsWith("https://")) { "desktop endpoint must use HTTPS" }
        require(deviceId.isNotBlank() && deviceId.length <= 128) { "invalid device id" }
        require(token.length >= 32) { "device credential is too short" }
        prefs.edit()
            .putString(KEY_ENDPOINT, encrypt(baseUrl))
            .putString(KEY_DEVICE_ID, encrypt(deviceId))
            .putString(KEY_TOKEN, encrypt(token))
            .apply()
    }

    fun loadDesktopCredential(): DesktopCredential? {
        val endpoint = prefs.getString(KEY_ENDPOINT, null) ?: return null
        val deviceId = prefs.getString(KEY_DEVICE_ID, null) ?: return null
        val token = prefs.getString(KEY_TOKEN, null) ?: return null
        return DesktopCredential(decrypt(endpoint), decrypt(deviceId), decrypt(token))
    }

    fun clear() {
        prefs.edit().clear().apply()
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

    data class DesktopCredential(val baseUrl: String, val deviceId: String, val token: String)

    companion object {
        private const val PREFS = "dpn_ai_secure_device"
        private const val KEY_ALIAS = "dpn_ai_mobile_device_credential_v1"
        private const val KEY_ENDPOINT = "desktop_endpoint"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_TOKEN = "device_token"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val IV_BYTES = 12
        private const val TAG_BITS = 128
    }
}
