package com.example.bhashasetu

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.example.bhashasetu.databinding.ActivityMainBinding

/**
 * Scaffold activity.
 *
 * Proves the project compiles end to end: viewBinding is generated, the Material
 * theme resolves, and the resources are wired. The two real workflows
 * (Sign -> Text and Text -> Sign) replace this layout in later steps.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.checkButton.setOnClickListener {
            Toast.makeText(
                this,
                getString(R.string.placeholder_toast),
                Toast.LENGTH_SHORT
            ).show()
        }
    }
}
