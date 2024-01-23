sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# install java
sudo apt update
sudo sudo apt install default-jre -y
java -version

# install jmeter
jmeter_version="5.6.2"
wget https://downloads.apache.org/jmeter/binaries/apache-jmeter-${jmeter_version}.tgz
tar -xvf apache-jmeter-${jmeter_version}.tgz
sudo mv apache-jmeter-${jmeter_version} /opt/jmeter
sudo ln -s /opt/jmeter/bin/jmeter /usr/local/bin/jmeter
jmeter -v

# install plugin
cd /opt/jmeter/lib
cmdrunner_version="2.2"
curl -O "https://repo1.maven.org/maven2/kg/apc/cmdrunner/${cmdrunner_version}/cmdrunner-${cmdrunner_version}.jar"
cd /opt/jmeter/lib/ext
jpm_version="1.7"
curl -O "https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-manager/${jpm_version}/jmeter-plugins-manager-${jpm_version}.jar"
cd /opt/jmeter/lib
plugin_version="2.2"
java -jar cmdrunner-${cmdrunner_version}.jar --tool org.jmeterplugins.repository.PluginManagerCMD install jpgc-synthesis,jpgc-cmd=${plugin_version}

mkdir -p /tmp/jmeter
chown -R ubuntu:ubuntu /tmp/jmeter
