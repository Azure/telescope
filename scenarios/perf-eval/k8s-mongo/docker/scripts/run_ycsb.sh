#!/usr/bin/env bash

function run_ycsb () {
    local repo_root=$1
    local host=$2
    local workload_name=$3 
    local result_path=$4

    local w=${repo_root}/scripts/client
    local ycsb_mongodb=${repo_root}/scripts/src/YCSB/ycsb-mongodb/
    local ts=$(date +%s)
    local clean=false
    local numactl_prefix="numactl --interleave=all"

    local classpath=${ycsb_mongodb}/core/target/core-0.1.4.jar:${ycsb_mongodb}/mongodb/target/mongodb-binding-0.1.4.jar:${ycsb_mongodb}/mongodb/target/archive-tmp/mongodb-binding-0.1.4.jar

    local workload=${w}/${workload_name}
    local host_workload=${workload}.${host}

    echo $host $workload $result_path $host_workload
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

    java -cp $classpath \
        com.yahoo.ycsb.Client \
        -db com.yahoo.ycsb.db.MongoDbClient \
        -s \
        -P ${workload}.${host} \
        "${params[@]}" >&1 | tee ${result_path}
}

run_ycsb "$@"
