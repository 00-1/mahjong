---
name: Bring Termux to foreground after each test
description: After any adb-driven UI test that puts a different app on the phone screen, return Termux to the foreground so the user can see when the test ends
type: feedback
originSessionId: 867f7e23-ba91-4e93-8461-56ec94ed26f0
---
After running any adb test that navigates the phone to another app or screen, end the sequence by bringing Termux back to the foreground (`adb shell am start -n com.termux/.app.TermuxActivity`). This applies whenever I use adb to drive other apps in this Poco F6 setup.

**Why:** The user often watches the phone screen passively to see when a test finishes. If the phone is left on a settings page or some random app, they can't tell whether the run is still in progress or done, and they have no quick path back to the conversation view.

**How to apply:** After any `adb shell am start` to a non-Termux app, after scrcpy/xdotool sequences, or after any tap-injection test, run `adb shell am start -n com.termux/.app.TermuxActivity` as the last step before reporting back. Skip only when the test itself is supposed to leave another app on screen for inspection.
