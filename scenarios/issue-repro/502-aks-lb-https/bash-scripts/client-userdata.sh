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

