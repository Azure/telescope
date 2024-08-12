source ./modules/bash/utils.sh

set -e

if $DEBUG; then
    set -x
fi

dummy_method() {
    local value = $1
    echo "Check setup: $value"

    local version=`mongosh --version`
    echo $version
}