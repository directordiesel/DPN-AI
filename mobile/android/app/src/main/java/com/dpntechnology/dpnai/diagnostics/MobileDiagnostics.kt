package com.dpntechnology.dpnai.diagnostics

import android.content.Context
import java.time.Instant

object MobileDiagnostics {
    private const val PREFS = "dpn_ai_mobile_diagnostics"
    private const val KEY_LAST_ERROR = "last_error"
    private const val MAX_ERROR_CHARS = 2000

    fun recordError(context: Context, area: String, error: Throwable) {
        val safeArea = area.filter { it.isLetterOrDigit() || it in "-_" }.take(80).ifBlank { "mobile" }
        val safeMessage = sanitize(error.message ?: error::class.java.simpleName)
        val entry = "${Instant.now()} | $safeArea | ${error::class.java.simpleName}: $safeMessage"
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_LAST_ERROR, entry.take(MAX_ERROR_CHARS))
            .apply()
    }

    fun lastError(context: Context): String? = context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getString(KEY_LAST_ERROR, null)

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_LAST_ERROR).apply()
    }

    private fun sanitize(value: String): String {
        var clean = value.replace(Regex("(?i)(token|password|secret|authorization|x-dpn-token)\\s*[:=]\\s*[^\\s,;]+"), "$1=<redacted>")
        clean = clean.replace(Regex("https://[^@\\s]+@"), "https://<redacted>@")
        return clean.take(MAX_ERROR_CHARS)
    }
}
