# What's new

**This release is about trust and verification — no app features changed.**

- Releases are now **built by GitHub Actions directly from the tagged source code** (not on a personal machine). Every release links its build log, so the download provably matches the code in the repository.
- Every release now ships a **SHA-256 checksum** (`SHA256SUMS.txt`) and a **VirusTotal scan** of the exact published file.
- New [SECURITY.md](https://github.com/markosharknz1/Club_Training/blob/master/SECURITY.md) explains in plain English what the app does (and doesn't do) with your club's data: everything stays in one local file on your computer, no cloud, no telemetry, and the only network traffic is the email/payment services you choose to configure.

## Install / update

1. Download `Club_Training_v1.7.1.zip` below and unzip anywhere. No Python or internet needed.
2. **Updating?** Copy your `badminton.db` (and `backups` folder) from the old app folder into the new one first.
3. Double-click `Club_Training.exe`.
