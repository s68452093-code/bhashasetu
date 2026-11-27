package com.bhashasetu.app

import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.view.View
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.ToggleButton
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {

    private lateinit var btnSignToText: Button
    private lateinit var btnTextToSign: Button
    private lateinit var layoutSignToText: LinearLayout
    private lateinit var layoutTextToSign: LinearLayout

    // Sign -> Text Components
    private lateinit var viewFinder: PreviewView
    private lateinit var toggleWordsOnly: ToggleButton
    private lateinit var tvPredictionResult: TextView
    private lateinit var tvConnectionStatus: TextView
    private lateinit var etSentence: EditText
    private lateinit var btnClear: Button
    private lateinit var btnSpeak: Button
    
    // Text -> Sign Components
    private lateinit var etSearchSign: EditText
    private lateinit var btnPlaySign: Button
    private lateinit var avatarWebView: WebView

    private var tts: TextToSpeech? = null
    private lateinit var cameraExecutor: ExecutorService

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Initialize Views
        btnSignToText = findViewById(R.id.btn_sign_to_text)
        btnTextToSign = findViewById(R.id.btn_text_to_sign)
        layoutSignToText = findViewById(R.id.layout_sign_to_text)
        layoutTextToSign = findViewById(R.id.layout_text_to_sign)

        viewFinder = findViewById(R.id.view_finder)
        toggleWordsOnly = findViewById(R.id.toggle_words_only)
        tvPredictionResult = findViewById(R.id.tv_prediction_result)
        tvConnectionStatus = findViewById(R.id.tv_connection_status)
        etSentence = findViewById(R.id.et_sentence)
        btnClear = findViewById(R.id.btn_clear)
        btnSpeak = findViewById(R.id.btn_speak)

        etSearchSign = findViewById(R.id.et_search_sign)
        btnPlaySign = findViewById(R.id.btn_play_sign)
        avatarWebView = findViewById(R.id.avatar_webview)

        // Navigation Handler
        btnSignToText.setOnClickListener {
            layoutSignToText.visibility = View.VISIBLE
            layoutTextToSign.visibility = View.GONE
            btnSignToText.setBackgroundColor(ContextCompat.getColor(this, android.R.color.holo_blue_dark))
            btnTextToSign.setBackgroundColor(ContextCompat.getColor(this, android.R.color.darker_gray))
        }

        btnTextToSign.setOnClickListener {
            layoutSignToText.visibility = View.GONE
            layoutTextToSign.visibility = View.VISIBLE
            btnTextToSign.setBackgroundColor(ContextCompat.getColor(this, android.R.color.holo_blue_dark))
            btnSignToText.setBackgroundColor(ContextCompat.getColor(this, android.R.color.darker_gray))
            setupAvatarWebView()
        }

        // TTS initialization
        tts = TextToSpeech(this, this)

        btnSpeak.setOnClickListener {
            val text = etSentence.text.toString()
            if (text.isNotEmpty()) {
                tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "")
            }
        }

        btnClear.setOnClickListener {
            etSentence.setText("")
        }

        // Start Camera Service
        cameraExecutor = Executors.newSingleThreadExecutor()
        startCamera()

        // Sign Animation Button trigger
        btnPlaySign.setOnClickListener {
            val queryWord = etSearchSign.text.toString().trim().uppercase()
            if (queryWord.isNotEmpty()) {
                // JavaScript call into realistic_isl_avatar_demo.html's web playback
                avatarWebView.evaluateJavascript("javascript:playSignClip('${queryWord}');", null)
            }
        }
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            val cameraProvider: ProcessCameraProvider = cameraProviderFuture.get()
            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(viewFinder.surfaceProvider)
            }

            val imageAnalyzer = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
                .also {
                    it.setAnalyzer(cameraExecutor) { imageProxy ->
                        // FRAME DISPATCH LOOP
                        // Sends frames/landmarks over sockets/local-host to Laptop for inference
                        // Keeping models/landmarks on the Laptop to save space on mobile storage
                        imageProxy.close()
                    }
                }

            val cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
            try {
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(this, cameraSelector, preview, imageAnalyzer)
            } catch (exc: Exception) {
                tvPredictionResult.text = "Camera Error: " + exc.message
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun setupAvatarWebView() {
        val webSettings: WebSettings = avatarWebView.settings
        webSettings.javaScriptEnabled = true
        webSettings.allowFileAccess = true
        webSettings.allowContentAccess = true
        webSettings.domStorageEnabled = true

        avatarWebView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
            }
        }
        
        // Load local file packaged in assets folder
        avatarWebView.loadUrl("file:///android_asset/avatar/realistic_isl_avatar_demo.html")
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts?.language = Locale.US
        }
    }

    override fun onDestroy() {
        if (tts != null) {
            tts?.stop()
            tts?.shutdown()
        }
        cameraExecutor.shutdown()
        super.onDestroy()
    }
}
