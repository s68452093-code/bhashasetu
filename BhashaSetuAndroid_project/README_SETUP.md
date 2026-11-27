# BHASHASETU Android Build Guide

### Requirements
1. **Android Studio** (Koala or newer)
2. **Java JDK 17**

### Architecture (Data on Laptop -> Client on App)
To prevent downloading hundreds of megabytes of landmark detectors on your local phone, this setup streams camera coordinate vectors over your local network to your laptop.

### How to Run
1. Copy the `BhashaSetuAndroid` directory to your laptop.
2. Run `python laptop_server.py` in your terminal.
3. Open `BhashaSetuAndroid` in Android Studio and click **Build APK** / **Run App**.
