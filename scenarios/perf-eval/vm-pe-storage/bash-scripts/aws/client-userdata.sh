#!/bin/bash

# change ssh port
sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# install java
sudo apt-get update
sudo apt-get install default-jre -y
java -version

# install jmeter
jmeter_version="5.6.2"
wget https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${jmeter_version}.tgz
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
sudo chmod 777 /opt/jmeter/lib

# generate certs
sudo mkdir -p /etc/ssl/certs/jmeter

cat <<EOF > /etc/ssl/certs/jmeter/client.crt
-----BEGIN CERTIFICATE-----
MIIDfTCCAmUCFBRG+yBOCB85DmI71r4FgZcIirSsMA0GCSqGSIb3DQEBCwUAMHsx
CzAJBgNVBAYTAlVTMREwDwYDVQQIDAhOZXcgWW9yazERMA8GA1UEBwwITmV3IFlv
cmsxFDASBgNVBAoMC0V4YW1wbGUgT3JnMRYwFAYDVQQLDA1JVCBEZXBhcnRtZW50
MRgwFgYDVQQDDA93d3cuZXhhbXBsZS5jb20wHhcNMjMxMDExMjEzMDQ5WhcNMjQx
MDEwMjEzMDQ5WjB7MQswCQYDVQQGEwJVUzERMA8GA1UECAwITmV3IFlvcmsxETAP
BgNVBAcMCE5ldyBZb3JrMRQwEgYDVQQKDAtFeGFtcGxlIE9yZzEWMBQGA1UECwwN
SVQgRGVwYXJ0bWVudDEYMBYGA1UEAwwPd3d3LmV4YW1wbGUuY29tMIIBIjANBgkq
hkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwiNpIVM94F13/+bIp5L/97WMfg07m4XG
YQC8WN5Zr9zoj1mvOI8f56n1FH1xTUdOaHpxfSAMiYenzasqBpSgfjYFHmGxogXr
6USuKBycmoQ804VG6DDTUBlIXiopzzqwStG/kiJixEAoo9m5KCF7/IxOAtoiDlp+
EaiWEa03FI3xhX+4ude4lc1uGz1312Q8sfxmbgG+W80ufAci2prCWFxVIzwmSe/a
cxx2OkBW//bGwrhk46lzCnpA1gHH0zQ3/kHrDPXMnBMYXTao7wd7VzmT/oWT/RgH
GgOuO9mjSZu/mQykw91YKtpGvDw8U6g7EU7iBK1WJa9vr8Jbtcb7KQIDAQABMA0G
CSqGSIb3DQEBCwUAA4IBAQACJG1CXXhkkG2/OPNH1wOJYeUxyiuEQ9DH74gkO9sc
UvX8TfQqwTunRUb3OvkWGgg13cb2cTUrFCoEzb+9u9P6BkZ3TplLZiHKOLcErnlK
HM2EItyHxw2X+YJL1Daqig81CPgDNOJHNk9fmAFNOwPF3aZNIu3e105D7i8fz395
NOS3cyLJd3CnyTRr1FzXO2Oo7xMky7B3eJGYLdrhJ+FOvPPMBZMVFbxZXYf8E+ra
92geceLeG5pNkjzik3HYnElEdVn8Biq4Be4awuGkQozWjJuyxIlWeznYaFD9Y1rM
2RdgM/a0glax972j9j6O5ExL2Oni/wcjGzCqATpkMBV/
-----END CERTIFICATE-----
EOF

cat <<EOF > /etc/ssl/certs/jmeter/client.key
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDCI2khUz3gXXf/
5sinkv/3tYx+DTubhcZhALxY3lmv3OiPWa84jx/nqfUUfXFNR05oenF9IAyJh6fN
qyoGlKB+NgUeYbGiBevpRK4oHJyahDzThUboMNNQGUheKinPOrBK0b+SImLEQCij
2bkoIXv8jE4C2iIOWn4RqJYRrTcUjfGFf7i517iVzW4bPXfXZDyx/GZuAb5bzS58
ByLamsJYXFUjPCZJ79pzHHY6QFb/9sbCuGTjqXMKekDWAcfTNDf+QesM9cycExhd
NqjvB3tXOZP+hZP9GAcaA6472aNJm7+ZDKTD3Vgq2ka8PDxTqDsRTuIErVYlr2+v
wlu1xvspAgMBAAECggEAV00TNqA3QBDoKJSAgRLStnLWpcyPlIVYy0BIcnIyxKnD
jssWx4ldIJFGG5u5erXpJYSCSnFCEgqFxDAHawQlE/x42su11JVzG+f9pR4Qsk9r
Bvd1Bm8GZ4unBmlRedX7dvnRewapgXUUkXIUGF7OYag6YH/1Np0s+gXkzjglf8D4
aImD4r+JE9mwZko/xl0vw2Ubqgr723ADs1/u0Ui+imNg1vU3xCXiZuyW57NCatg6
LGsDy1G5LViR9J9fDG4Gp4kugNSWReTot+IoX3jAYpW3Wy5FBHngJUbdkj0beMND
DjN9x+PGMZzmPzP2x+3v5bqBKcg3lewW2pB2H8prrQKBgQDiD30XzyDDmF5hWTt0
4bNehu+aWSrjJX53TrEFTkkgLmEpq9/Fn8h+Px0NOKrATE+5FZhpcWdNLsQ8TQai
2fdqzD9LVpNVQ+8QATgoGV7+q8xVA+UIg0yY93vzim3fRostaoHEN+fYQmfSg4Wf
svNDYfQhOrwTY8jvIDZCGK5QpwKBgQDb2ZxDXGQtFYYDyOzk4/HXgCTknpWRw5px
e1yce21sULBcEHf8V04NxACuDX36TOK2UbTd+Fj0T1Au5cI98vKk5M5W5uyN/plC
qjwNuWiXHfvGUwhvB5gWas99ZDfU4d4CKgnC1ecCg9JhWoK8dL84FvI/JiEGUMUq
Uvk4/u1/rwKBgQCWyB/2/ofrDrl9EyiuSFD8ruIoQGtzwLF+4LUARfxOg8D5K5QB
XBc95dj51Z9Gzl+qozXatvJhL91iHzpa6ym1SXC6To/NIpfVRArx7CJJmcubtRJS
QEmaChDaG643a/UvIMhXWbbBr2FSr7k0EQdjHXXZqDSEdl0y6nhmU9IJJwKBgH9Y
2+VA/V4IG6rRljc3unzD45ryKV1X2nxlos2ZyVZ2ntGVUItA3xumL2aithhotOI7
DfONyakq0B16RTuxINBXIRbBiMDve0NcbJDelzEB0zecHUSDN5u0nx/ZD2Ymt3y1
cRYE5V1VkmWGEjirv5/z2rqtkW+hFbRgf7B+KoBNAoGBAIWBsm7Uq/jmQEMApt9E
4/Fn199gN6nj17+4B1Vvdh5/hBmw3YFmpgvCAwE2o6DtHpYJzrQkgECEyoj9rUak
1iGGVG1ii1O7Ra7UV9BfhrD+XS+CDNsDhO8MBV2eOGUF7T5i7FJuw0KV+ujN3HUA
WwGHz32zuMM7NdL/UBLdJgR3
-----END PRIVATE KEY-----
EOF

sudo chmod 644 /etc/ssl/certs/jmeter/*.crt
sudo chmod 600 /etc/ssl/certs/jmeter/*.key

# convert to PKCS12 format
openssl pkcs12 -export -out /etc/ssl/certs/jmeter/client.p12 -inkey /etc/ssl/certs/jmeter/client.key -in /etc/ssl/certs/jmeter/client.crt -passout pass:123456

# create keystore
keytool -importkeystore -srckeystore /etc/ssl/certs/jmeter/client.p12 -srcstoretype PKCS12 -srcstorepass 123456 -keystore /etc/ssl/certs/jmeter/client.keystore -storepass 123456
sudo chmod 644 /etc/ssl/certs/jmeter/client.keystore

# create alias file
mkdir -p /tmp/jmeter
cat <<EOF > /tmp/jmeter/alias.csv
cert_name
1
EOF

chown -R ubuntu:ubuntu /tmp/jmeter