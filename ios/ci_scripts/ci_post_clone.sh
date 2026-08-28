#!/bin/sh
set -eu

umask 077

repository_path="${CI_PRIMARY_REPOSITORY_PATH:?CI_PRIMARY_REPOSITORY_PATH is required}"

/usr/bin/env python3 \
  "$repository_path/scripts/install_firebase_ios_config.py" \
  --project zhang23-23 \
  --expected-app-id 1:788259830737:ios:1715e5481afc3b9097bef0 \
  --bundle-id com.zll.sumaiguard \
  --destination \
  "$repository_path/ios/SumaiGuard/Resources/GoogleService-Info.plist" \
  --config-base64-env FIREBASE_IOS_CONFIG_BASE64
