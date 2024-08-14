#!/usr/bin/env bash
# Run as root

# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/azure-to-guest-disk-mapping#listing-block-devices

# [azureuser@PERF-2734-DAS-v4 scripts]$ sudo lsscsi
# [0:0:0:0]    disk    Msft     Virtual Disk     1.0   /dev/sda
# [0:0:0:1]    disk    Msft     Virtual Disk     1.0   /dev/sdb
# [1:0:0:0]    disk    Msft     Virtual Disk     1.0   /dev/sdc
# [1:0:0:1]    disk    Msft     Virtual Disk     1.0   /dev/sdd
# [1:0:0:2]    disk    Msft     Virtual Disk     1.0   /dev/sde
#The last column listed will contain the LUN, the format is [Host:Channel:Target:LUN]
# I assume that should read first column and the Host is not 0!

# Based on the output above ...:
#
# sudo ./disk.sh -d /dev/sdc -m /mnts/P50_4TB_NoCache
# sudo ./disk.sh -d /dev/sdd -m /mnts/P50_2TB_NoCache
# sudo ./disk.sh -d /dev/sde -m /mnts/P50_2TB_Cache
# sudo ./disk.sh -d /dev/sdg -m /mnts/P10_128_Cache
# sudo ./disk.sh -d /dev/sdf -m /mnts/P10_128_NoCache
#

#| Size    | Performance tier | Provisioned IOPS | Provisioned throughput | Max Shares | Max burst IOPS | Max burst throughput |
#| 128 GiB | P10              | 500              | 100                    | 3          | 3500           | 170                  |

# For disk bursting, credits accumulate in a burst bucket whenever disk traffic is below the provisioned performance target for
# their disk size, and consume credits when traffic bursts beyond the target. Disk traffic is tracked against both IOPS and
# throughput in the provisioned target. Disk bursting is enabled by default on supported sizes.
# Learn more @  https://docs.microsoft.com/en-gb/azure/virtual-machines/disk-bursting

function configure_disk () {
    local device=/dev/sdc
    local mount_point=/mnts/cached
    local user=azureuser

    function usage(){
        cat <<EOF
configure_disk [-h] [-d device] [-m mount] [-u user]
              -h|--help : display this message and exit
              -d <device> : The target device, default: $device.
              -m <mount> : The mount point, default: $disk.
              -o <owner> : The mount owner, default: $user.
EOF
    }
    while getopts ":hd:m:o:" o; do
        case "${o}" in
            d)
                device=${OPTARG}
                ;;
            m)
                mount_point=${OPTARG}
                ;;
            o)
                owner=${OPTARG}
                ;;
            *)
                usage
                return
            ;;
        esac
    done
    shift $((OPTIND-1))


    umount ${device}

    parted ${device} --script mklabel gpt mkpart xfspart xfs 0% 100%
    mkfs.xfs -f ${device}
    partprobe ${device}
    mkdir -p ${mount_point}/ms
    mount -o noatime ${device} ${mount_point}

    echo 256 >  /sys/block/$(basename $device)/queue/nr_requests
    echo deadline  > /sys/block/$(basename $device)/queue/scheduler
    blockdev --setra 256 ${device}
    blockdev --report


    umount ${device}
    mount -o noatime ${device} ${mount_point}
    chown -Rv $user  ${mount_point}

    echo "-------------------- $device --------------------"
    echo "$(cat /sys/block/${device}/queue/nr_requests): Requests: ${device} "
    echo "$(cat /sys/block/${device}/queue/scheduler) Scheduler: /dev/sd$dev"
    sudo sudo     blockdev --report /dev/${device}
    mount | grep $device
    df -h | grep $device
    echo "-------------------------------------------------"

}


configure_disk "$@"
