#!/usr/bin/env bash

function run_ycsb () {
    local repo_root="/app"
    local default_hosts=( mongo-server-0.mongo-server )
    local workload_name="ycsb_load/workloadEvergreen_load"
    local result_path="/tmp/ycsb_result"

    local mongo_dir=/mnt/azure
    local properties=()
    local hosts=()
    local w=${repo_root}/scripts/client
    local ycsb_mongodb=${repo_root}/scripts/src/YCSB/ycsb-mongodb/
    local ts=$(date +%s)
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
              -p <name=value> : set name property to value, default: ${properties}.
              -w <workload> : set the workload to run, default: ${workload_name}.
              -o <output> : set the output file, default: ${result_path}.

              <workloads>: defaults to ${workloads[@]}

run like:
    > ~/scripts/run_ycsb.sh  -c -t perf-2734-d32sv3.centosv79 scripts/client/ycsb_short/workloadEvergreen_short # Run a quick workload on a single host
    > ~/scripts/run_ycsb.sh  -c -t perf-2734-d32sv3.centosv79 scripts/client/ycsb_load/workloadEvergreen_load   # Run one specific workload on a single host
    > ~/scripts/run_ycsb.sh  -c # Run all default workloads on all hosts
    > ~/scripts/run_ycsb.sh  -c -t perf-2734-d32sv3.centosv79
EOF
    }

    while getopts "t:y:d:n:w:o:cp:" o; do
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
            p)
                properties+=(-p ${OPTARG})
                ;;
            w)
                workload_name=${OPTARG}
                ;;
            o)
                result_path=${OPTARG}
                ;;
            *)
                usage
                return
            ;;
        esac
    done
    shift $((OPTIND-1))

    local classpath=${ycsb_mongodb}/core/target/core-0.1.4.jar:${ycsb_mongodb}/mongodb/target/mongodb-binding-0.1.4.jar:${ycsb_mongodb}/mongodb/target/archive-tmp/mongodb-binding-0.1.4.jar

    if [ ${#hosts[@]} -eq 0 ]; then
        hosts=( "${default_hosts[@]}")
    fi

    local workload=${w}/${workload_name}

    echo "hosts: ${hosts[@]}"
    echo "clean: ${clean}"

    for host in "${hosts[@]}"; do
        
        local host_workload=${workload}.${host}

        sed 's/username:password@10.2.0.200/'${host}'/g' ${workload} > ${workload}.${host}

        local params=(-threads 8 -load)
        local preload=true
        local load_params=(-threads 8 -load)

        if  [[ "${workload}" == *workloadEvergreen_load ]]; then
            # Command line: -db com.yahoo.ycsb.db.MongoDbClient -s -P ../../../workloadEvergreen -threads 8 -load
            params=(-threads 8 -load)
            preload=false
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
        if [ "$preload" = true ]; then
            
            echo "Pre loading data into MongoDB"
            echo "java com.yahoo.ycsb.Client -db com.yahoo.ycsb.db.MongoDbClient -s -P ${workload}.${host} ${load_params[@]}"
            
            java -cp $classpath \
                com.yahoo.ycsb.Client \
                -db com.yahoo.ycsb.db.MongoDbClient \
                -s \
                -P ${workload}.${host} \
                "${load_params[@]}" >&1 | tee /tmp/ycsb_preload_result
        fi

        echo "java com.yahoo.ycsb.Client -db com.yahoo.ycsb.db.MongoDbClient -s -P ${workload}.${host} ${params[@]}"

        java -cp $classpath \
            com.yahoo.ycsb.Client \
            -db com.yahoo.ycsb.db.MongoDbClient \
            -s \
            -P ${workload}.${host} \
            "${params[@]}" >&1 | tee ${result_path}
    done
}

run_ycsb "$@"
