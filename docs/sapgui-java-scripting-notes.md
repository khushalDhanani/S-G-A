# SAP GUI for Java scripting discovery

## Read-only search findings

- SAP GUI for Java is installed at `/Applications/SAP Clients/SAPGUI 8.10rev13/SAPGUI 8.10rev13.app`.
- The running macOS GUI process name is `SAPGUI`.
- A search of SAP-related locations under `~/Library`, `~/Documents`, and `/Applications/SAP Clients` found SAP application support/preferences directories, but no user-facing SAP GUI for Java scripting or recorded-script folder.
- The only script-named folder found under the SAP GUI app bundle was `Contents/Resources/jre/Contents/Home/legal/java.scripting`. This is part of the bundled Java runtime, not a SAP GUI recording folder.
- No `*.js` files were found inside SAP GUI application bundles. The app bundle was searched by path only; no files in it were opened or changed.
- `~/Library/Preferences/SAP/Cache/webview/Default/Extension Scripts` also exists, but it appears to be a webview cache directory and is not confirmed as a SAP GUI script location.

## Manual next steps

1. Open SAP GUI for Java and sign in manually.
2. Open **Scripts > Scripting** in the macOS menu bar.
3. Start recording, open transaction `VA05`, enter a date range, and choose **Execute**.
4. Stop the recording and save the script to a convenient location outside the SAP application bundle.
5. Before sharing it, replace client numbers, user names, and any confidential values with placeholders. Then paste the sanitized script into the chat.

Do not include passwords, authentication tokens, or other system secrets in a shared script.
