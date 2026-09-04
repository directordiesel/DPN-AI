package com.dpntechnology.dpnai

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.dpntechnology.dpnai.network.DesktopApiClient
import com.dpntechnology.dpnai.security.SecureCredentialStore
import java.util.Locale
import kotlin.concurrent.thread

class VoiceActivity : Activity(), RecognitionListener, TextToSpeech.OnInitListener {
    private lateinit var api: DesktopApiClient
    private lateinit var status: TextView
    private lateinit var transcript: TextView
    private lateinit var talkButton: Button
    private lateinit var speechRecognizer: SpeechRecognizer
    private lateinit var tts: TextToSpeech
    private var listening = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = DesktopApiClient(SecureCredentialStore(this))
        speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this).also { it.setRecognitionListener(this) }
        tts = TextToSpeech(this, this)
        setContentView(buildUi())
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_HORIZONTAL
        setPadding(36, 48, 36, 36)
        setBackgroundColor(Color.rgb(7, 7, 10))
        layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        addView(TextView(this@VoiceActivity).apply {
            text = "DPN AI • Voice"
            textSize = 26f
            setTextColor(Color.WHITE)
        })
        addView(TextView(this@VoiceActivity).apply {
            text = "Tap to talk • no background listening"
            textSize = 12f
            setTextColor(Color.rgb(167, 139, 250))
            setPadding(0, 4, 0, 36)
        })
        status = TextView(this@VoiceActivity).apply {
            text = "Ready for an explicit voice request."
            textSize = 15f
            setTextColor(Color.LTGRAY)
            setPadding(0, 0, 0, 24)
        }
        addView(status)
        transcript = TextView(this@VoiceActivity).apply {
            text = "Your spoken request and DPN AI reply will appear here."
            textSize = 17f
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(18, 16, 27))
            setPadding(24, 24, 24, 24)
        }
        addView(transcript, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        talkButton = Button(this@VoiceActivity).apply {
            text = "Tap to Talk"
            setOnClickListener {
                if (listening) stopListening() else requestMicrophoneAndListen()
            }
        }
        addView(talkButton)
        addView(Button(this@VoiceActivity).apply {
            text = "Stop Speaking"
            setOnClickListener { tts.stop() }
        })
    }

    private fun requestMicrophoneAndListen() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_AUDIO)
            return
        }
        startListening()
    }

    private fun startListening() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            status.text = "Speech recognition is unavailable on this device."
            return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        }
        listening = true
        talkButton.text = "Stop Listening"
        status.text = "Listening only while this voice session is active…"
        speechRecognizer.startListening(intent)
    }

    private fun stopListening() {
        if (!listening) return
        speechRecognizer.stopListening()
        listening = false
        talkButton.text = "Tap to Talk"
        status.text = "Voice capture stopped."
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_AUDIO) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startListening()
            else status.text = "Microphone permission denied — voice capture remains off."
        }
    }

    override fun onResults(results: Bundle?) {
        listening = false
        talkButton.text = "Tap to Talk"
        val spoken = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim().orEmpty()
        if (spoken.isEmpty()) {
            status.text = "No speech was recognized."
            return
        }
        submitVoiceRequest(spoken)
    }

    override fun onPartialResults(partialResults: Bundle?) {
        val partial = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()
        if (!partial.isNullOrEmpty()) transcript.text = "YOU\n$partial"
    }

    private fun submitVoiceRequest(spoken: String) {
        transcript.text = "YOU\n$spoken\n\nDPN AI\nWorking…"
        status.text = "Sending voice request to the unified DPN AI runtime…"
        talkButton.isEnabled = false
        thread(name = "dpn-mobile-voice-chat") {
            val result = runCatching {
                api.sendChat(
                    conversationId = null,
                    message = spoken,
                    profile = "auto",
                    executionMode = "auto",
                    verify = false,
                )
            }
            runOnUiThread {
                talkButton.isEnabled = true
                result.onSuccess { reply ->
                    transcript.text = "YOU\n$spoken\n\nDPN AI\n${reply.message}"
                    status.text = "Voice reply synchronized with DPN AI conversation ${reply.conversationId}."
                    speakReply(reply.message)
                }.onFailure { error ->
                    transcript.text = "YOU\n$spoken\n\nSYSTEM\nVoice request failed: ${error.message ?: "unknown error"}"
                    status.text = "Voice request failed — no success was fabricated."
                }
            }
        }
    }

    private fun speakReply(text: String) {
        if (text.isBlank()) return
        val bounded = text.take(MAX_SPEAK_CHARS)
        tts.speak(bounded, TextToSpeech.QUEUE_FLUSH, null, "dpn-ai-mobile-reply")
    }

    override fun onInit(statusCode: Int) {
        if (statusCode == TextToSpeech.SUCCESS) {
            tts.language = Locale.getDefault()
            tts.setSpeechRate(0.95f)
        }
    }

    override fun onError(error: Int) {
        listening = false
        talkButton.text = "Tap to Talk"
        status.text = "Voice recognition stopped with error code $error."
    }

    override fun onDestroy() {
        if (listening) speechRecognizer.cancel()
        speechRecognizer.destroy()
        tts.stop()
        tts.shutdown()
        super.onDestroy()
    }

    override fun onReadyForSpeech(params: Bundle?) = Unit
    override fun onBeginningOfSpeech() = Unit
    override fun onRmsChanged(rmsdB: Float) = Unit
    override fun onBufferReceived(buffer: ByteArray?) = Unit
    override fun onEndOfSpeech() {
        listening = false
        talkButton.text = "Tap to Talk"
        status.text = "Processing speech…"
    }
    override fun onEvent(eventType: Int, params: Bundle?) = Unit

    companion object {
        private const val REQUEST_AUDIO = 4101
        private const val MAX_SPEAK_CHARS = 12_000
    }
}
