#!/usr/bin/env bash

#
# This assumes mongo is already installed.
#
#sudo tee /etc/yum.repos.d/mongodb-org-5.0.repo<<EOF
#[mongodb-org-5.0]
#name=MongoDB Repository
#baseurl=https://repo.mongodb.org/yum/redhat/\$releasever/mongodb-org/5.0/x86_64/
#gpgcheck=1
#enabled=1
#gpgkey=https://www.mongodb.org/static/pgp/server-5.0.asc
#EOF
#
# sudo yum install mongodb-org  mongodb-org-shell -y
# sudo yum install numactl -y
#
#
function setup_mongodb () {
    local dbRoot=$(pwd)
    local dbUser=$(whoami)

    function usage(){
        cat <<EOF
setup_mongodb [-h] [-d dbPath]
              -h|--help : display this message and exit
              -d <dbRoot> : Set the db root, default: ${dbRoot}.
              -u <dbUser> : Set the dbpath, default: ${dbUser}.
EOF
    }
    while getopts "hd:" o; do
        case "${o}" in
            d)
                dbRoot=${OPTARG}
                ;;
            *)
                usage
                return
            ;;
        esac
    done
    shift $((OPTIND-1))

mkdir -pv ${dbRoot}/{dbs,logs}

sudo sed -i.bak '/# mongo ulimits/d' /etc/security/limits.conf
cat <<EOF | sudo tee -a /etc/security/limits.conf > /dev/null
${dbUser}        soft    nofile          65535       # mongo ulimits
${dbUser}        hard    nofile          65535       # mongo ulimits
${dbUser}        hard    nproc           65535       # mongo ulimits
${dbUser}        soft    nproc           65535       # mongo ulimits
${dbUser}        soft    core            unlimited   # mongo ulimits
${dbUser}        hard    core            unlimited   # mongo ulimits
EOF

# echo "${dbUser}        soft    nofile          65535" | sudo tee -a /etc/security/limits.conf > /dev/null
# echo "${dbUser}        hard    nofile          65535" | sudo tee -a /etc/security/limits.conf > /dev/null
# echo "${dbUser}        hard    nproc           65535" | sudo tee -a /etc/security/limits.conf > /dev/null
# echo "${dbUser}        soft    nproc           65535" | sudo tee -a /etc/security/limits.conf > /dev/null
# echo "${dbUser}        soft    core            unlimited" | sudo tee -a /etc/security/limits.conf > /dev/null
# echo "${dbUser}        hard    core            unlimited" | sudo tee -a /etc/security/limits.conf > /dev/null
# For control of core dumps and file names:
# http://man7.org/linux/man-pages/man5/core.5.html
echo "${dbRoot}/logs/core.%e.%p.%h.%t" |sudo tee -a  /proc/sys/kernel/core_pattern > /dev/null

echo "never" | sudo tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null
echo "never" | sudo tee /sys/kernel/mm/transparent_hugepage/defrag > /dev/null

cat << EOF | tee /tmp/mongo_port_27017.conf
net:
  port: 27017
  bindIp: 0.0.0.0
processManagement:
  fork: true
replication:
   replSetName: "rs0"
storage:
  dbPath: ${dbRoot}/dbs
  engine: wiredTiger
systemLog:
  destination: file
  path: ${dbRoot}/logs/mongod.log
EOF
}


setup_mongodb "$@"
