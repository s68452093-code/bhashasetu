# Debug builds do not use this file (minifyEnabled false).
# Release builds enable R8, so these rules matter there.

# Keep line numbers so crash reports stay readable.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Keep annotations (needed by reflection used in libraries).
-keepattributes *Annotation*

# Keep ViewBinding generated classes: layouts are resolved by name at runtime.
-keep class com.example.bhashasetu.databinding.** { *; }
-keepclassmembers class * extends androidx.viewbinding.ViewBinding {
    public static *** inflate(android.view.LayoutInflater);
    public static *** inflate(android.view.LayoutInflater, android.view.ViewGroup, boolean);
    public static *** bind(android.view.View);
}

# Keep the launcher activity name reachable from the manifest.
-keep class com.example.bhashasetu.MainActivity { *; }

# WebView JavaScript bridge classes would need keeping once the avatar screen
# adds an @JavascriptInterface. Left commented until that exists:
# -keepclassmembers class com.example.bhashasetu.avatar.** {
#     @android.webkit.JavascriptInterface <methods>;
# }
