#!/usr/bin/env bash
# Build supplemental JVM Starlarky outside the repository. No gateway credentials are used.
set -euo pipefail
[ "$#" = 1 ] || { echo 'Usage: setup-jvm.sh /absolute/private/runtime-directory' >&2; exit 2; }
case "$1" in /*) ;; *) echo 'Use an absolute runtime directory' >&2; exit 2 ;; esac
umask 077
RUNTIME_DIR="$1"
JVM_IMAGE='maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320'
SOURCE_SHA='57e6799d904c047f17f0921e6d3b0696a4965d19c0a18e52a0f2e8d4cb13ef18'
[ ! -e "$RUNTIME_DIR/jvm" ] || { echo 'The JVM directory already exists; choose a new runtime directory.' >&2; exit 2; }
mkdir -p "$RUNTIME_DIR"
BUILD_DIR=$(mktemp -d "$RUNTIME_DIR/jvm-build.XXXXXX")
curl --fail --location 'https://github.com/verygoodsecurity/starlarky/archive/refs/tags/v1.0.0.tar.gz' -o "$BUILD_DIR/source.tar.gz"
python3 - "$BUILD_DIR/source.tar.gz" "$SOURCE_SHA" <<'PY'
import hashlib, pathlib, sys
if hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest() != sys.argv[2]:
    raise SystemExit('Official source checksum mismatch; stop without changing the pin.')
PY
tar -xzf "$BUILD_DIR/source.tar.gz" -C "$BUILD_DIR"
mkdir "$RUNTIME_DIR/jvm"
docker run --rm --mount "type=bind,source=$BUILD_DIR/starlarky-1.0.0,target=/source" \
  --mount "type=bind,source=$RUNTIME_DIR/jvm,target=/output" -w /source "$JVM_IMAGE" \
  sh -c 'mvn -B -DskipTests install && mvn -B -pl runlarky dependency:copy-dependencies -DincludeScope=runtime && cp runlarky/target/*.jar /output/ && cp runlarky/target/dependency/*.jar /output/'
python3 - "$RUNTIME_DIR/jvm" "$SOURCE_SHA" "$JVM_IMAGE" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.jar'))}
if not any(n.startswith('runlarky-') for n in files):
    raise SystemExit('Missing runtime JAR; retain the build directory for diagnosis.')
(root/'build.json').write_text(json.dumps({'source':'https://github.com/verygoodsecurity/starlarky/tree/v1.0.0',
 'sourceModified':False,'sourceArchiveSha256':sys.argv[2],'image':sys.argv[3],'files':files},indent=2)+'\n')
PY
echo 'Supplemental JVM runtime built; dependency hashes recorded in jvm/build.json.'
