# BhashaSetu — Android project (build-ready)

A complete, self-contained Android/Gradle project. Drop the contents of the zip at
your **repository root**, push, and GitHub Actions produces
`app-debug.apk`.

**This scaffold was built and verified here** — not just written:

```
BUILD SUCCESSFUL in 1m 10s
app/build/outputs/apk/debug/app-debug.apk   (5.8 MB)
apksigner verify  -> SIGNATURE VERIFIED OK
zipalign -c 4     -> ALIGNED OK
launchable-activity: com.example.bhashasetu.MainActivity  label='BhashaSetu'
minSdk 24 · targetSdk 34 · compileSdk 34
```

## What this is, honestly

It is the **toolchain proof**: Gradle 8.7 + AGP 8.5.2 + Kotlin 1.9.24 + AndroidX
builds a signed, installable debug APK containing one placeholder screen.

It does **not** contain the camera, recognition, avatar or speech features yet.
Those come next. Pushing this first is deliberate: it isolates build failures
from feature failures, which is exactly what bit you on the previous run.

## File map

```
repository-root/
├── settings.gradle                  repositories + include ':app'
├── build.gradle                     AGP 8.5.2 / Kotlin 1.9.24, apply false
├── gradle.properties                JVM args, AndroidX, UTF-8
├── gradlew / gradlew.bat            Gradle wrapper scripts
├── gradle/wrapper/
│   ├── gradle-wrapper.jar           REAL jar (43 KB), not a placeholder
│   └── gradle-wrapper.properties    pins gradle-8.7-bin.zip
├── .gitignore                       ignores build/, local.properties, *.apk
├── .github/workflows/
│   ├── build.yml                    main CI: build + upload APK artifact
│   └── release-debug-apk.yml        optional: draft GitHub Release with APK
└── app/
    ├── build.gradle                 compileSdk 34, minSdk 24, viewBinding
    ├── proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml
        ├── java/com/example/bhashasetu/MainActivity.kt
        └── res/
            ├── layout/activity_main.xml
            └── values/strings.xml
```

## Push it (two ways)

**Option A — GitHub web UI**
1. Unzip anywhere.
2. On your repo page: *Add file → Upload files*.
3. Drag the **contents** (not the outer folder): `settings.gradle`, `build.gradle`,
   `gradle.properties`, `gradlew`, `gradlew.bat`, the `gradle/`, `app/` and
   `.github/` folders.
4. Commit. The `Build debug APK` workflow runs automatically.

> The `.github` folder starts with a dot — your file manager may hide it. On macOS
> press `Cmd+Shift+.`; on Windows enable *View → Hidden items*.

**Option B — command line (safer, keeps file modes)**
```bash
cd your-repo
git checkout -b android-scaffold
unzip -o ~/Downloads/bhashasetu_android.zip -d .
git add -A
git commit -m "Android scaffold: Gradle 8.7, AGP 8.5.2, Kotlin 1.9.24"
git push -u origin android-scaffold
```

`gradlew` **must stay executable** (`100755`). Option B preserves that; Option A
sometimes does not, which is why the workflow also contains a `chmod +x ./gradlew`
step in the release workflow.

## Get the APK

1. Repo → **Actions** → *Build debug APK* → newest green run.
2. Bottom of the run page → **Artifacts** → `BhashaSetu-debug-apk`.
3. Unzip it (GitHub zips artifacts) and install `app-debug.apk` on the phone.
   You must allow *Install unknown apps* for your browser/file manager.

## Build locally instead

```bash
# JDK 17 required (17 or 21 both work with AGP 8.5.2; 11 does not)
./gradlew assembleDebug
# output: app/build/outputs/apk/debug/app-debug.apk
```

Create `local.properties` once (never commit it):
```properties
sdk.dir=/path/to/Android/Sdk
```

## The one memory setting that matters

`gradle.properties` is deliberately capped:
```properties
org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=384m -Dfile.encoding=UTF-8
org.gradle.parallel=false
org.gradle.workers.max=1
```
The first build attempt here **died** with
`DaemonDisappearedException` at `-Xmx2048m` on a 1 GB machine (OOM killer,
`Killed process ... (java)`). At 1 GB with one worker it built fine. If your CI
runner or laptop has plenty of RAM you can raise this, but the low values are
safe everywhere and this project needs almost nothing.

## If the build fails again

Read the **first** 10 lines of the failing step, not the bottom. The bottom is
Gradle's generic daemon stack trace, which is what misled the previous attempt.

| First-line symptom | Cause | Fix |
|---|---|---|
| `Unsupported class file major version` | wrong JDK | keep `java-version: '17'` |
| `Failed to find target with hash string 'android-34'` | platform not installed | the `sdkmanager` step covers it |
| `SDK location not found` | no SDK / no `local.properties` | `setup-android@v3` sets `ANDROID_HOME`; locally add `local.properties` |
| `Permission denied: ./gradlew` | mode lost on upload | `git update-index --chmod=+x gradlew` |
| `Could not find method ...` in a `.gradle` file | stray text/partial paste | re-copy the file whole from the zip |
| Daemon dies instantly, no tasks run | too little RAM or wrong JDK | the capped `jvmargs` above; JDK 17 |

## Package name

`com.example.bhashasetu`. Change `applicationId` + `namespace` in
`app/build.gradle` and move the Kotlin folder to match if you want
`in.bhashasetu.app` before publishing anywhere.
