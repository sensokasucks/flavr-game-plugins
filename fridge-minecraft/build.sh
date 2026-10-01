#!/usr/bin/env bash
# Build both Fridge Minecraft jars and copy them into jars/
set -euo pipefail
cd "$(dirname "$0")"

echo "========================================"
echo " Fridge Minecraft - build both jars"
echo "========================================"

if ! command -v java >/dev/null 2>&1; then
  echo "[ERROR] java not on PATH — install JDK 21"
  exit 1
fi
java -version

ensure_wrapper() {
  local wrap="$1/gradle/wrapper/gradle-wrapper.jar"
  if [[ -f "$wrap" ]]; then
    echo "Wrapper OK: $wrap"
    return 0
  fi
  echo "Missing $wrap — downloading Gradle wrapper"
  mkdir -p "$1/gradle/wrapper"
  curl -fsSL "https://github.com/gradle/gradle/raw/v8.14.3/gradle/wrapper/gradle-wrapper.jar" -o "$wrap"
}

ensure_wrapper client-mod
ensure_wrapper server-mod

echo
echo "-------- client-mod --------"
( cd client-mod && ./gradlew build --warning-mode none )

echo
echo "-------- server-mod --------"
( cd server-mod && ./gradlew build --warning-mode none )

mkdir -p jars

pick_jar() {
  local dir="$1" pattern="$2"
  local found=""
  for f in "$dir"/build/libs/${pattern}; do
    [[ -f "$f" ]] || continue
    case "$f" in
      *-sources.jar|*-dev.jar|*-dev-*.jar) continue ;;
    esac
    found="$f"
  done
  if [[ -z "$found" ]]; then
    echo "[ERROR] no jar matching $pattern in $dir/build/libs/"
    exit 1
  fi
  echo "$found"
}

CLIENT_JAR=$(pick_jar client-mod "fridge-minecraft-client-*.jar")
SERVER_JAR=$(pick_jar server-mod "fridge-minecraft-server-*.jar")

cp -f "$CLIENT_JAR" jars/
cp -f "$SERVER_JAR" jars/
echo
echo "Copied:"
echo "  jars/$(basename "$CLIENT_JAR")"
echo "  jars/$(basename "$SERVER_JAR")"
echo
echo "BUILD OK — drop jars/*.jar into .minecraft/mods/ (with Fabric API)"
echo "Stream Core needs minecraft.enabled: true"
