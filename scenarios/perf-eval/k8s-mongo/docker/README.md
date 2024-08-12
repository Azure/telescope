# Creating and publishing FIO image

## Building the package
The fio package used uses the source code which is a private fork from the public repository which can be found [here](https://msazure.visualstudio.com/One/_git/Storage-storagetests-OSS-fio). This also has a nuget package published to the feed [here](https://msazure.visualstudio.com/One/_artifacts/feed/Storage-XPerfInfra/NuGet/Fio_Linux/overview/3.18.0.19). To build the docker image, we need to download the nuget package and copy the binary to the docker image.

To download the nuget package, the directory contains the `nuget.config` and `packages.config` file.
Run:
```
nuget restore ./packages.config
```

Make sure the dockerfile points to the correct path of the fio executable in the COPY command.
Build the docker image by running:
```
docker buildx build -t telescope.azurecr.io/perf-eval/fio:1.0.0 .
```

## Publishing the package

Use docker push command to push to the telescope container registry:
```
docker push telescope.azurecr.io/perf-eval/fio:<version>
```

Once pushed, update the version to be used in the deployment files (fio.yml)