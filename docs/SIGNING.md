# Optional signing of the experimental APK

The manual workflow still builds **unsigned by default**. Set `sign_apk` to `true` only after reviewing the source and configuring your own key. Signing creates an installable experimental artifact, **not proof that login, account safety, or runtime behavior is validated**. No tag or release is created.

This change only prepares repository files. It does not generate a key, upload secrets, authenticate to GitHub, push changes, or run a signed build.

## Trust and prerequisites

- Use the repository's trusted default branch, **`4.0-dev`**. Both the selected ref and the repository default branch must match it. Other refs cannot use this workflow's signing job.
- Review every workflow and source change before dispatch. Protect the default branch and require review of `.github/workflows/`. Repository administrators and anyone able to run modified workflows with repository secrets are inside the trust boundary. The branch check is not protection against a malicious workflow rewrite by such a collaborator.
- All build, test, and full blocking lint steps must succeed. An unsigned archive can exist before lint finishes; its existence alone does not authorize signing.
- Use GitHub-hosted `ubuntu-24.04`, with the preinstalled Android Build Tools `36.0.0`. The signing job selects the same pinned Temurin JDK `17.0.20+8` through the pinned official setup-java action; it installs no Android SDK or application dependencies and never checks out or executes repository/artifact scripts. The build job never receives signing secrets.
- Treat your signing key as a long-lived identity. Keep an encrypted offline backup with recovery instructions. Losing it can prevent updates to installations signed by that key. Never send a private key, password, or base64 keystore in chat, an issue, a commit, a log, or an artifact.

## User-operated key and secret setup

Perform these steps yourself on a trusted computer. The assistant must not read, generate, or upload your key/passwords.

1. Create a dedicated private directory **outside this checkout**, with restrictive permissions. Generate your own Android signing key with Android Studio's signing-key UI or the official JDK [`keytool`](https://docs.oracle.com/en/java/javase/17/docs/specs/man/keytool.html). For example, in that private directory:

   ```sh
   umask 077
   keytool -genkeypair -v -keystore learning-signing.p12 -storetype PKCS12 \
     -alias learning -keyalg RSA -keysize 4096 -validity 10000
   ```

   Follow the interactive prompts; do not put passwords in command arguments or shell history. Use suitable certificate subject values, understanding that certificate information is public in signed APKs. PKCS12 commonly uses the same password for the keystore and private key: supply that same password to both password secrets below. This workflow explicitly requires a PKCS12 keystore. Do not replace an established application key without planning update compatibility.

2. Inspect the public certificate fingerprint locally:

   ```sh
   keytool -list -v -keystore learning-signing.p12 -alias learning
   ```

   Copy the certificate's **SHA256 fingerprint**, not a hash of the keystore file. This command prompts for the password. Do not share the private keystore.

3. Encode the keystore to a local private temporary file, without displaying its contents:

   ```sh
   base64 < learning-signing.p12 > keystore.b64
   ```

   Base64 is encoding, **not encryption**. Treat this file exactly like the keystore. The workflow accepts line wrapping. GitHub repository secrets have a 48 KB limit; if the encoded value exceeds it, stop and review an alternative design rather than committing key material.

4. In your repository, open **Settings → Secrets and variables → Actions → Secrets**, and personally create these four repository secrets through GitHub's secure UI:

   - `ANDROID_KEYSTORE_BASE64`: the full encoded keystore file contents
   - `ANDROID_KEYSTORE_PASSWORD`: the keystore password
   - `ANDROID_KEY_ALIAS`: the key alias, such as the one you selected during generation
   - `ANDROID_KEY_PASSWORD`: the private-key password; for the PKCS12 example, the same password as the keystore

   Then under **Variables**, create the required public repository variable `ANDROID_SIGNING_CERT_SHA256` with the fingerprint from step 2. It accepts 64 hexadecimal characters, with or without colons; no surrounding whitespace. Signing fails closed if the variable is missing, malformed, or does not match the signed APK's sole signer.

5. Delete the temporary base64 copy using your computer's normal secure handling procedures; retain the original keystore and encrypted backup safely. Do not rely on `.gitignore` as secret protection: it only reduces accidental staging and does not remove already-tracked files.

Official references: [Android app signing](https://developer.android.com/studio/publish/app-signing), [GitHub secret management and limits](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## Dispatch and verification

1. After the reviewed changes are committed to `4.0-dev`, open **Actions → Build learning APK → Run workflow**.
2. Select `4.0-dev`. Leave signing unchecked for normal unsigned builds, or explicitly enable `sign_apk` for this run.
3. Wait for the entire build job, including full lint. The isolated signing job then downloads the exact immutable artifact ID produced by that successful build in the current workflow run. It accepts no user-supplied artifact name, run ID, branch, or URL.
4. Download `SIGNED-EXPERIMENTAL-not-login-validated-<commit>-<attempt>` only after the signing job succeeds. Retention is **3 days**. It contains only:
   - `experimental-not-login-validated.apk`
   - `SHA256SUMS` for the APK and metadata
   - `signing-metadata.json` with source commit/repository/run/attempt, unsigned artifact ID, original and signed APK SHA-256, public certificate SHA-256, and the experimental warning
5. Independently verify downloaded checksums and the APK's certificate with Android SDK tools:

   ```sh
   sha256sum --check SHA256SUMS
   apksigner verify --verbose --print-certs experimental-not-login-validated.apk
   ```

   Compare the reported signer certificate SHA-256 with your trusted local fingerprint. Do not modify or re-align the APK after signing. Passing signature verification establishes integrity/signing identity, not application safety.

The job validates the input file allowlist, checksums, metadata source/run/attempt, clean working tree, single unsplit APK output, and expected Build Tools version before exposing secrets. It checks alignment before signing. Passwords are passed through `apksigner` environment-variable references, not plaintext command arguments. Keystore bytes exist only in a private directory under `runner.temp`, removed by an exit trap and an `always()` cleanup step. Hard runner termination can prevent cleanup code, so this design depends on disposable hosted runners; it is not a secure-erasure guarantee for self-hosted machines.

Official tooling references: [apksigner options](https://developer.android.com/tools/apksigner), [zipalign ordering](https://developer.android.com/tools/zipalign), [pinned download-artifact v8.0.1](https://github.com/actions/download-artifact/commit/3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c). The download action uses its current-run default and fails on digest mismatch.

## Failures and reruns

- A missing or wrong secret, unsupported key, incorrect certificate pin, validation failure, or signing error stops the job without uploading a signed artifact. Tool errors are intentionally suppressed to avoid accidental secret disclosure; do not enable shell tracing or dump environment variables to debug.
- Check settings locally, then start a **new full workflow run**, or rerun **all jobs**. Rerunning only a failed signing job against a previous attempt's unsigned artifact intentionally fails the strict run-attempt check.
- If lint fails, fix the source and run again. Do not bypass the gate or sign an older archive manually as if it passed.
- The unsigned artifact keeps its existing seven-day retention and experimental labels.

## Key-free regression checks

Run `python3 scripts/test_signing_workflow.py`. The suite executes extracted inline validation/signing code using temporary inert byte fixtures and a mock `apksigner`; it never generates or uses a real signing key. It checks identity mismatches, tampering, unexpected files/symlinks, fingerprint validation, public output allowlists, environment password arguments, failure cleanup, secret-safe errors, and workflow isolation. These checks are not a substitute for a future user-authorized real-key signing run and device smoke test.
