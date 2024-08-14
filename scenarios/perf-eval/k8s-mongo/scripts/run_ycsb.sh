#!/usr/bin/env bash

#
# Centos
# sudo yum install epel-release 
# sudo yum install fio expect htop screen glances numactl -y 
#
# Ubuntu
# sudo apt update
# sudo apt install expect fio screen glances numactl -y 
# 
function run_ycsb () {
    local default_hosts=( perf-2734-l16sv3.centosv79 perf-2734-d32sv3.centosv79 )
    local hosts=( )
    local w=~/scripts/client
    local workloads=( ${w}/ycsb_load/workloadEvergreen_load ${w}/ycsb_100read/workloadEvergreen_100read ${w}/ycsb_95read5update/workloadEvergreen_95read5update ${w}/ycsb_100update/workloadEvergreen_100update ${w}/ycsb_50read50update/workloadEvergreen_50read50update )
    local ycsb_mongodb=~/scripts/src/YCSB/ycsb-mongodb/
    local mongo_dir=/mnts/P40_2TB_Cache/mongo
    local ts=$(date +%s)
    # local device=$(basename $(dirname $mongo_dir))
    # local directory=~/reports/ycsb.${device}.${ts}/
    local clean=false
    local numactl_prefix="numactl --interleave=all"
    function usage(){
        cat <<EOF
run_ycsb [-h] [-t target] [-y ycsb_mongodb] [-d mongo_dir] [-n numa command] [-c classpath]  <workloads>*
              -h|--help : display this message and exit
              -t <target> : The target host, default: ${default_targets[@]}.
              -y <ycsb mongo> : The ycsb mongodb source, default: ${ycsb_mongodb}.
              -d <mongo_dir> : The mongo directory, default: ${mongo_dir}.
              -c : Clean the target, default: ${clean}.
              -n <numa prefix> : Clean the target, default: ${numactl_prefix}.
              <workloads>: defaults to ${workloads[@]}

run like:
    > ~/scripts/run_ycsb.sh  -c -t perf-2734-d32sv3.centosv79 scripts/client/ycsb_short/workloadEvergreen_short # Run a quick workload on a single host
    > ~/scripts/run_ycsb.sh  -c -t perf-2734-d32sv3.centosv79 scripts/client/ycsb_load/workloadEvergreen_load   # Run one specific workload on a single host
    > ~/scripts/run_ycsb.sh  -c # Run all default workloads on all hosts
    > ~/scripts/run_ycsb.sh  -c -t perf-2734-d32sv3.centosv79
EOF
    }
    while getopts "t:y:d:n:c" o; do
        case "${o}" in
            t)
                hosts+=(${OPTARG})
                ;;
            d)
                mongo_dir=${OPTARG}
                ;;
            y)
                ycsb_mongodb=${OPTARG}
                ;;
            n)
                numactl_prefix="${OPTARG}"
                ;;
            c)
                clean=true
                ;;
            *)
                usage
                return
            ;;
        esac
    done
    shift $((OPTIND-1))

    local device=$(basename $(dirname $mongo_dir))
    local out_directory=~/PERF-3184-reports.${ts}/ycsb.${device}

    local classpath=${ycsb_mongodb}/core/target/core-0.1.4.jar:${ycsb_mongodb}/mongodb/target/mongodb-binding-0.1.4.jar:${ycsb_mongodb}/mongodb/target/archive-tmp/mongodb-binding-0.1.4.jar

    if [ $# -ne 0 ]; then
        workloads=( "$@" )
    fi

    if [ ${#hosts[@]} -eq 0 ]; then
        hosts=( "${default_hosts[@]}")
    fi

    
    echo "hosts: ${hosts[@]}"
    echo "workloads: ${workloads[@]}"
    echo "clean: ${clean}"

    # local ts=$(date +%s)
    for host in "${hosts[@]}"; do
        local report_dir=${out_directory}/${host}
        mkdir -pv $report_dir

        echo "Starting Clean Database"
        CMDS=$(cat <<CMD 
function pause(){
    echo "\$@"
    for i in \$(seq 0 10); do 
        echo \$((10 -i))
        sleep 1
    done
}
mongo --host "mongodb://localhost/admin" --quiet --eval "printjson(db.shutdownServer())"
pause Waiting for mongodb to stop
rm -rf ${mongo_dir}
mkdir -pv ${mongo_dir}/{dbs,logs}
cd ${mongo_dir}
~/scripts/setup_mongodb.sh
${numactl_prefix} mongod -f /tmp/mongo_port_27017.conf
pause  Waiting for mongodb to start
mongo --host "mongodb://localhost/admin" --quiet --eval "rs.initiate()"; 
pause Waiting for replset to start
CMD
) 

        echo "$CMDS"
        ssh $host -t "$CMDS"
    done
    
    for workload in "${workloads[@]}"; do
        for host in "${hosts[@]}"; do
            local report_dir=${out_directory}/${host}/$(basename ${workload})
            mkdir -pv $report_dir
            local out=${report_dir}/workload.log
            local host_workload=${workload}.${host}

            sed 's/username:password@10.2.0.200/'${host}'/g' ${workload}  > ${workload}.${host}

            local params=(-threads 8 -load)

            if  [[ "${workload}" == *workloadEvergreen_load ]]; then
                # Command line: -db com.yahoo.ycsb.db.MongoDbClient -s -P ../../../workloadEvergreen -threads 8 -load
                params=(-threads 8 -load)
            elif  [[ "${workload}" == *workloadEvergreen_100read ]]; then
                # Command line: -db com.yahoo.ycsb.db.MongoDbClient -s -P ../../../workloadEvergreen_100read -threads 128 -t
                params=(-threads 128 -t)
            elif  [[ "${workload}" == *workloadEvergreen_95read5update ]]; then
                # Command line: -db com.yahoo.ycsb.db.MongoDbClient -s -P ../../../workloadEvergreen_95read5update -threads 16 -t
                params=(-threads 16 -t)
            elif  [[ "${workload}" == *workloadEvergreen_100update ]]; then
                # Command line: -db com.yahoo.ycsb.db.MongoDbClient -s -P ../../../workloadEvergreen_100update -threads 32 -t
                params=(-threads 32 -t)
            elif  [[ "${workload}" == *workloadEvergreen_50read50update ]]; then
                # Command line: -db com.yahoo.ycsb.db.MongoDbClient -s -P ../../../workloadEvergreen_50read50update -threads 64 -t
                params=(-threads 64 -t)
            else
                params=(-threads 8 -load)
            fi

            echo "java com.yahoo.ycsb.Client -db com.yahoo.ycsb.db.MongoDbClient -s -P ${workload}.${host} ${params[@]}"

            unbuffer java -cp $classpath \
                 com.yahoo.ycsb.Client \
                 -db com.yahoo.ycsb.db.MongoDbClient \
                 -s \
                 -P ${workload}.${host} \
                 "${params[@]}" >&1 | tee ${out}

            # # Add Code to Rsync the diagnostics
            # mongo --host "mongodb://${host}/admin" --quiet --eval "printjson(db.adminCommand( { logRotate : 'server' } ))"
            ssh "${host}" 'mongo --host "mongodb://localhost/admin" --quiet --eval "printjson(db.shutdownServer())" ; true'
            rsync -rvp --exclude '*/*.wt'  --exclude '*/storage.bson' --exclude '*/WiredTiger*' --exclude '*/journal/*' ${host}:${mongo_dir}/ ${report_dir}
            if [ "$clean" = true ]; then
                echo "Cleaning Database"
        CMDS=$(cat <<CMD 
function pause(){
    echo "\$@"
    for i in \$(seq 0 10); do 
        echo \$((10 -i))
        sleep 1
    done
}
rm -rf ${mongo_dir}
mkdir -pv ${mongo_dir}/{dbs,logs};
${numactl_prefix} mongod -f /tmp/mongo_port_27017.conf
pause Wait for MongoDB to restart
mongo --host "mongodb://localhost/admin" --quiet --eval "rs.initiate()"
pause Wait for Replset to initiate
CMD
) 

                echo "$CMDS"
                ssh $host -t "$CMDS"
            else
                ssh "${host}" "${numactl_prefix} mongod -f /tmp/mongo_port_27017.conf"
                
            fi


        done
    done
}


run_ycsb "$@"
