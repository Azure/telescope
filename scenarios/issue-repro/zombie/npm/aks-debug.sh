#! /bin/bash

LOG_DIR="/var/log/azure"

### START CONFIGURATION
PREFIX="aks_debug_logs"
SUFFIX=0

# Log bundle upload max size is limited to 100MB
MAX_SIZE=104857600

command -v zip >/dev/null || {
  echo "Error: zip utility not found. Please install zip."
  exit 255
}

# Function to clean up the output directory and log termination
function cleanup {
  # Make sure WORKDIR is a proper temp directory so we don't rm something we shouldn't
  workdir=$1
  if [[ $workdir =~ ^/tmp/tmp\.[a-zA-Z0-9]+$ ]]; then
    if [[ "$DEBUG" != "1" ]]; then
      echo "Cleaning up $workdir..."
      rm -rf "$workdir"
    else
      echo "DEBUG active or $workdir looks wrong; leaving $workdir behind."
    fi
  else
    echo "ERROR: WORKDIR ($workdir) doesn't look like a proper mktemp directory; not removing it for safety reasons!"
    exit 255
  fi
  echo "Log collection finished."
}

# This function runs a command and dumps its output to a named pipe, then includes that named
# pipe into a zip file. It's used to include command output in the ZIP file without taking up
# any disk space aside from the ZIP file itself.
# USAGE: collectToZip FILENAME CMDTORUN
function collectToZip {
  mkfifo "${1}"
  ${@:2} >"${1}" 2>&1 &
  zip -gumDZ deflate --fifo "${ZIP}" "${1}"
}

while true
do
  ZIP="${PREFIX}_${SUFFIX}.zip"

  # Create a temporary directory to store results in
  WORKDIR="$(mktemp -d)"
  # check if tmp dir was created
  if [[ ! "$WORKDIR" || "$WORKDIR" == "/" || "$WORKDIR" == "/tmp" || ! -d "$WORKDIR" ]]; then
    echo "ERROR: Could not create temporary working directory."
    exit 1
  fi
  cd $WORKDIR
  echo "Created temporary directory: $WORKDIR"

  mkdir collect

  # Create the ZIP in the first place
  zip -DZ deflate "${ZIP}" /proc/cgroups

  # Check if the log bundle size exceeds the limit
  FILE_SIZE=$(stat --printf "%s" ${ZIP})
  FILE_SUFFIX=0

  while [ $FILE_SIZE -le $MAX_SIZE ]
  do
    # Execute the cleanup function if the script terminates
    trap "exit 1" HUP INT PIPE QUIT TERM
    trap "cleanup $WORKDIR" EXIT

    echo "Collecting debug information..."
    # Collect process information
    collectToZip collect/ps${FILE_SUFFIX}.txt ps -auxf
    mkfifo collect/lsof${FILE_SUFFIX}.txt
    lsof 2> /dev/null | wc -l > collect/lsof${FILE_SUFFIX}.txt 2>&1 &
    zip -gumDZ deflate --fifo "${ZIP}" collect/lsof${FILE_SUFFIX}.txt
    echo "Collected process information with file suffix $FILE_SUFFIX."

    cp ${ZIP} ${LOG_DIR}/${ZIP}
    echo -n "Copy to log directory ${LOG_DIR} done."

    FILE_SIZE=$(stat --printf "%s" ${ZIP})
    FILE_SUFFIX=$((FILE_SUFFIX+1))
  done

  echo "Log bundle size: $(du -hs ${ZIP})"
  mkdir -p /var/lib/waagent/logcollector
  cp ${ZIP} /var/lib/waagent/logcollector/logs.zip
  echo -n "Uploading log bundle: "
  /usr/bin/env python3 /opt/azure/containers/aks-log-collector-send.py
  SUFFIX=$((SUFFIX+1))
  sleep 10
done
