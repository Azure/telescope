#!/bin/bash
set -e

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get -qq update
sudo apt-get -qq install gcc

sudo bash -c 'cat >> /etc/security/limits.conf' << EOF
* soft nofile 1048575
* hard nofile 1048575
EOF

sudo bash -c 'cat >> /etc/rc.local' << EOF
#!/bin/sh
sysctl -w net.ipv4.tcp_tw_reuse=1 # TIME_WAIT work-around
iptables -t raw -I OUTPUT -j NOTRACK # disable connection tracking
iptables -t raw -I PREROUTING -j NOTRACK # disable connection tracking
sysctl -w net.netfilter.nf_conntrack_max=0 # needed on some kernels
sysctl -w net.ipv4.tcp_syncookies=0
sysctl -w net.ipv4.tcp_max_syn_backlog=2048
sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w fs.file-max=1048576
EOF
chmod +x /etc/rc.local

wget https://telescopetools.z13.web.core.windows.net/packages/network-tools/ncps/ncps_1.1.tar.gz
tar -xzf ncps_1.1.tar.gz
cp ncps/ncps /bin/ncps
nohup ncps -s &> /dev/null &
